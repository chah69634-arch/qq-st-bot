"""Thin HTTP adapter for the frozen external companion runtime contract."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from admin.auth import require_scopes, security
from core.companion.models import (
    CONTRACT,
    MAX_BODY_BYTES,
    CompanionResponse,
    error_payload,
    parse_request,
    provenance_mismatch,
)
from core.companion.service import CompanionServiceError, handle_event, observability

router = APIRouter()
_companion_scope = require_scopes("companion.write")


async def _require_companion(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    try:
        return await _companion_scope(request, credentials)
    except HTTPException as exc:
        if exc.status_code == 401:
            detail = error_payload("UNAUTHORIZED", "companion authentication required", retryable=False)
        elif exc.status_code == 403:
            detail = error_payload("SCOPE_REQUIRED", "companion.write scope required", retryable=False)
        else:
            raise
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


_require_companion._required_scopes = ("companion.write",)


def _http_error(status_code: int, code: str, message: str, *, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_payload(code, message, retryable=retryable),
    )


@router.post(
    "/integrations/companion/events",
    response_model=CompanionResponse,
    summary="Submit one external companion event",
    responses={
        400: {"description": "Invalid companion request"},
        401: {"description": "Companion authentication required"},
        403: {"description": "Companion scope required"},
        409: {"description": "Companion session mismatch"},
        426: {"description": "Unsupported companion contract major"},
        503: {"description": "Companion runtime unavailable"},
    },
)
async def companion_event(
    request: Request,
    body: object = Body(...),
    auth=Depends(_require_companion),
):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise _http_error(400, "COMPANION_REQUEST_INVALID", "companion request is too large", retryable=False)
        except ValueError:
            raise _http_error(400, "COMPANION_REQUEST_INVALID", "invalid content length", retryable=False)
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        raise _http_error(400, "COMPANION_REQUEST_INVALID", "companion request is too large", retryable=False)
    if not isinstance(body, dict):
        raise _http_error(400, "COMPANION_REQUEST_INVALID", "request body must be an object", retryable=False)

    contract = body.get("contract")
    if isinstance(contract, str) and contract.startswith("presencekit-external-companion-") and contract != CONTRACT:
        raise _http_error(
            426,
            "COMPANION_CONTRACT_UNSUPPORTED",
            "unsupported companion contract major",
            retryable=False,
        )
    if contract != CONTRACT:
        raise _http_error(400, "COMPANION_REQUEST_INVALID", "invalid companion contract", retryable=False)

    try:
        parsed = parse_request(body)
    except ValidationError as exc:
        if provenance_mismatch(body):
            raise _http_error(
                400,
                "COMPANION_PROVENANCE_REQUIRED",
                "request provenance does not match kind",
                retryable=False,
            ) from exc
        raise _http_error(
            400,
            "COMPANION_REQUEST_INVALID",
            "invalid companion request",
            retryable=False,
        ) from exc
    except ValueError as exc:
        raise _http_error(400, "COMPANION_REQUEST_INVALID", "invalid companion request", retryable=False) from exc

    try:
        result = await handle_event(parsed, caller_label=auth.label)
    except CompanionServiceError as exc:
        raise _http_error(exc.status_code, exc.code, exc.message, retryable=exc.retryable) from exc
    return result


@router.get(
    "/observability/companion-events",
    summary="Read redacted external companion runtime observability",
)
async def companion_events(_auth=Depends(require_scopes("state.read"))):
    return observability()
