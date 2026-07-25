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
import time
from pathlib import Path
from typing import Protocol

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent

_GSV_PROVIDER = "gsv"
_OPENAI_COMPAT_PROVIDER = "openai_compatible"
_PROVIDER_ALIASES = {"gpt_sovits": _GSV_PROVIDER, "gsv": _GSV_PROVIDER}


def _resolve_audio_path(path: str) -> str:
    """Resolve ref_audio path: anchor relative paths, then fall back to same-stem variants."""
    if not path:
        return path
    p = Path(path) if Path(path).is_absolute() else _PROJECT_ROOT / path
    if p.exists():
        return str(p)
    # Try alternate extensions in priority order
    for ext in (".wav", ".mp3", ".MP3", ".flac", ".ogg"):
        alt = p.with_suffix(ext)
        if alt.exists():
            logger.debug(f"[voice_adapter] ref_audio fallback {p.name} → {alt.name}")
            return str(alt)
    # Glob same-stem prefix (handles names like 生气.mp4_xxx.wav)
    matches = sorted(p.parent.glob(f"{p.stem}*.wav")) + sorted(p.parent.glob(f"{p.stem}*.mp3"))
    if matches:
        logger.debug(f"[voice_adapter] ref_audio glob fallback {p.name} → {matches[0].name}")
        return str(matches[0])
    return str(p)


def _active_provider_name(cfg: dict) -> str:
    requested = str(cfg.get("provider") or _GSV_PROVIDER).strip().lower()
    return _PROVIDER_ALIASES.get(requested, requested)


def _char_tts_preset_name(char_id: str) -> str | None:
    """角色卡 presence_ext.tts_preset（角色资产路由：与 presence_ext.model_routing 同构）。

    fail-soft：加载失败/字段缺失 → None（回落全局 tts 配置，与现有单角色部署零迁移）。
    """
    try:
        from core import character_loader
        char = character_loader.load(char_id)
        return (getattr(char, "presence_ext", None) or {}).get("tts_preset") or None
    except Exception:
        return None


def resolve_tts_config(char_id: str | None = None) -> dict:
    """把 ``tts.presets.<name>`` 命名预设叠加在全局 ``tts:`` 配置之上（角色资产路由）。

    解析顺序：
      1. char_id 为空 → 直接返回全局 tts 配置（未接线的旧调用点行为不变）。
      2. 角色卡未声明 presence_ext.tts_preset → 回落全局配置。
      3. 声明了但 tts.presets 里找不到同名预设 → 记 warning，回落全局配置（fail-soft，
         不能因为一张卡填错预设名就让语音整体哑掉）。
      4. 找到 → 预设字段覆盖全局同名字段（浅合并，预设可以只覆盖部分字段，如只换
         provider/emotions，其余沿用全局默认）。

    只做配置层合并，不改 get_provider_config() / synthesize() 已有的 provider 解析逻辑——
    合并结果原样喂给它们，兼容 legacy 顶层 GSV 字段与 providers 块两种写法。
    """
    base = dict(get_config().get("tts", {}))
    if not char_id:
        return base
    preset_name = _char_tts_preset_name(char_id)
    if not preset_name:
        return base
    presets = base.get("presets") if isinstance(base.get("presets"), dict) else {}
    preset = presets.get(preset_name)
    if not isinstance(preset, dict):
        logger.warning(
            "[voice_adapter] char_id=%r 声明的 tts_preset=%r 未在 tts.presets 中找到，回落全局 tts 配置",
            char_id, preset_name,
        )
        return base
    merged = dict(base)
    merged.update(preset)
    return merged


def get_provider_config(cfg: dict | None = None) -> tuple[str, dict]:
    """Return active provider settings with legacy top-level GSV fields mapped in.

    Existing ``tts.api_url`` / ``ref_audio`` configurations remain authoritative
    whenever the new ``tts.providers.gsv`` block has not overridden a field.
    """
    cfg = dict(cfg or get_config().get("tts", {}))
    provider = _active_provider_name(cfg)
    provider_blocks = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    legacy_gsv = {
        key: cfg[key]
        for key in (
            "api_url", "ref_audio", "prompt_text", "speed", "emotion_enabled",
            "emotions", "how_to_cut", "top_k", "top_p", "temperature",
            "ref_free", "if_freeze", "sample_steps", "if_sr", "pause_second",
        )
        if key in cfg
    }
    selected = dict(legacy_gsv if provider == _GSV_PROVIDER else {})
    selected.update(provider_blocks.get(provider) or {})
    return provider, selected


def get_provider_status(cfg: dict | None = None) -> dict:
    """Safe provider state for the admin panel; never includes credentials."""
    provider, selected = get_provider_config(cfg)
    supported = provider in {_GSV_PROVIDER, _OPENAI_COMPAT_PROVIDER}
    if provider == _GSV_PROVIDER:
        ready = bool(selected.get("api_url") and selected.get("ref_audio"))
        reason = "" if ready else "GSV requires api_url and ref_audio"
    elif provider == _OPENAI_COMPAT_PROVIDER:
        ready = bool(selected.get("base_url"))
        reason = "" if ready else "openai_compatible requires base_url (api_key optional for unauthenticated local deployments)"
    else:
        ready = False
        reason = f"Unknown TTS provider: {provider}"
    return {
        "provider": provider,
        "supported": supported,
        "ready": ready,
        "reason": reason,
        "api_key_configured": bool(selected.get("api_key")),
    }


def get_safe_provider_params(cfg: dict | None = None) -> dict:
    """Return editable active-provider settings without ever returning api_key."""
    _provider, selected = get_provider_config(cfg)
    return {key: value for key, value in selected.items() if key != "api_key"}


class TtsProvider(Protocol):
    async def synthesize(self, text: str, emotion: str, cfg: dict) -> bytes | None:
        """Synthesize an audio payload, returning None when the provider fails."""


class GsvProvider:
    async def synthesize(self, text: str, emotion: str, cfg: dict) -> bytes | None:
        api_url = str(cfg.get("api_url") or "http://127.0.0.1:9880").rstrip("/")
        if cfg.get("emotion_enabled", False):
            emotions = cfg.get("emotions", {})
            ecfg = emotions.get(emotion) or emotions.get("neutral") or {}
            ref_audio = str(ecfg.get("ref_audio", "")).strip() or str(cfg.get("ref_audio", "")).strip()
            prompt_txt = str(ecfg.get("prompt_text", "")).strip() or str(cfg.get("prompt_text", "")).strip()
            speed = float(ecfg.get("speed") or cfg.get("speed", 1.0))
        else:
            ref_audio = str(cfg.get("ref_audio", "")).strip()
            prompt_txt = str(cfg.get("prompt_text", "")).strip()
            speed = float(cfg.get("speed", 1.0))
        ref_audio = _resolve_audio_path(ref_audio)
        if not ref_audio:
            logger.warning("[voice_adapter] GSV ref_audio is not configured")
            return None

        def _sync_call():
            import os
            from gradio_client import Client, handle_file

            os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
            client = Client(api_url)
            result = client.predict(
                ref_wav_path=handle_file(ref_audio),
                prompt_text=prompt_txt,
                prompt_language="中文",
                text=text,
                text_language="中文",
                how_to_cut=cfg.get("how_to_cut", "凑四句一切"),
                top_k=int(cfg.get("top_k", 15)),
                top_p=float(cfg.get("top_p", 1.0)),
                temperature=float(cfg.get("temperature", 1.0)),
                ref_free=bool(cfg.get("ref_free", False)),
                speed=speed,
                if_freeze=bool(cfg.get("if_freeze", False)),
                inp_refs=None,
                sample_steps=int(cfg.get("sample_steps", 8)),
                if_sr=bool(cfg.get("if_sr", False)),
                pause_second=float(cfg.get("pause_second", 0.3)),
                api_name="/get_tts_wav",
            )
            with open(result, "rb") as f:
                return f.read()

        return await asyncio.get_event_loop().run_in_executor(None, _sync_call)


class OpenAICompatibleProvider:
    """OpenAI ``POST {base_url}/audio/speech`` 协议的通用 provider（Brief 107·B2）。

    覆盖两类真实场景：真·OpenAI/走同协议的云服务；以及自建开源 TTS 套了一层
    OpenAI 兼容外壳的部署（如 openai-edge-tts 之类的反代/网关，或引擎自带的
    openai-compat 模式）。不绑定具体厂商，所有字段都从
    ``tts.providers.openai_compatible`` 读，缺 base_url 直接判不可用（不去猜协议）。

    per-emotion 音色切换与 GSV 的 ``emotions`` 块同构，但 GSV 换的是参考音频文件，
    这里换的是 ``voice`` 预置音色名（云端/远程引擎通常不支持上传参考音频）：
        emotions:
          happy: {voice: "shimmer", speed: 1.1}
          sad:   {voice: "onyx", speed: 0.9}
    也接受纯字符串简写 ``happy: "shimmer"``（等价于只覆盖 voice，speed 用顶层默认）。
    """

    async def synthesize(self, text: str, emotion: str, cfg: dict) -> bytes | None:
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        if not base_url:
            logger.warning("[voice_adapter] openai_compatible TTS 缺少 base_url，跳过")
            return None
        model = str(cfg.get("model") or "tts-1")
        voice = str(cfg.get("voice") or "alloy")
        response_format = str(cfg.get("response_format") or "wav")
        api_key = str(cfg.get("api_key") or "")
        speed = float(cfg.get("speed", 1.0))

        if cfg.get("emotion_enabled", False):
            voice_map = cfg.get("emotions", {}) or {}
            evoice = voice_map.get(emotion) or voice_map.get("neutral")
            if isinstance(evoice, dict):
                voice = str(evoice.get("voice") or voice)
                speed = float(evoice.get("speed") or speed)
            elif isinstance(evoice, str) and evoice:
                voice = evoice

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
            "speed": speed,
        }

        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=float(cfg.get("timeout", 20.0)))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{base_url}/audio/speech", json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        body = (await resp.text())[:300]
                        logger.warning(
                            "[voice_adapter] openai_compatible TTS 返回非 200: "
                            "status=%s body=%s", resp.status, body,
                        )
                        return None
                    return await resp.read()
        except Exception as e:
            log_error("voice_adapter.openai_compatible.synthesize", e)
            return None


_PROVIDERS: dict[str, TtsProvider] = {
    _GSV_PROVIDER: GsvProvider(),
    _OPENAI_COMPAT_PROVIDER: OpenAICompatibleProvider(),
}


async def synthesize(text: str, emotion: str = "neutral", *, char_id: str | None = None) -> bytes | None:
    """
    将文本合成为语音，返回 wav 音频二进制数据。

    配置项（config.yaml tts 节）：
        api_url      — GPT-SoVITS API 地址，默认 http://127.0.0.1:9880
        ref_audio    — 参考音频本地路径（必填，留空时跳过合成）
        prompt_text  — 参考音频对应文字（可留空）
        speed        — 语速倍率，1.0 为正常

    char_id：给定时按该角色卡 presence_ext.tts_preset 解析命名预设（角色资产路由，
    见 resolve_tts_config()）；省略时用全局 tts 配置（未接线调用点的现状行为）。

    成功返回 bytes，失败返回 None（已记录详细日志）。
    超时 15 秒。
    """
    provider, provider_cfg = get_provider_config(resolve_tts_config(char_id))
    started_at = time.perf_counter()
    adapter = _PROVIDERS.get(provider)
    if adapter is None:
        from core.api_call_log import append
        append(caller="tts", purpose="synthesize", provider=provider, model="", duration_ms=int((time.perf_counter() - started_at) * 1000), ok=False, output_hint="unsupported_provider")
        logger.warning("[voice_adapter] unsupported provider=%s", provider)
        return None
    try:
        audio_bytes = await adapter.synthesize(text, emotion, provider_cfg)
        from core.api_call_log import append
        append(caller="tts", purpose="synthesize", provider=provider, model="", duration_ms=int((time.perf_counter() - started_at) * 1000), ok=bool(audio_bytes), output_hint=f"{len(audio_bytes)}_bytes" if audio_bytes else "empty_audio")
        if audio_bytes:
            logger.info("[voice_adapter] provider=%s synthesized %d bytes", provider, len(audio_bytes))
            return audio_bytes
        return None
    except Exception as e:
        from core.api_call_log import append
        append(caller="tts", purpose="synthesize", provider=provider, model="", duration_ms=int((time.perf_counter() - started_at) * 1000), ok=False, output_hint=type(e).__name__)
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
    import subprocess, tempfile, os
    wav_path = amr_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            wav_path = f.name
        amr_path = wav_path.replace(".wav", ".amr")
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-ar", "8000", "-ab", "12.2k", "-ac", "1", amr_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        await qq_adapter.send_record(target_id, f"file:///{amr_path}", is_group)
    except Exception:
        b64 = base64.b64encode(audio_bytes).decode("ascii")
        await qq_adapter.send_record(target_id, f"base64://{b64}", is_group)
    finally:
        if wav_path:
            try: os.unlink(wav_path)
            except: pass
        if amr_path:
            try: os.unlink(amr_path)
            except: pass


# ── 类封装 ─────────────────────────────────────────────────────────────────────

class VoiceAdapter:
    """VoiceAdapter 类封装，代理到模块级函数"""

    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes | None:
        return await synthesize(text, emotion)

    async def send_voice(self, target_id: str, audio_bytes: bytes, is_group: bool = False):
        await send_voice(target_id, audio_bytes, is_group)
