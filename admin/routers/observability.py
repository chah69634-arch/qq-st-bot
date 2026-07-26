from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from admin.auth import require_scopes

router = APIRouter()


@router.get("/observability/api-calls", summary="读取外部 API 调用总账")
async def api_calls(caller: str = "", provider: str = "", limit: int = Query(100, ge=1, le=500), _auth=Depends(require_scopes("state.read"))):
    from core.api_call_log import query
    entries, grouped = query(caller=caller, provider=provider, limit=limit)
    return {"entries": entries, "count": len(entries), "by_provider": grouped}


@router.get(
    "/observability/tool-traces",
    summary="列出有工具执行痕迹的 uid（只读）",
)
async def tool_trace_uids(
    char_id: str = "",
    _auth=Depends(require_scopes("memory.read")),
):
    from admin.routers.provenance import _resolve_char_id
    from core.memory import action_trace

    resolved_char_id = _resolve_char_id(char_id)
    return {"char_id": resolved_char_id, "uids": action_trace.list_uids(resolved_char_id)}


@router.get(
    "/observability/tool-traces/{uid}",
    summary="读取统一工具执行痕迹（只读）",
    description=(
        "按工具 category 读取 action_trace 的安全摘要；包含探针、意图解析和 Tool Loop "
        "三条执行路径，永不返回工具原始结果或未白名单参数。"
    ),
)
async def tool_traces(
    uid: str,
    category: str = "",
    limit: int = Query(30, ge=1, le=30),
    char_id: str = "",
    _auth=Depends(require_scopes("memory.read")),
):
    from admin.routers.provenance import _resolve_char_id
    from core.memory import action_trace

    resolved_char_id = _resolve_char_id(char_id)
    entries = action_trace.query(uid, resolved_char_id, category=category, limit=limit)
    all_entries = action_trace.query(uid, resolved_char_id, limit=30)
    categories: dict[str, int] = {}
    for entry in all_entries:
        name = str(entry.get("category") or "unknown")
        categories[name] = categories.get(name, 0) + 1
    return {
        "uid": uid,
        "char_id": resolved_char_id,
        "category": category or None,
        "entries": entries,
        "count": len(entries),
        "categories": categories,
    }


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
