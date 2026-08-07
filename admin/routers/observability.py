from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from admin.auth import require_scopes

router = APIRouter()


@router.get(
    "/observability/backup-service-state",
    summary="读取离线备份使用的服务状态判定（不暴露 PID 或路径）",
)
async def backup_service_state(_auth=Depends(require_scopes("state.read"))):
    from core.backup_state import service_state

    return {"service_state": service_state(Path.cwd()).value}


@router.get("/observability/api-calls", summary="读取外部 API 调用总账")
async def api_calls(caller: str = "", provider: str = "", limit: int = Query(100, ge=1, le=500), _auth=Depends(require_scopes("state.read"))):
    from core.api_call_log import query
    entries, grouped = query(caller=caller, provider=provider, limit=limit)
    return {"entries": entries, "count": len(entries), "by_provider": grouped}


@router.get("/observability/mail-executions", summary="读取脱敏邮件执行台账")
async def mail_executions(
    uid: str = "", char_id: str = "", execution_id: str = "",
    limit: int = Query(100, ge=1, le=500), _auth=Depends(require_scopes("state.read")),
):
    from core.mail.execution_ledger import query
    entries = query(uid=uid, char_id=char_id, execution_id=execution_id, limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.get(
    "/observability/runtime-signals",
    summary="读取进程内聚合运行信号（不含正文、prompt、密钥、路径或用户标识）",
)
async def runtime_signals(_auth=Depends(require_scopes("state.read"))):
    from core.runtime_signal_observability import snapshot

    return snapshot()


@router.get(
    "/observability/llm-debug-requests",
    summary="读取 LLM 请求调试快照（高敏感）",
    description="仅当 llm_debug_requests.enabled 为真时才会产生快照；内容含 prompt 与工具 schema。",
)
async def llm_debug_requests(
    purpose: str = "",
    limit: int = Query(20, ge=1, le=100),
    _auth=Depends(require_scopes("admin")),
):
    from core.llm_debug_requests import query

    entries = query(purpose=purpose, limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.delete(
    "/observability/llm-debug-requests",
    summary="清空 LLM 请求调试快照（高敏感）",
)
async def clear_llm_debug_requests(_auth=Depends(require_scopes("admin"))):
    from core.llm_debug_requests import clear

    return {"message": "LLM 请求调试快照已清空", "removed_files": clear()}


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
        "按工具 category 读取 action_trace 的安全摘要；每条含 execution_path（Path A/Path C/autonomy）"
        "与 provider（builtin/MCP），永不返回工具原始结果或未白名单参数。"
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
