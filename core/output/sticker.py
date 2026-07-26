"""
表情包发送模块
LLM判断情绪类别，随机抽取对应文件夹的图片发送
概率极低，角色偶尔才会发
"""

import logging
import random
from base64 import b64encode
from pathlib import Path

from core.error_handler import log_error
from core.config_loader import get_config

logger = logging.getLogger(__name__)

_EMOTION_LABELS = ["无奈", "心疼", "开心", "委屈", "害羞", "沉默"]

# 默认触发概率，角色不常发表情包。配置缺失时保持旧行为。
_TRIGGER_PROB = 0.06


_STICKER_EXTS = (".jpg", ".jpeg", ".png", ".gif")


def _char_sticker_pack_name(char_id: str) -> str | None:
    """角色卡 presence_ext.sticker_pack（角色资产路由：与 presence_ext.model_routing /
    tts_preset 同构）。fail-soft：加载失败/字段缺失 → None（只用通用表情包池）。
    """
    try:
        from core import character_loader
        char = character_loader.load(char_id)
        return (getattr(char, "presence_ext", None) or {}).get("sticker_pack") or None
    except Exception:
        return None


def _list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return [f for f in folder.iterdir() if f.suffix.lower() in _STICKER_EXTS]


def _pick_sticker(emotion: str, char_id: str | None = None) -> str | None:
    """从对应情绪文件夹随机抽一张图片，返回绝对路径。

    char_id 给定且该角色声明了 presence_ext.sticker_pack 时，优先从该角色专属表情包池
    （sticker_pack_dir()/<emotion>/）抽取；专属包没有这个情绪的图片（目录不存在或为空，
    不要求专属包覆盖全部情绪）时回落读通用池 stickers_dir()/<emotion>/，与角色未配置
    专属包时行为一致。
    """
    from core.sandbox import get_paths

    if char_id:
        pack_name = _char_sticker_pack_name(char_id)
        if pack_name:
            pack_folder = get_paths().sticker_pack_dir(pack_name) / emotion
            pack_files = _list_images(pack_folder)
            if pack_files:
                return str(random.choice(pack_files).resolve())
            logger.debug(
                "[sticker] 专属表情包池 %r 情绪 %r 无图片，回落通用池", pack_name, emotion,
            )

    folder = get_paths().stickers_dir() / emotion
    files = _list_images(folder)
    if not files:
        return None
    return str(random.choice(files).resolve())


def _build_sticker_payload(path: str, emotion: str) -> dict | None:
    """构造可跨通道转发的贴纸 payload，不向客户端暴露本机文件路径。"""
    suffix = Path(path).suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
    }.get(suffix)
    if media_type is None:
        return None
    try:
        encoded = b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return None
    return {
        "kind": "sticker",
        "emotion": emotion,
        "data_url": f"data:{media_type};base64,{encoded}",
    }


async def maybe_send_sticker(
    reply: str,
    target_id: str | None = None,
    is_group: bool = False,
    emotion: str = "",
    char_id: str | None = None,
    *,
    recipient_id: str | None = None,
):
    """
    根据情绪小概率发一张表情包。
    在post_process里调用，失败静默。

    ``target_id`` is a QQ destination when present; it is deliberately
    optional because desktop/mobile replies have no QQ address.  Cross-channel
    sticker delivery uses ``recipient_id`` instead and must not be gated by QQ.

    char_id：给定时优先用该角色专属表情包池，缺图回落通用池（角色资产路由，
    见 _pick_sticker()）；省略时只用通用池（现状行为不变）。
    """
    try:
        sticker_cfg = get_config().get("sticker", {})
        if not sticker_cfg.get("enabled", True):
            return
        trigger_prob = sticker_cfg.get("trigger_prob", _TRIGGER_PROB)

        # neutral或无情绪直接跳过
        if not emotion or emotion == "neutral":
            return
        if random.random() >= trigger_prob:
            return
        # 把detect_emotion的标签映射到表情包文件夹
        _EMOTION_MAP = {
            "happy": "开心",
            "sad": "委屈",
            "gentle": "心疼",
            "surprised": "害羞",
            "angry": "无奈",
        }
        folder_emotion = _EMOTION_MAP.get(emotion, "沉默")

        path = _pick_sticker(folder_emotion, char_id=char_id)
        if not path:
            from core.sandbox import get_paths
            folder = get_paths().stickers_dir() / folder_emotion
            # 曾经是 INFO（日常日志噪音里几乎看不见）。这是"表情包为什么从不触发"
            # 最常见的静默失败点（目录解析错/迁移中路径不一致/图片未放对文件夹），
            # 升到 WARNING 便于直接从日志定位，不用每次专门起一轮排查。
            logger.warning(
                "[sticker] 目录无可用图片，表情包本轮未发送: %s（resolved via get_paths().stickers_dir()）",
                folder,
            )
            return

        if target_id:
            try:
                from core.qq_adapter import send_image
                await send_image(target_id, path, is_group)
            except Exception as e:
                logger.warning("[sticker] QQ 侧发送失败（不影响其他通道广播）: %s", e)

        payload = _build_sticker_payload(path, folder_emotion)
        if payload is not None:
            # QQ 保持原有 OneBot 图片发送；桌宠和手机经既有通道注册表收到同一份
            # 自包含 payload，客户端按 sticker 字段渲染（渲染实现见各前端仓库）。
            from channels import registry
            failures = await registry.broadcast(
                "", recipient_id or target_id or "", sticker=payload, exclude_channels={"qq"},
            )
            logger.info(
                "[sticker] 已选中并尝试发送: %s，跨端广播失败通道=%s"
                "（收到广播≠客户端已渲染，前端是否显示取决于其 sticker 字段实现）",
                folder_emotion, failures or "无",
            )
        else:
            logger.warning("[sticker] payload 构建失败（图片格式或读取问题）: %s", path)

    except Exception as e:
        log_error("sticker.maybe_send_sticker", e)
