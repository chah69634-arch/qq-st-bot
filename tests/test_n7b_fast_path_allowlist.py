"""
tests/test_n7b_fast_path_allowlist.py — N7-B 快速路径白名单收窄

覆盖：
  1. FAST_PATH_TOOL_ALLOWLIST 结构验证（frozenset，只含安全工具）
  2. allowlist 内工具（get_time）仍能 fast path
  3. desktop_open_url 不再 fast path（含"打开"等关键词）
  4. media control（play_song / desktop_play_pause）不再 fast path
  5. garden 写操作（water_garden）不再 fast path
  6. add_reminder 不再 fast path（含必填参数，有副作用）
  7. 普通闲聊包含"打开/播放/花园/提醒/天气"等词时 _fast_path_match 返回 None
  8. 明确工具请求（非 get_time）fast path 返回 None，应由 LLM probe 处理
  9. allowlist 不包含有副作用或有必填参数的工具（结构安全断言）
"""

import pytest
from core.pretool_router import fast_path_match as _fast_path_match, FAST_PATH_TOOL_ALLOWLIST
from core import tool_dispatcher


# ─────────────────────────────────────────────────────────────────────────────
# 1. allowlist 结构验证
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowlistStructure:
    def test_is_frozenset(self):
        assert isinstance(FAST_PATH_TOOL_ALLOWLIST, frozenset)

    def test_contains_get_time(self):
        assert "get_time" in FAST_PATH_TOOL_ALLOWLIST

    def test_all_allowlist_tools_have_no_required_params(self):
        """allowlist 内每个工具都必须是零必填参数的。"""
        for tool_name in FAST_PATH_TOOL_ALLOWLIST:
            spec = tool_dispatcher._TOOL_REGISTRY.get(tool_name, {})
            required = spec.get("parameters", {}).get("required", [])
            assert required == [], (
                f"{tool_name!r} has required params {required} — unsafe for fast path"
            )

    def test_all_allowlist_tools_have_no_side_effects(self):
        """allowlist 内每个工具都必须是无副作用的。"""
        for tool_name in FAST_PATH_TOOL_ALLOWLIST:
            assert not tool_dispatcher.is_side_effect_tool(tool_name), (
                f"{tool_name!r} is a side-effect tool — must not be in FAST_PATH_TOOL_ALLOWLIST"
            )

    def test_side_effect_tools_not_in_allowlist(self):
        """所有有副作用的工具不得在 allowlist 中。"""
        side_effect_tools = [
            "water_garden", "add_reminder", "desktop_open_url",
            "desktop_play_pause", "desktop_minimize", "desktop_notify",
            "play_song", "exit_yandere", "device_shutdown", "device_sleep",
        ]
        for tool_name in side_effect_tools:
            assert tool_name not in FAST_PATH_TOOL_ALLOWLIST, (
                f"Side-effect tool {tool_name!r} must not be in FAST_PATH_TOOL_ALLOWLIST"
            )

    def test_param_requiring_tools_not_in_allowlist(self):
        """有必填参数的工具不得在 allowlist 中。"""
        param_tools = [
            "add_reminder", "weather", "web_search",
            "desktop_open_url", "desktop_minimize", "play_song", "desktop_notify",
        ]
        for tool_name in param_tools:
            assert tool_name not in FAST_PATH_TOOL_ALLOWLIST, (
                f"Param-requiring tool {tool_name!r} must not be in FAST_PATH_TOOL_ALLOWLIST"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. allowlist 内工具仍能 fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowlistToolsStillFastPath:
    @pytest.mark.parametrize("text", [
        "现在几点了",
        "几点了",
        "今天几号",
        "现在什么时间",
        "今天星期几",
        "现在几点",
    ])
    def test_get_time_fast_paths(self, text):
        result = _fast_path_match(text)
        assert result is not None, f"get_time 应 fast path 命中文本: {text!r}"
        tool_name, kw = result
        assert tool_name == "get_time"
        assert tool_name in FAST_PATH_TOOL_ALLOWLIST


# ─────────────────────────────────────────────────────────────────────────────
# 3. desktop_open_url 不再 fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestDesktopOpenUrlNotFastPath:
    @pytest.mark.parametrize("text", [
        "打开bilibili",
        "帮我开一下知乎",
        "我打开了窗户",       # 日常闲聊："打开"不触发 open_url
        "打开冰箱看看",       # 日常闲聊
        "开一下门",          # 日常闲聊
    ])
    def test_open_url_keywords_do_not_fast_path(self, text):
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 文本 {text!r} 不应经由快速路径命中 desktop_open_url"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. media control 工具不再 fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestMediaControlNotFastPath:
    @pytest.mark.parametrize("text", [
        "播放稻香",
        "放一首歌",
        "听周杰伦",
        "暂停音乐",
        "继续播放",
        "暂停一下",
        "我刚刚播放了一首歌",   # 日常叙述："播放"不触发 play_song
        "放歌给我听",
    ])
    def test_media_keywords_do_not_fast_path(self, text):
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 文本 {text!r} 不应经由快速路径命中 play_song / desktop_play_pause"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. garden 写操作不再 fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestGardenNotFastPath:
    @pytest.mark.parametrize("text", [
        "快去浇花",
        "花园里的花怎么样了",
        "浇水了吗",
        "花园好漂亮",           # 日常闲聊："花园"不触发 water_garden
        "你花园里种了什么",      # 日常闲聊
        "花园好漂亮啊今天",
    ])
    def test_garden_keywords_do_not_fast_path(self, text):
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 文本 {text!r} 不应经由快速路径命中 water_garden"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. add_reminder 不再 fast path
# ─────────────────────────────────────────────────────────────────────────────

class TestAddReminderNotFastPath:
    @pytest.mark.parametrize("text", [
        "提醒我8点吃药",
        "帮我记一下",
        "记得帮我带伞",
        "提醒我想起以前的事",   # 日常叙述："提醒"不触发 add_reminder
        "提醒我想起……",         # 日常叙述
        "今天让我想起了很多事",
    ])
    def test_reminder_keywords_do_not_fast_path(self, text):
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 文本 {text!r} 不应经由快速路径命中 add_reminder"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. 普通闲聊包含危险词时不 fast path（核心安全验证）
# ─────────────────────────────────────────────────────────────────────────────

class TestCasualChatNotFastPath:
    """包含"打开/播放/花园/提醒/天气"等词的日常闲聊不得被 fast path 命中。"""

    @pytest.mark.parametrize("text", [
        "我打开了窗户",
        "我刚刚播放了一首歌",
        "花园好漂亮",
        "提醒我想起以前……",
        "今天天气不错",
        "感觉很暖和",
        "你最近帮我搜了什么",
        "我在想有没有提醒过你",
        "帮我查一下心情",
        "打开心扉跟你聊聊",
    ])
    def test_casual_chat_does_not_fast_path(self, text):
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 日常句子 {text!r} 不应被 fast path 命中非 allowlist 工具"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 8. 明确工具请求（非 get_time）fast path 返回 None，应由 probe 处理
# ─────────────────────────────────────────────────────────────────────────────

class TestExplicitToolRequestGoesToProbe:
    """明确的非 get_time 工具请求不走 fast path，交给 LLM probe 识别。

    被排除出 fast path ≠ 禁用工具。probe 仍会识别意图并调用工具。
    """

    @pytest.mark.parametrize("text", [
        "今天天气怎么样",       # weather → probe
        "帮我提醒我8点吃药",    # add_reminder → probe
        "播放稻香这首歌",       # play_song → probe
        "快去浇花",             # water_garden → probe
        "帮我搜一下最新消息",   # web_search → probe
        "打开bilibili",         # desktop_open_url → probe
        "最小化微信窗口",       # desktop_minimize → probe
        "暂停音乐",             # desktop_play_pause → probe
    ])
    def test_explicit_request_bypasses_fast_path(self, text):
        """明确的工具意图应返回 None，由 probe 而非 fast path 处理。"""
        result = _fast_path_match(text)
        assert result is None or result[0] in FAST_PATH_TOOL_ALLOWLIST, (
            f"N7-B: 文本 {text!r} 不应 fast path，应交由 probe 处理"
        )
