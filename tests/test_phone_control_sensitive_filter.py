"""phone_control 敏感页面硬拦截器 —— 安全关键路径，必须有测试兜底。"""
import pytest

from core.phone_control.sensitive_filter import check_observation, is_sensitive_text


@pytest.mark.parametrize(
    "screen_title,node_texts",
    [
        ("请输入支付密码", []),
        ("收银台", ["确认支付", "去支付"]),
        ("", ["请输入银行卡号", "CVV"]),
        ("Checkout", ["Pay now", "Card number"]),
        ("", ["短信验证码已发送"]),
    ],
)
def test_check_observation_blocks_sensitive_pages(screen_title, node_texts):
    reason = check_observation(
        package_name="com.taobao.taobao",
        screen_title=screen_title,
        node_texts=node_texts,
    )
    assert reason is not None


def test_check_observation_blocks_banking_app_by_package():
    reason = check_observation(
        package_name="com.icbc.mobile.android",
        screen_title="首页",
        node_texts=["查看余额"],
    )
    assert reason is not None
    assert "icbc" in reason.lower() or "银行" in reason


def test_check_observation_allows_normal_shopping_page():
    reason = check_observation(
        package_name="com.taobao.taobao",
        screen_title="购物车",
        node_texts=["去结算", "增加数量", "删除"],
    )
    assert reason is None


def test_mixed_app_only_blocks_the_sensitive_subpage_not_the_whole_app():
    # 微信这类聊天+支付混合 App 不能按包名整体拦截，只在真的进了支付子页面时才拦。
    chat_reason = check_observation(
        package_name="com.tencent.mm",
        screen_title="张三",
        node_texts=["晚上一起吃饭吗", "发送"],
    )
    assert chat_reason is None

    pay_reason = check_observation(
        package_name="com.tencent.mm",
        screen_title="",
        node_texts=["输入支付密码"],
    )
    assert pay_reason is not None


def test_is_sensitive_text_case_insensitive_and_substring():
    assert is_sensitive_text("Please enter your PASSWORD") is not None
    assert is_sensitive_text("普通购物车页面，没有敏感内容") is None
    assert is_sensitive_text(None, "", "去结算") is None
