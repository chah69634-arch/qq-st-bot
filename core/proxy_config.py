"""
代理配置模块
───────────────────────────────────────────────────
统一读取 config.yaml 的 proxy 配置，供所有需要走代理的模块使用。

设计原则：
  - 每次调用都重新读 config，不做本地缓存
    这样 admin 面板修改 config.yaml 后，下一次请求就能自动生效（热重载）
  - 返回格式兼容 httpx / requests 的 proxies 字典，以及 aiohttp 的单字符串用法

用法示例：
    from core.proxy_config import get_proxies, get_aiohttp_proxy

    # httpx / requests
    proxies = get_proxies()          # {"http://": "...", "https://": "..."} 或 None
    httpx.get(url, proxies=proxies)

    # aiohttp
    proxy = get_aiohttp_proxy()      # "http://..." 字符串 或 None
    session.get(url, proxy=proxy)
"""

from core.config_loader import get_config


def get_proxies() -> dict | None:
    """
    读取 config.yaml 的 proxy 配置。

    enabled=true  时返回：
        {
            "http://":  "http://127.0.0.1:7897",
            "https://": "http://127.0.0.1:7897",
        }
        （httpx/requests 标准格式，key 带 "://" 后缀）

    enabled=false 时返回 None。

    每次调用都重新读 config，不缓存，支持热重载。
    """
    # 每次调用都重新拿 config（config_loader 内部有单例，
    # reload_config() 之后这里就能拿到新值）
    proxy_cfg = get_config().get("proxy", {})

    if not proxy_cfg.get("enabled", False):
        return None

    result = {}
    http_url = proxy_cfg.get("http", "")
    https_url = proxy_cfg.get("https", "")

    if http_url:
        result["http://"] = http_url
    if https_url:
        result["https://"] = https_url

    # 两个都没配置，视为未启用
    return result if result else None


def get_aiohttp_proxy() -> str | None:
    """
    返回适合 aiohttp 使用的代理 URL 字符串（单个 URL，不是字典）。

    aiohttp 的 session.get(url, proxy=...) 只接受字符串，不接受字典。
    优先返回 https 代理，没有则返回 http 代理，都没有返回 None。

    enabled=false 时返回 None。
    """
    proxy_cfg = get_config().get("proxy", {})

    if not proxy_cfg.get("enabled", False):
        return None

    # 优先用 https，因为大多数外部 API 是 https 链接
    return (
        proxy_cfg.get("https")
        or proxy_cfg.get("http")
        or None
    )
