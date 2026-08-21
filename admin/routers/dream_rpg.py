"""Read-only contracts for the backend-only RPG Dream foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from admin.auth import require_scopes
from core.config_loader import get_config
from core.data_paths import DEFAULT_CHAR_ID

router = APIRouter()


class RpgCapability(BaseModel):
    available: bool = True
    contract_version: str = "rpg/v1"
    max_primary_characters: int = 1


class DreamCapabilitiesResponse(BaseModel):
    supported_modes: list[str]
    rpg: RpgCapability


class RpgSessionProjection(BaseModel):
    dream_id: str
    char_id: str
    script_id: str | None
    status: str
    round_status: str
    active_round_id: str | None
    active_branch_id: str | None
    scene_revision: int
    since: float | None
    last_error_code: str | None
    session_health: str


class RpgStateResponse(BaseModel):
    session: RpgSessionProjection | None


class RpgObservabilityResponse(BaseModel):
    session_count: int
    active_session_count: int
    round_count: int
    status: str
    round_status: str
    last_error_code: str | None
    recovery_source: str
    last_updated_at: float | None
    path_health: str
    dream_id_hash: str | None
    char_id_hash: str | None
    event_count: int
    dice_count: int
    branch_count: int
    pending_receipt_count: int
    recovery_conflict_count: int
    invalid_proposal_count: int
    latency_bucket: str


def _uid() -> str:
    return str(get_config().get("scheduler", {}).get("owner_id", "owner"))


def _char_id() -> str:
    from core.pipeline_registry import get as get_pipeline
    pipeline = get_pipeline()
    return str((getattr(pipeline, "_active_character_id", None) if pipeline else None) or DEFAULT_CHAR_ID)


def _current():
    from core.dream.dream_state import read_state
    from core.dream.rpg_store import load, projection
    state = read_state(_uid())
    dream_id = str(state.get("dream_id") or "")
    if state.get("dream_mode") != "rpg" or not dream_id:
        return None
    core, health = load(_uid(), dream_id, char_id=str(state.get("char_id") or _char_id()))
    if core is None:
        # Do not manufacture a resumable core from a partial write. This is a
        # content-free error projection only; normal Dream Guard remains closed.
        return {
            "dream_id": dream_id,
            "char_id": str(state.get("char_id") or _char_id()),
            "script_id": (state.get("rpg_session") or {}).get("script_id"),
            "status": "uncertain",
            "round_status": "unknown",
            "active_round_id": None,
            "active_branch_id": None,
            "scene_revision": 0,
            "since": state.get("dream_started_at"),
            "last_error_code": "RPG_SESSION_" + health.upper(),
            "session_health": health,
        }
    return projection(core, health=health, since=state.get("dream_started_at"))


@router.get("/dream/capabilities", response_model=DreamCapabilitiesResponse, summary="Dream mode capabilities")
async def dream_capabilities(_auth=Depends(require_scopes("activity"))):
    from core.dream.dream_state import DreamMode
    return DreamCapabilitiesResponse(supported_modes=[item.value for item in DreamMode], rpg=RpgCapability())


@router.get("/dream/rpg/state", response_model=RpgStateResponse, summary="RPG Dream safe session state")
async def rpg_state(_auth=Depends(require_scopes("activity"))):
    return RpgStateResponse(session=_current())


@router.get(
    "/observability/dream-rpg",
    response_model=RpgObservabilityResponse,
    summary="RPG Dream content-free observability",
)
async def rpg_observability(_auth=Depends(require_scopes("state.read"))):
    from core.dream.dream_state import read_state
    from core.dream.rpg_store import load, observability
    state = read_state(_uid())
    dream_id = str(state.get("dream_id") or "")
    if state.get("dream_mode") != "rpg" or not dream_id:
        return RpgObservabilityResponse(**observability(None, health="missing", recovery_source="no_active_rpg_state"))
    core, health = load(_uid(), dream_id, char_id=str(state.get("char_id") or _char_id()))
    return RpgObservabilityResponse(**observability(core, health=health, recovery_source="disk"))
