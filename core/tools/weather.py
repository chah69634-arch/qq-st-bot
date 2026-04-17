"""
天气查询工具
调用 wttr.in 免费天气 API，返回城市当前天气文本。
"""

import asyncio

import aiohttp

from core.error_handler import log_error
from core.proxy_config import get_aiohttp_proxy


async def get_weather(city: str) -> str:
    """查询指定城市的当前天气，返回一行天气描述文本"""
    url = f"https://wttr.in/{city}?format=3&lang=zh"
    proxy = get_aiohttp_proxy()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
                proxy=proxy,
            ) as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
                return f"获取天气失败，HTTP {resp.status}"
    except asyncio.TimeoutError:
        return "天气查询超时，请稍后再试"
    except Exception as e:
        log_error("tool.weather", e)
        return "天气查询出错"
