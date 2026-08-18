from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from admin.auth import require_scopes

router = APIRouter()


@router.get(
    "/observability/owner-turns",
    summary="读取脱敏 Owner Turn receipt 观测",
    description=(
        "只返回 caller/client/canonical ID、状态、时间和固定错误码；不返回正文、"
        "request hash、Prompt、工具数据、token 或路径。"
    ),
)
async def owner_turn_receipts(
    status: str = "",
    caller: str = "",
    created_after: float | None = Query(None, ge=0),
    created_before: float | None = Query(None, ge=0),
    limit: int = Query(25, ge=1, le=100),
    cursor: str = Query("", max_length=512),
    _auth=Depends(require_scopes("state.read")),
):
    if created_after is not None and created_before is not None and created_after > created_before:
        raise HTTPException(status_code=422, detail="created_after must not exceed created_before")
    from core import owner_turn_receipts as receipt_store
    from core.owner_turn_service import is_currently_inflight

    try:
        result = receipt_store.list_receipts(
            status=status or None,
            caller=caller or None,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            cursor=cursor or None,
            is_inflight=is_currently_inflight,
        )
        result["status_counts"] = receipt_store.summary(is_inflight=is_currently_inflight)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    "/observability/memory-event-ledger",
    summary="读取 Memory Event 账本双写健康度",
)
async def memory_event_ledger(_auth=Depends(require_scopes("state.read"))):
    from core.memory.event_store import observability_snapshot

    return observability_snapshot()


@router.get(
    "/observability/memory-event-migration",
    summary="读取 Memory Event 历史迁移进度（不返回正文或本地路径）",
)
async def memory_event_migration(
    uid: str,
    char_id: str,
    _auth=Depends(require_scopes("state.read")),
):
    from core.asset_registry import get_registry
    from core.memory.event_migration import migration_status
    from core.memory.scope import MemoryScope

    try:
        get_registry().resolve(char_id, "character")
        scope = MemoryScope.reality_scope(uid, char_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail={"code": "invalid_scope"}) from None
    return {"scope": {"uid": uid, "char_id": char_id, "realm": "reality"}, **migration_status(scope)}


@router.get(
    "/observability/memory-event-edges",
    summary="读取 Memory Event 确定性关联边统计",
)
async def memory_event_edges(
    uid: str,
    char_id: str,
    _auth=Depends(require_scopes("state.read")),
):
    from core.memory.event_store import edge_observability_snapshot
    from core.memory.scope import MemoryScope

    return edge_observability_snapshot(MemoryScope.reality_scope(uid, char_id))


@router.get(
    "/observability/memory-event-edge-proposals",
    summary="读取 Memory Event 模型候选关联边统计",
)
async def memory_event_edge_proposals(
    uid: str,
    char_id: str,
    _auth=Depends(require_scopes("state.read")),
):
    from core.memory.event_store import edge_proposal_observability_snapshot
    from core.memory.scope import MemoryScope
    from core.scheduler.triggers.event_edge_proposer import _config, _day_key, discovery_observability_snapshot

    cfg = _config()
    result = edge_proposal_observability_snapshot(
        MemoryScope.reality_scope(uid, char_id), day_key=_day_key(),
        daily_call_limit=int(cfg["max_daily_calls"]),
        daily_token_limit=int(cfg["max_daily_tokens"]),
    )
    result["discovery"] = discovery_observability_snapshot()
    return result


@router.get(
    "/observability/memory-event-shadow-recall",
    summary="读取 Memory Event shadow recall 灰度指标",
    description=(
        "只返回 shadow recall 的状态、计数、字符/token 预算、重叠率、"
        "scope 拒绝、截断和超时原因；不会返回查询正文或事件证据。"
    ),
)
async def memory_event_shadow_recall(
    uid: str,
    char_id: str,
    date: str = "",
    limit: int = Query(20, ge=1, le=100),
    _auth=Depends(require_scopes("state.read")),
):
    import json
    from datetime import datetime
    from core.memory.path_resolver import resolve_path
    from core.memory.scope import MemoryScope

    date_str = date or datetime.now().strftime("%Y-%m-%d")
    scope = MemoryScope.reality_scope(uid, char_id)
    trace_file = resolve_path(scope, "recall_trace") / f"{date_str}.jsonl"
    try:
        read_limit = min(100, max(1, int(limit)))
    except (TypeError, ValueError):
        read_limit = 20
    records: list[dict] = []
    if trace_file.exists():
        try:
            for line in trace_file.read_text(encoding="utf-8").splitlines()[-read_limit:]:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                shadow = item.get("event_shadow_recall")
                if isinstance(shadow, dict):
                    records.append({
                        key: shadow.get(key)
                        for key in (
                            "status", "enabled", "seed_event_ids", "new_event_ids",
                            "new_turn_ids", "seed_order", "comparison_mode",
                            "expand_count", "related_count", "candidate_count", "chars",
                            "tokens", "old_chars", "old_tokens", "overlap_rate",
                            "event_overlap_rate", "turn_overlap_rate", "event_overlap_count",
                            "turn_overlap_count", "event_coverage", "old_result_count",
                            "old_mapped_count", "old_unmapped_count", "old_mapped_event_count",
                            "new_mapped_count", "new_unmapped_count", "new_event_count",
                            "new_turn_count", "extra_event_count", "omitted_event_count",
                            "comparison_scope_rejections",
                            "scope_rejections", "truncation_reason", "timeout_reason",
                            "elapsed_ms",
                        )
                    })
        except Exception:
            records = []
    status_counts: dict[str, int] = {}
    for item in records:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "uid": uid,
        "char_id": char_id,
        "date": date_str,
        "records": records,
        "count": len(records),
        "status_counts": status_counts,
    }


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
