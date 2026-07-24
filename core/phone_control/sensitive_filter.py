"""敏感页面硬拦截器 — phone_control 循环每一步观察都必须先过这道闸。

命中即返回拦截原因，不把"要不要点"的判断权交给视觉模型——这是防线，不是建议。关键词表
故意保守：宁可错拦一个正常页面，也不放过一个真实的支付/密码页。设备侧（Android）也要用
同一份逻辑做本地二次校验，两边独立判断，任一方拦截即停止，不是"后端说了算"。

见 docs/protocols/phone-control-protocol.md（Emerald-mobile 仓库）。
"""
from __future__ import annotations

# 命中任一关键词即拦截；子串匹配、大小写不敏感。中英文都覆盖，因为截图/节点文本可能来自
# 国际化 App。
SENSITIVE_KEYWORDS: frozenset[str] = frozenset({
    "密码", "支付密码", "交易密码", "手势密码", "指纹密码", "输入密码", "登录密码",
    "支付", "付款", "确认支付", "立即支付", "支付方式", "收银台", "去支付",
    "银行卡", "信用卡", "储蓄卡", "卡号", "有效期",
    "验证码", "短信验证码", "动态口令", "动态密码",
    "银行", "网银", "转账", "汇款", "u盾", "网上银行", "手机银行",
    "password", "passcode", "pin code", "payment", "checkout", "pay now",
    "card number", "cvv", "cvv2", "expiry date", "otp", "verification code",
    "one-time code", "bank account", "wire transfer", "billing",
})

# 只有整个 App 本身就是银行/支付类工具时才按包名整体拦截；微信、支付宝这类聊天/生活服务
# 里内嵌支付子页面的混合型 App，靠上面的关键词识别具体页面，不能按包名一刀切拦掉整个 App。
SENSITIVE_PACKAGE_SUBSTRINGS: frozenset[str] = frozenset({
    "unionpay", "bank", "icbc", "ccb.crm", "abc.tm", "spdb", "cmbchina", "psbc",
    "bankcomm", "cib.mobile", "bocmbci",
})


def _normalize(text: str) -> str:
    return text.strip().lower()


def is_sensitive_text(*texts: str | None) -> str | None:
    """任一文本命中敏感关键词则返回该关键词，否则 None。"""
    for raw in texts:
        if not raw:
            continue
        normalized = _normalize(raw)
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in normalized:
                return keyword
    return None


def is_sensitive_package(package_name: str | None) -> bool:
    if not package_name:
        return False
    normalized = _normalize(package_name)
    return any(marker in normalized for marker in SENSITIVE_PACKAGE_SUBSTRINGS)


def check_observation(
    *,
    package_name: str | None,
    screen_title: str | None,
    node_texts: list[str],
) -> str | None:
    """检查一次设备上报的观察。通过返回 None；命中拦截则返回人类可读的拦截原因

    （直接用作 /phone_control/step 响应里 need_confirmation 的 message）。
    """
    if is_sensitive_package(package_name):
        return f"识别到银行/支付类 App（{package_name}），已停止自动操作，请自己完成剩余步骤"
    hit = is_sensitive_text(screen_title, *node_texts)
    if hit:
        return f"页面内容包含敏感关键词「{hit}」，已停止自动操作，请自己完成剩余步骤"
    return None
