"""Allowlisted runtime feature flags for the admin panel.

Only boolean switches with an implemented config consumer are exposed. Secrets and
deployment paths deliberately stay out of this generic endpoint.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin.auth import require_scopes
from admin.config_control import read_config_file, write_config_file
from core.config_loader import get_config

router = APIRouter()
CONFIG_FILE = Path("config.yaml")

FLAGS = {
    "qq":   ("qq",   "enabled", "QQ 通道"),
    "mail": ("mail", "enabled", "邮件通道"),
    "visual_perception": ("visual_perception", "enabled", "视觉感知"),
    "spend": ("spend", "enabled", "支出意向"),
    "practice": ("practice", "enabled", "自主练习"),
    "action_trace": ("action_trace", "enabled", "行为痕迹"),
    "self_management": ("self_management", "enabled", "Self Capability"),
    "mcp_servers": ("mcp_servers", "enabled", "MCP 外部工具"),
    "fs_access": ("fs_access", "enabled", "文件只读访问"),
    "anti_collapse": ("anti_collapse", "enabled", "输出防坍缩"),
    "coplay": ("coplay", "enabled", "陪玩部署"),
    "toy_autogrow": ("toy_autogrow", "enabled", "玩具自主生长"),
    "web_autosearch": ("web_autosearch", "enabled", "自主联网搜索"),
    "performance_mapping": ("performance_mapping", "enabled", "表演标注映射"),
    "private_exchange": ("private_exchange", "enabled", "角色私下往来"),
    "event_edge_proposer": ("event_edge_proposer", "enabled", "Memory Event 候选关联边"),
}
RESTART_REQUIRED_FLAGS = frozenset({"qq"})
_DEFAULT_ENABLED_FLAGS = frozenset({"self_management"})


class FeatureFlagsUpdate(BaseModel):
    flags: dict[str, bool]


@router.get("/settings/feature-flags", summary="读取功能开关白名单")
async def get_feature_flags(auth=Depends(require_scopes("admin"))):
    cfg = get_config()
    return {"flags": {
        name: {
            "enabled": bool(cfg.get(section, {}).get(key, name in _DEFAULT_ENABLED_FLAGS)),
            "label": label,
            "apply_mode": "restart_required" if name in RESTART_REQUIRED_FLAGS else "hot_reload",
            "restart_required": name in RESTART_REQUIRED_FLAGS,
        }
        for name, (section, key, label) in FLAGS.items()
    }}


@router.put("/settings/feature-flags", summary="批量更新功能开关并返回实际生效方式")
async def update_feature_flags(body: FeatureFlagsUpdate, auth=Depends(require_scopes("admin"))):
    unknown = sorted(set(body.flags) - set(FLAGS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知功能开关: {unknown}")
    full_cfg = read_config_file(CONFIG_FILE)
    changed = set()
    for name, enabled in body.flags.items():
        section, key, _ = FLAGS[name]
        if bool(full_cfg.get(section, {}).get(key, name in _DEFAULT_ENABLED_FLAGS)) != enabled:
            changed.add(name)
        full_cfg.setdefault(section, {})[key] = enabled
    write_config_file(CONFIG_FILE, full_cfg)
    from core import config_loader
    config_loader.reload_config()
    if "mcp_servers" in body.flags:
        from core import mcp_client
        await mcp_client.sync_mcp_servers()
    result = await get_feature_flags(auth)
    restart_required = sorted(changed & RESTART_REQUIRED_FLAGS)
    result.update({
        "reload_status": "restart_required" if restart_required else "reloaded",
        "restart_required": restart_required,
        "message": (
            "设置已保存；QQ 通道需要重启后端后生效"
            if restart_required
            else "设置已保存并热生效"
        ),
    })
    return result
