"""
媒体内容处理模块
下载并处理图片和文件，转换为LLM可读的内容
"""

import base64
import logging
from pathlib import Path

import aiohttp

from core.error_handler import log_error
from core.proxy_config import get_aiohttp_proxy

logger = logging.getLogger(__name__)


async def download_bytes(url: str) -> bytes | None:
    """下载URL内容，返回bytes"""
    proxy = get_aiohttp_proxy()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15),
                proxy=proxy,
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        log_error("media_processor.download_bytes", e)
    return None


async def process_image(url: str, user_text: str = "") -> str | None:
    """
    下载图片并用vision模型识别，返回描述文字
    """
    try:
        data = await download_bytes(url)
        if not data:
            return None

        if data[:4] == b'\x89PNG':
            media_type = "image/png"
        elif data[:2] == b'\xff\xd8':
            media_type = "image/jpeg"
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            media_type = "image/gif"
        else:
            media_type = "image/jpeg"

        b64 = base64.b64encode(data).decode()

        from core import llm_client
        vision_messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"}
                    },
                    {
                        "type": "text",
                        "text": user_text if user_text else "用中文简洁描述这张图片的内容"
                    }
                ]
            }
        ]
        result = await llm_client.chat(vision_messages, use_vision=True)
        return result if result else None

    except Exception as e:
        log_error("media_processor.process_image", e)
    return None


async def process_file(file_info: dict) -> str | None:
    """
    下载并读取文件内容
    支持txt和docx，返回文本内容
    """
    try:
        name = file_info.get("name", "")
        url = file_info.get("url", "")
        file_id = file_info.get("file_id", "")
        data = None

        # 没有url时用file_id换取
        if not url and file_id:
            from core.qq_adapter import ws_call
            resp = await ws_call("get_file", {"file_id": file_id})
            if resp and resp.get("status") == "ok":
                resp_data = resp.get("data", {})
                raw_url = resp_data.get("url", "")
                if raw_url and raw_url.startswith("http"):
                    url = raw_url
                else:
                    local_path = raw_url or resp_data.get("file", "")
                    if local_path:
                        from urllib.parse import unquote
                        local_path = unquote(local_path).replace("file:///", "")
                        if local_path.startswith("c:") or local_path.startswith("C:"):
                            local_path = local_path.replace("/", "\\")
                        p = Path(local_path)
                        if p.exists():
                            data = p.read_bytes()
                            logger.info(f"[media_processor] 文件从本地路径读取: {local_path}")

        if not data and url:
            data = await download_bytes(url)

        if not data:
            logger.warning(f"[media_processor] 文件内容获取失败: {name}")
            return None

        suffix = Path(name).suffix.lower()

        if suffix == ".txt":
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode("gbk", errors="ignore")

        elif suffix in (".docx", ".doc"):
            import io
            from docx import Document
            doc = Document(io.BytesIO(data))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)

        else:
            return f"（收到了一个{suffix}文件：{name}，暂时只能读取txt和docx格式）"

    except Exception as e:
        log_error("media_processor.process_file", e)
    return None
