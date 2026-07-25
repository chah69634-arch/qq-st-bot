from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
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


@router.get(
    "/observability/character-permissions",
    summary="角色权限：桌面+手机工具类目暴露面、危险模式闸门、身份固化管线状态（2026-07-25）",
)
async def character_permissions(
    char_id: str,
    uid: str = "",
    _auth=Depends(require_scopes("state.read")),
):
    from core.character_permissions import get_tool_category_status, get_identity_consolidation_status
    result = get_tool_category_status(char_id)
    if uid:
        result["identity_consolidation"] = get_identity_consolidation_status(uid, char_id)
    return result


class _PermissionTestRequest(BaseModel):
    link: str
    char_id: str
    uid: str


@router.post(
    "/observability/character-permissions/test",
    summary="测试一条角色权限链路是否真的通（2026-07-25，见 core/character_permissions.py 关于哪些链路真实执行）",
)
async def character_permissions_test(
    body: _PermissionTestRequest,
    _auth=Depends(require_scopes("state.read")),
):
    from core.character_permissions import run_permission_test
    return await run_permission_test(body.link, uid=body.uid, char_id=body.char_id)
