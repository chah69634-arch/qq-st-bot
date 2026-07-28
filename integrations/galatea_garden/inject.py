"""One-shot stdin injector for Galatea Garden's upstream wake bridge.

This process deliberately only validates an upstream envelope and posts a bounded
low-trust hint to PresenceKit.  It owns no SSE connection, does not write runtime
state, and never calls MCP, the LLM, or a chat endpoint.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

MAX_INPUT_BYTES = 12 * 1024
MAX_REASON_CHARS = 128
MAX_MESSAGE_CHARS = 4096
SUCCESS_STATUSES = frozenset({"accepted", "pending", "coalesced"})
EXIT_SUCCESS = 0
EXIT_TEMPORARY = 1
EXIT_TERMINAL = 2


class InjectorInputError(ValueError):
    """Malformed upstream envelope or protected local configuration."""


def _report_error(category: str) -> None:
    """Emit a fixed, non-sensitive diagnostic for the bridge supervisor."""
    sys.stderr.write(f"garden injector: {category}\n")


def _local_opener(request: Request, *, timeout: int):
    """Open PresenceKit's local endpoint without inheriting environment proxies."""
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)


def _read_envelope(stream) -> dict[str, str | int]:
    raw = stream.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise InjectorInputError("stdin_too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InjectorInputError("stdin_not_utf8") from exc
    line = text.rstrip("\r\n")
    if not line or "\n" in line or "\r" in line:
        raise InjectorInputError("stdin_not_one_line")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise InjectorInputError("stdin_not_json") from exc
    return _validate_envelope(value)


def _validate_envelope(value: Any) -> dict[str, str | int]:
    if not isinstance(value, dict) or set(value) != {"version", "type", "reason", "message"}:
        raise InjectorInputError("invalid_envelope")
    reason = value.get("reason")
    message = value.get("message")
    if value.get("version") != 1 or value.get("type") != "garden_wake":
        raise InjectorInputError("unsupported_envelope")
    if not isinstance(reason, str) or not reason or len(reason) > MAX_REASON_CHARS or reason.strip() != reason:
        raise InjectorInputError("invalid_reason")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
        raise InjectorInputError("invalid_message")
    return {"version": 1, "type": "garden_wake", "reason": reason, "message": message}


def _local_config(environ: Mapping[str, str]) -> tuple[str, str, str, str]:
    base_url = str(environ.get("PRESENCE_BASE_URL") or "").strip().rstrip("/")
    token = str(environ.get("PRESENCE_INTEGRATION_TOKEN") or "").strip()
    uid = str(environ.get("PRESENCE_UID") or "").strip()
    char_id = str(environ.get("PRESENCE_CHAR_ID") or "").strip()
    parts = urlsplit(base_url)
    if not base_url or parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise InjectorInputError("invalid_presence_base_url")
    host = (parts.hostname or "").lower()
    if parts.scheme == "http" and host not in {"localhost", "::1"} and not host.endswith(".localhost") and not host.startswith("127."):
        raise InjectorInputError("insecure_nonlocal_presence_url")
    if not token or not uid or not char_id or len(uid) > 128 or len(char_id) > 128:
        raise InjectorInputError("missing_presence_configuration")
    return base_url, token, uid, char_id


def _request_body(envelope: Mapping[str, str | int], *, uid: str, char_id: str) -> bytes:
    # uid and char_id are intentionally sourced only from protected local config,
    # never from the untrusted upstream envelope.
    payload = {
        "provider": "galatea_garden",
        "reason": envelope["reason"],
        "message": envelope["message"],
        "received_at": datetime.now(timezone.utc).isoformat(),
        "uid": uid,
        "char_id": char_id,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def deliver(
    envelope: Mapping[str, str | int],
    *,
    environ: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> int:
    """Return the upstream bridge-compatible outcome code without logging secrets."""
    base_url, token, uid, char_id = _local_config(environ or os.environ)
    request = Request(
        f"{base_url}/integrations/garden/wake",
        data=_request_body(envelope, uid=uid, char_id=char_id),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with (opener or _local_opener)(request, timeout=10) as response:
            raw_status = getattr(response, "status", None)
            status_code = int(response.getcode() if raw_status is None else raw_status)
            response_body = response.read(16 * 1024)
    except HTTPError as exc:
        if exc.code == 401:
            _report_error("http_401")
            return EXIT_TERMINAL
        if exc.code == 403:
            _report_error("http_403")
            return EXIT_TERMINAL
        if 400 <= exc.code < 500:
            _report_error("http_4xx")
            return EXIT_TERMINAL
        _report_error("http_5xx" if exc.code >= 500 else "invalid_response")
        return EXIT_TEMPORARY
    except TimeoutError:
        _report_error("timeout")
        return EXIT_TEMPORARY
    except URLError as exc:
        _report_error("timeout" if isinstance(exc.reason, TimeoutError) else "connection_error")
        return EXIT_TEMPORARY
    except OSError:
        _report_error("connection_error")
        return EXIT_TEMPORARY
    except (AttributeError, TypeError, ValueError):
        _report_error("invalid_response")
        return EXIT_TEMPORARY
    if not 200 <= status_code < 300:
        if 400 <= status_code < 500:
            _report_error("http_401" if status_code == 401 else "http_403" if status_code == 403 else "http_4xx")
            return EXIT_TERMINAL
        _report_error("http_5xx" if status_code >= 500 else "invalid_response")
        return EXIT_TEMPORARY
    try:
        result = json.loads(response_body.decode("utf-8"))
    except (AttributeError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        _report_error("invalid_response")
        return EXIT_TEMPORARY
    if isinstance(result, dict) and str(result.get("status") or "") in SUCCESS_STATUSES:
        return EXIT_SUCCESS
    _report_error("invalid_response")
    return EXIT_TERMINAL if isinstance(result, dict) and result.get("status") == "malformed" else EXIT_TEMPORARY


def main() -> int:
    try:
        return deliver(_read_envelope(sys.stdin))
    except InjectorInputError as exc:
        sys.stderr.write(f"garden injector: {exc}\n")
        return EXIT_TERMINAL
    except Exception:
        # Do not render arbitrary exception strings: they can contain headers,
        # tokens, or the server-provided message.
        sys.stderr.write("garden injector: temporary_failure\n")
        return EXIT_TEMPORARY


if __name__ == "__main__":
    raise SystemExit(main())
