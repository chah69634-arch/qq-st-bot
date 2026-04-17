"""
语音输出适配器 — 对接 GPT-SoVITS v2 整合包

接口规格（GPT-SoVITS v2 推理 API）：
  POST http://127.0.0.1:9880/tts
  Content-Type: application/json
  Body:
    text            要合成的文字
    text_lang       文本语言，固定 "zh"
    ref_audio_path  参考音频本地路径（config.tts.ref_audio，必填）
    prompt_lang     参考音频语言，固定 "zh"
    prompt_text     参考音频对应文字（config.tts.prompt_text，可留空）
    top_k           5
    top_p           1.0
    temperature     1.0
    speed_factor    语速倍率（config.tts.speed，默认 1.0）
  返回：音频流（wav bytes），HTTP 200

启用条件：config.yaml  tts.enabled = true
"""

import asyncio
import base64
import logging

import aiohttp

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)


async def synthesize(text: str, emotion: str = "neutral") -> bytes | None:
    """
    将文本合成为语音，返回 wav 音频二进制数据。

    配置项（config.yaml tts 节）：
        api_url      — GPT-SoVITS API 地址，默认 http://127.0.0.1:9880
        ref_audio    — 参考音频本地路径（必填，留空时跳过合成）
        prompt_text  — 参考音频对应文字（可留空）
        speed        — 语速倍率，1.0 为正常

    成功返回 bytes，失败返回 None（已记录详细日志）。
    超时 15 秒。
    """
    cfg = get_config().get("tts", {})
    api_url = cfg.get("api_url", "http://127.0.0.1:9880").rstrip("/")

    # 情绪模式：从对应情绪配置读取音频参数
    if cfg.get("emotion_enabled", False):
        emotions = cfg.get("emotions", {})
        # 找不到指定情绪时回退到 neutral，再回退到顶层默认值
        ecfg = emotions.get(emotion) or emotions.get("neutral") or {}
        ref_audio  = ecfg.get("ref_audio",  "").strip() or cfg.get("ref_audio",  "").strip()
        prompt_txt = ecfg.get("prompt_text", "").strip() or cfg.get("prompt_text", "").strip()
        speed      = float(ecfg.get("speed") or cfg.get("speed", 1.0))
        logger.debug(f"[voice_adapter] 情绪模式 emotion={emotion} speed={speed}")
    else:
        ref_audio  = cfg.get("ref_audio",  "").strip()
        prompt_txt = cfg.get("prompt_text", "").strip()
        speed      = float(cfg.get("speed", 1.0))

    if not ref_audio:
        logger.warning("[voice_adapter] tts.ref_audio 未配置，跳过语音合成")
        return None

    payload = {
        "text":           text,
        "text_lang":      "zh",
        "ref_audio_path": ref_audio,
        "prompt_lang":    "zh",
        "prompt_text":    prompt_txt,
        "top_k":          5,
        "top_p":          1.0,
        "temperature":    1.0,
        "speed_factor":   speed,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{api_url}/tts",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    if not audio_bytes:
                        logger.warning("[voice_adapter] GPT-SoVITS 返回了空音频")
                        return None
                    logger.info(
                        f"[voice_adapter] 合成成功，{len(audio_bytes)} bytes，"
                        f"文本预览: {text[:30]!r}"
                    )
                    return audio_bytes
                else:
                    body = await resp.text()
                    logger.warning(
                        f"[voice_adapter] GPT-SoVITS 返回 HTTP {resp.status}: {body[:200]}"
                    )
                    return None

    except aiohttp.ClientConnectorError:
        logger.warning(
            f"[voice_adapter] 无法连接 GPT-SoVITS {api_url}，"
            "请确认整合包 API 服务已启动（一键启动 → API 服务）"
        )
        return None
    except asyncio.TimeoutError:
        logger.warning(f"[voice_adapter] GPT-SoVITS 合成超时（>15s），text={text[:30]!r}")
        return None
    except Exception as e:
        log_error("voice_adapter.synthesize", e)
        return None


async def send_voice(target_id: str, audio_bytes: bytes, is_group: bool = False):
    """
    将音频 bytes 通过 NapCat 以语音消息形式发送（OneBot 11 record 段）。

    参数：
        target_id   — 私聊时为 user_id，群聊时为 group_id
        audio_bytes — synthesize() 返回的 wav bytes
        is_group    — True=群聊，False=私聊
    """
    from core import qq_adapter

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    await qq_adapter.send_record(target_id, f"base64://{b64}", is_group)


# ── 类封装 ─────────────────────────────────────────────────────────────────────

class VoiceAdapter:
    """VoiceAdapter 类封装，代理到模块级函数"""

    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes | None:
        return await synthesize(text, emotion)

    async def send_voice(self, target_id: str, audio_bytes: bytes, is_group: bool = False):
        await send_voice(target_id, audio_bytes, is_group)
