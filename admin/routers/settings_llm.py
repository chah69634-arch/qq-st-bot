"""
LLM 生成参数配置接口
GET /llm-params  — 读取当前生成参数
PUT /llm-params  — 修改生成参数并热重载
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


class LlmParamsUpdate(BaseModel):
    temperature:       Optional[float] = None
    top_p:             Optional[float] = None
    max_tokens:        Optional[int]   = None
    frequency_penalty: Optional[float] = None


@router.get("/llm-params", summary="获取 LLM 生成参数")
async def get_llm_params(auth=Depends(verify_token)):
    """读取 config.yaml 中的 llm 生成参数"""
    cfg = get_config().get("llm", {})
    return {
        "temperature":       float(cfg.get("temperature",       0.7)),
        "top_p":             float(cfg.get("top_p",             0.9)),
        "max_tokens":        int(cfg.get("max_tokens",          1000)),
        "frequency_penalty": float(cfg.get("frequency_penalty", 0.0)),
    }


@router.put("/llm-params", summary="修改 LLM 生成参数并热重载")
async def update_llm_params(body: LlmParamsUpdate, auth=Depends(verify_token)):
    """修改 config.yaml 的 llm 生成参数字段并热重载"""
    if body.temperature is not None and not (0.0 <= body.temperature <= 2.0):
        raise HTTPException(status_code=422, detail="temperature 必须在 0.0~2.0 之间")
    if body.top_p is not None and not (0.0 <= body.top_p <= 1.0):
        raise HTTPException(status_code=422, detail="top_p 必须在 0.0~1.0 之间")
    if body.max_tokens is not None and not (100 <= body.max_tokens <= 4000):
        raise HTTPException(status_code=422, detail="max_tokens 必须在 100~4000 之间")
    if body.frequency_penalty is not None and not (0.0 <= body.frequency_penalty <= 2.0):
        raise HTTPException(status_code=422, detail="frequency_penalty 必须在 0.0~2.0 之间")

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    llm_cfg = full_cfg.setdefault("llm", {})
    if body.temperature is not None:
        llm_cfg["temperature"] = body.temperature
    if body.top_p is not None:
        llm_cfg["top_p"] = body.top_p
    if body.max_tokens is not None:
        llm_cfg["max_tokens"] = body.max_tokens
    if body.frequency_penalty is not None:
        llm_cfg["frequency_penalty"] = body.frequency_penalty

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader
    config_loader.reload_config()
    return {"message": "LLM 参数已更新", "llm": {k: llm_cfg[k] for k in ("temperature", "top_p", "max_tokens", "frequency_penalty") if k in llm_cfg}}


class VisionParamsUpdate(BaseModel):
    enabled:  Optional[bool]  = None
    provider: Optional[str]   = None
    api_key:  Optional[str]   = None
    model:    Optional[str]   = None
    base_url: Optional[str]   = None


@router.get("/vision-params", summary="获取 Vision 配置")
async def get_vision_params(auth=Depends(verify_token)):
    cfg = get_config().get("vision", {})
    return {
        "enabled":  cfg.get("enabled",  False),
        "provider": cfg.get("provider", ""),
        "api_key":  cfg.get("api_key",  ""),
        "model":    cfg.get("model",    ""),
        "base_url": cfg.get("base_url", ""),
    }


@router.put("/vision-params", summary="修改 Vision 配置并热重载")
async def update_vision_params(body: VisionParamsUpdate, auth=Depends(verify_token)):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {e}")

    vision_cfg = full_cfg.setdefault("vision", {})
    if body.enabled  is not None: vision_cfg["enabled"]  = body.enabled
    if body.provider is not None: vision_cfg["provider"] = body.provider
    if body.api_key  is not None: vision_cfg["api_key"]  = body.api_key
    if body.model    is not None: vision_cfg["model"]    = body.model
    if body.base_url is not None: vision_cfg["base_url"] = body.base_url

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    from core import config_loader, llm_client
    config_loader.reload_config()
    llm_client.reload_client()
    return {"message": "Vision 配置已更新", "vision": vision_cfg}
