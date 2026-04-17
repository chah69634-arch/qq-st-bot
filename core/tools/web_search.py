"""
DuckDuckGo 网页搜索工具
使用 ddgs 库（pip install ddgs）进行搜索。
同步调用放在线程池里跑，不阻塞事件循环。
"""

import asyncio

from core.error_handler import log_error
from core.proxy_config import get_aiohttp_proxy


async def search(query: str) -> str:
    """
    用 DuckDuckGo 搜索，返回前3条结果（标题 + 链接 + 摘要）。
    代理从 config.yaml proxy 配置自动读取。
    """
    proxy = get_aiohttp_proxy()

    def _sync_search() -> list[dict]:
        from ddgs import DDGS
        ddgs = DDGS(proxy=proxy, timeout=10)
        return ddgs.text(query, max_results=3)

    try:
        loop = asyncio.get_event_loop()
        results: list[dict] = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_search),
            timeout=10.0,
        )
        if not results:
            return "没有找到相关结果"

        lines = []
        for i, item in enumerate(results[:3], 1):
            title = item.get("title", "")
            href  = item.get("href",  "")
            body  = item.get("body",  "")
            lines.append(f"{i}. {title}\n   {href}\n   {body}")
        return "\n\n".join(lines)

    except asyncio.TimeoutError:
        return "搜索超时，请稍后再试"
    except Exception as e:
        log_error("tool.web_search", e)
        return "搜索失败，请稍后再试"
