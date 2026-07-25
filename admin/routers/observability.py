from fastapi import APIRouter, Depends, Query
from admin.auth import require_scopes

router = APIRouter()


@router.get("/observability/api-calls", summary="读取外部 API 调用总账")
async def api_calls(caller: str = "", provider: str = "", limit: int = Query(100, ge=1, le=500), _auth=Depends(require_scopes("state.read"))):
    from core.api_call_log import query
    entries, grouped = query(caller=caller, provider=provider, limit=limit)
    return {"entries": entries, "count": len(entries), "by_provider": grouped}


@router.get("/observability/perceive-events", summary="读取 reality stimulus 审计记录")
async def perceive_events(
    source: str = "",
    gate_result: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _auth=Depends(require_scopes("state.read")),
):
    from core.perceive_event_audit import query

    entries, total = query(
        source=source,
        gate_result=gate_result,
        offset=offset,
        limit=limit,
    )
    return {
        "entries": entries,
        "count": len(entries),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get(
    "/observability/resource-completeness",
    summary="资源完整性/功能状态检查：哪个开关没开、哪个功能缺素材、哪个还没做（2026-07-25）",
)
async def resource_completeness(_auth=Depends(require_scopes("state.read"))):
    from core.resource_completeness import run_all_checks
    return run_all_checks()


@router.get(
    "/observability/api-contract-check",
    summary="后端↔前端 desktop action 契约检查：扫两边 type 字符串取差集（2026-07-25）",
)
async def api_contract_check(_auth=Depends(require_scopes("state.read"))):
    from core.api_contract_check import run_check
    return run_check()
