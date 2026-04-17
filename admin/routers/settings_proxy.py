"""
代理配置接口
GET /proxy  — 读取当前代理配置
PUT /proxy  — 修改代理配置并热重载
"""

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin.auth import verify_token
from core.config_loader import get_config

router = APIRouter()
CONFIG_FILE = Path("config.yaml")


class ProxyUpdate(BaseModel):
    enabled: Optional[bool] = None
    http: Optional[str] = None
    https: Optional[str] = None


@router.get("/proxy", summary="获取当前代理配置")
async def get_proxy(auth=Depends(verify_token)):
    proxy_cfg = get_config().get("proxy", {})
    return {
        "enabled": proxy_cfg.get("enabled", False),
        "http":    proxy_cfg.get("http",    ""),
        "https":   proxy_cfg.get("https",   ""),
    }


@router.put("/proxy", summary="修改代理配置并热重载")
async def update_proxy(body: ProxyUpdate, auth=Depends(verify_token)):
    """修改 proxy 字段，热重载 config + 重置 LLM 客户端"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    proxy_cfg = full_cfg.setdefault("proxy", {})
    if body.enabled is not None:
        proxy_cfg["enabled"] = body.enabled
    if body.http is not None:
        proxy_cfg["http"] = body.http
    if body.https is not None:
        proxy_cfg["https"] = body.https

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader, llm_client
    config_loader.reload_config()
    llm_client.reload_client()

    return {"message": "代理配置已更新并热重载", "proxy": proxy_cfg}
