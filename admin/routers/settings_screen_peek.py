"""
屏幕内容查看配置接口
GET  /settings/screen-peek   — 读取当前 screen_peek 配置
POST /settings/screen-peek   — 更新 enabled / cooldown_minutes 并热重载
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin.auth import require_scopes
from admin.config_control import read_config_file, write_config_file
from core.config_loader import get_config

router = APIRouter()
CONFIG_FILE = Path("config.yaml")

_COOLDOWN_MIN = 5
_COOLDOWN_MAX = 240


class ScreenPeekUpdate(BaseModel):
    enabled: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(None, ge=_COOLDOWN_MIN, le=_COOLDOWN_MAX)


@router.get("/settings/screen-peek", summary="获取屏幕内容查看配置")
async def get_screen_peek(auth=Depends(require_scopes("admin"))):
    cfg = get_config().get("screen_peek", {})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "cooldown_minutes": int(cfg.get("cooldown_minutes", 30)),
    }


@router.post("/settings/screen-peek", summary="更新屏幕内容查看配置并热重载")
async def update_screen_peek(body: ScreenPeekUpdate, auth=Depends(require_scopes("admin"))):
    full_cfg = read_config_file(CONFIG_FILE)

    sp = full_cfg.setdefault("screen_peek", {})
    if body.enabled is not None:
        sp["enabled"] = body.enabled
    if body.cooldown_minutes is not None:
        sp["cooldown_minutes"] = body.cooldown_minutes

    write_config_file(CONFIG_FILE, full_cfg)

    from core import config_loader
    config_loader.reload_config()

    return {
        "message": "屏幕内容查看配置已更新",
        "screen_peek": full_cfg["screen_peek"],
    }
