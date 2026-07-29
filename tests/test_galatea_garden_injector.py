"""Boundary tests for the one-shot Galatea Garden stdin injector."""

from __future__ import annotations

import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

import pytest

from integrations.galatea_garden import inject


def _envelope(**overrides):
    value = {
        "version": 1,
        "type": "garden_wake",
        "reason": "notification_available",
        "message": "你有新的 Garden 通知。请调用 Garden MCP 查看。",
    }
    value.update(overrides)
    return value


def _environment(**overrides):
    value = {
        "PRESENCE_BASE_URL": "http://127.0.0.1:8123",
        "PRESENCE_INTEGRATION_TOKEN": "test-token-not-for-logs",
        "PRESENCE_UID": "owner-1",
        "PRESENCE_CHAR_ID": "char-a",
    }
    value.update(overrides)
    return value


class _Response:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self._payload).encode("utf-8")

    def getcode(self):
        return self.status


@pytest.mark.parametrize("ack_status", ["accepted", "pending", "coalesced"])
def test_valid_envelope_posts_local_scope_and_returns_zero(ack_status):
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.get_header("Authorization")
        return _Response({"status": ack_status})

    code = inject.deliver(_envelope(), environ=_environment(), opener=opener)
    assert code == inject.EXIT_SUCCESS
    assert captured["url"] == "http://127.0.0.1:8123/integrations/garden/wake"
    assert captured["body"]["uid"] == "owner-1"
    assert captured["body"]["char_id"] == "char-a"
    assert captured["body"]["provider"] == "galatea_garden"
    assert captured["authorization"] == "Bearer test-token-not-for-logs"


@pytest.mark.parametrize("value", [
    _envelope(version=2),
    _envelope(type="forum_wake"),
    _envelope(reason=""),
    _envelope(reason="x" * 129),
    _envelope(message=" "),
    _envelope(message="x" * 4097),
    _envelope(uid="remote-owner"),
])
def test_invalid_or_scope_overriding_envelopes_are_terminal(value):
    with pytest.raises(inject.InjectorInputError):
        inject._validate_envelope(value)


def test_read_envelope_requires_exactly_one_json_line():
    class _Stream:
        buffer = io.BytesIO(b'{"version":1}\n{"version":1}\n')

    with pytest.raises(inject.InjectorInputError):
        inject._read_envelope(_Stream())


@pytest.mark.parametrize("code", [401, 403])
def test_auth_http_errors_are_terminal(code):
    def opener(*args, **kwargs):
        raise HTTPError("http://127.0.0.1", code, "failure", hdrs=None, fp=None)

    assert inject.deliver(_envelope(), environ=_environment(), opener=opener) == inject.EXIT_TERMINAL


def test_network_and_server_errors_are_retryable():
    def network(*args, **kwargs):
        raise URLError("offline")

    def server(*args, **kwargs):
        raise HTTPError("http://127.0.0.1", 503, "failure", hdrs=None, fp=None)

    assert inject.deliver(_envelope(), environ=_environment(), opener=network) == inject.EXIT_TEMPORARY
    assert inject.deliver(_envelope(), environ=_environment(), opener=server) == inject.EXIT_TEMPORARY


def test_default_local_request_ignores_environment_proxies(monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"accepted"}')

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Event()

    def serve():
        serving.set()
        server.serve_forever()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert serving.wait(timeout=2), "loopback test server did not start"
    proxy_names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    before = {name: os.environ.get(name) for name in proxy_names}
    try:
        environment = _environment(PRESENCE_BASE_URL=f"http://127.0.0.1:{server.server_port}")
        # First pollute the inherited proxy environment, then leave that scope
        # and make another request in the same process.  The injector must use
        # its explicit direct opener in both cases and the test must restore
        # the ambient process environment for following tests.
        with monkeypatch.context() as proxy_env:
            proxy_env.setenv("HTTP_PROXY", "http://127.0.0.1:1")
            proxy_env.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
            proxy_env.setenv("ALL_PROXY", "http://127.0.0.1:1")
            proxy_env.setenv("NO_PROXY", "")
            assert inject.deliver(_envelope(), environ=environment) == inject.EXIT_SUCCESS
        assert {name: os.environ.get(name) for name in proxy_names} == before
        assert inject.deliver(_envelope(), environ=environment) == inject.EXIT_SUCCESS
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert received == ["/integrations/garden/wake", "/integrations/garden/wake"]


@pytest.mark.parametrize(("failure", "expected"), [
    (HTTPError("http://127.0.0.1", 401, "failure", hdrs=None, fp=None), "http_401"),
    (HTTPError("http://127.0.0.1", 403, "failure", hdrs=None, fp=None), "http_403"),
    (HTTPError("http://127.0.0.1", 502, "failure", hdrs=None, fp=None), "http_5xx"),
    (URLError("offline"), "connection_error"),
    (TimeoutError(), "timeout"),
])
def test_delivery_errors_are_safe_and_categorized(failure, expected, capsys):
    message = "message-that-must-not-reach-stderr"
    token = _environment()["PRESENCE_INTEGRATION_TOKEN"]

    def opener(*args, **kwargs):
        raise failure

    expected_code = inject.EXIT_TERMINAL if expected in {"http_401", "http_403"} else inject.EXIT_TEMPORARY
    assert inject.deliver(_envelope(message=message), environ=_environment(), opener=opener) == expected_code
    stderr = capsys.readouterr().err
    assert f"garden injector: {expected}" in stderr
    assert token not in stderr
    assert message not in stderr


def test_malformed_response_is_not_acknowledged_and_logs_no_secret(monkeypatch, capsys):
    def opener(*args, **kwargs):
        return _Response({"status": "malformed"})

    assert inject.deliver(_envelope(), environ=_environment(), opener=opener) == inject.EXIT_TERMINAL

    class _BadStream:
        buffer = io.BytesIO(b"not json\n")

    monkeypatch.setattr(inject.sys, "stdin", _BadStream())
    assert inject.main() == inject.EXIT_TERMINAL
    stderr = capsys.readouterr().err
    assert "garden injector: invalid_response" in stderr
    assert "test-token-not-for-logs" not in stderr
    assert _envelope()["message"] not in stderr
