"""
调度器管理路由
提供调度器状态查询、配置读写、手动触发等接口
"""

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import verify_token
from core.config_loader import get_config, reload_config

router = APIRouter()


def _sched_cfg() -> dict:
    return get_config().get("scheduler", {})


def _save_sched_cfg(new_sched: dict):
    """将修改后的 scheduler 节写回 config.yaml"""
    import yaml
    from pathlib import Path
    path = Path("config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        full = yaml.safe_load(f) or {}
    full["scheduler"] = new_sched
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(full, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    reload_config()


# ── 状态 ──────────────────────────────────────────────────────────────────────

@router.get("/scheduler/status", summary="获取调度器触发状态")
async def get_scheduler_status(auth=Depends(verify_token)):
    """返回各触发器的冷却状态和上次触发时间"""
    from core.scheduler import get_status
    return {
        "enabled": _sched_cfg().get("enabled", True),
        "triggers": get_status(),
    }


# ── 配置读写 ──────────────────────────────────────────────────────────────────

@router.get("/scheduler/config", summary="读取调度器配置")
async def get_sched_config(auth=Depends(verify_token)):
    return _sched_cfg()


@router.put("/scheduler/config", summary="更新调度器配置")
async def put_sched_config(body: dict, auth=Depends(verify_token)):
    """
    支持局部更新，只传需要改的字段。
    signatures 字段若传入则整体替换。
    """
    cfg = dict(_sched_cfg())

    bool_fields = [
        "enabled", "morning_greeting", "night_reminder", "random_message",
        "daily_journal", "period_reminder", "diary_reminder", "diary_inject",
    ]
    for f in bool_fields:
        if f in body:
            cfg[f] = bool(body[f])

    if "owner_id" in body:
        cfg["owner_id"] = str(body["owner_id"]).strip()

    if "signatures" in body:
        sigs = body["signatures"]
        if not isinstance(sigs, list):
            raise HTTPException(status_code=422, detail="signatures 必须为数组")
        cfg["signatures"] = [str(s).strip() for s in sigs if str(s).strip()]

    _save_sched_cfg(cfg)
    return {"message": "调度器配置已保存", "config": cfg}


# ── 签名增删 ─────────────────────────────────────────────────────────────────

@router.post("/scheduler/signatures", summary="添加一条签名")
async def add_signature(body: dict, auth=Depends(verify_token)):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=422, detail="text 不能为空")
    cfg = dict(_sched_cfg())
    sigs = list(cfg.get("signatures", []))
    if text in sigs:
        return {"message": "签名已存在", "signatures": sigs}
    sigs.append(text)
    cfg["signatures"] = sigs
    _save_sched_cfg(cfg)
    return {"message": "已添加", "signatures": sigs}


@router.delete("/scheduler/signatures", summary="删除一条签名")
async def delete_signature(body: dict, auth=Depends(verify_token)):
    text = str(body.get("text", "")).strip()
    cfg = dict(_sched_cfg())
    sigs = [s for s in cfg.get("signatures", []) if s != text]
    cfg["signatures"] = sigs
    _save_sched_cfg(cfg)
    return {"message": "已删除", "signatures": sigs}


# ── 手动触发 ─────────────────────────────────────────────────────────────────

@router.post("/scheduler/trigger/{name}", summary="手动触发指定动作")
async def manual_trigger(name: str, auth=Depends(verify_token)):
    """
    可触发的名称：
      morning_greeting / night_reminder / random_message
    """
    from core.scheduler import manual_trigger as _trigger
    result = await _trigger(name)
    return {"message": result}
