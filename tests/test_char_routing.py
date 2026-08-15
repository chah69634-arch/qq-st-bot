"""
tests/test_char_routing.py — Brief 30 · LLM 路由的 char 维度穿线

覆盖 cc-tasks/30-LLM路由char维度穿线.md §3 的 5 项测试：
1. char_id=None → 与现行为逐字节一致（活跃角色 override 生效）。
2. 显式 char_id=X（X 卡带 model_routing）且活跃角色是 Y → 解析用 X 的 profile。
3. X 卡无 presence_ext → 回落全局 active_routing（不是 Y 的 override）。
4. 日记多角色：白名单两个角色、卡路由不同 → 两次生成各用各的 preset。
5. 缓存：两个 preset 交替解析，client 实例各自稳定复用、互不串。
"""
from __future__ import annotations

import types
from dataclasses import dataclass, field

import pytest


_MP_CONFIG = {
    "active_routing": "default",
    "defaults": {},
    "presets": {
        "ds": {
            "provider_kind": "deepseek",
            "base_url": "",
            "api_key": "test-only-placeholder",
            "model": "ds-chat",
        },
        "claude": {
            "provider_kind": "anthropic_compat",
            "base_url": "",
            "api_key": "test-only-placeholder",
            "model": "claude",
        },
    },
    "routing_profiles": {
        "default": {"chat": "ds", "intent": "ds"},
        "claude-main": {"chat": "claude", "intent": "ds"},
    },
}


@dataclass
class _FakeChar:
    name: str = "Fake"
    gender: str = "neutral"
    presence_ext: dict = field(default_factory=dict)


@dataclass
class _FakePipeline:
    character: object


@pytest.fixture(autouse=True)
def _clear_pipeline_registry():
    from core import pipeline_registry
    pipeline_registry.register(None)
    yield
    pipeline_registry.register(None)


def _register_active_char(**presence_ext_kwargs):
    """注册"活跃角色"——char_id=None 路径读的是它（Brief 29 既有语义）。"""
    from core import pipeline_registry
    char = _FakeChar(presence_ext=presence_ext_kwargs)
    pipeline_registry.register(_FakePipeline(character=char))
    return char


def _patch_char_card(monkeypatch, cards: dict):
    """monkeypatch character_loader.load(char_id) → 对应角色卡（显式 char_id 路径读它）。

    未在映射里的 char_id → 抛 ValueError（模拟未注册/加载失败），走 fail-soft 回落。
    """
    def _fake_load(char_id):
        if char_id not in cards:
            raise ValueError(f"unknown char {char_id!r}")
        return _FakeChar(presence_ext=cards[char_id])

    monkeypatch.setattr("core.character_loader.load", _fake_load)


# ─────────────────────────────────────────────────────────────────────────────
# 1. char_id=None → 与现行为逐字节一致（活跃角色 override 生效）
# ─────────────────────────────────────────────────────────────────────────────

class TestCharIdNoneMatchesCurrentBehavior:
    def test_no_active_char_no_override(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        assert mr._resolve_preset_name("chat") == "ds"
        assert mr._resolve_preset_name("chat", char_id=None) == "ds"

    def test_active_char_override_still_applies_when_char_id_omitted_or_none(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        _register_active_char(model_routing="claude-main")

        # 不传 char_id、显式传 None：逐字节一致，都读活跃角色卡的 override
        assert mr._resolve_preset_name("chat") == "claude"
        assert mr._resolve_preset_name("chat", char_id=None) == "claude"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 显式 char_id=X（带 model_routing）覆盖活跃角色 Y 的路由
# ─────────────────────────────────────────────────────────────────────────────

class TestExplicitCharIdUsesOwnCard:
    def test_explicit_char_routes_by_its_own_card_not_active_char(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        _patch_char_card(monkeypatch, {"X": {"model_routing": "claude-main"}})
        _register_active_char()  # 活跃角色 Y，无 override（走全局 default）

        assert mr._resolve_preset_name("chat", char_id="X") == "claude"

    def test_explicit_char_routing_wins_even_when_active_char_differs(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        _patch_char_card(monkeypatch, {"X": {"model_routing": "claude-main"}})
        _register_active_char(model_routing="default")  # 活跃角色 Y 显式指向 default

        assert mr._resolve_preset_name("chat", char_id="X") == "claude"


# ─────────────────────────────────────────────────────────────────────────────
# 3. X 卡无 presence_ext → 回落全局 active_routing（不是 Y 的 override）
# ─────────────────────────────────────────────────────────────────────────────

class TestExplicitCharFallsBackToGlobalNotActiveOverride:
    def test_char_without_model_routing_field_falls_back_to_global(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        _patch_char_card(monkeypatch, {"X": {}})  # X 卡存在但无 model_routing 字段
        _register_active_char(model_routing="claude-main")  # 活跃角色 Y 指向 claude

        # 显式传 X：X 无 override → 回落全局 active_routing="default"→"ds"，
        # 绝不能读到 Y 的 "claude-main" override（这是 §2.1 的核心行为边界）
        assert mr._resolve_preset_name("chat", char_id="X") == "ds"

    def test_char_load_failure_falls_back_to_global(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        _patch_char_card(monkeypatch, {})  # 任何 char_id 都会 raise（未注册/文件缺失）
        _register_active_char(model_routing="claude-main")

        assert mr._resolve_preset_name("chat", char_id="unregistered") == "ds"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 日记多角色：白名单两个角色、卡路由不同 → 两次生成各用各的 preset
# ─────────────────────────────────────────────────────────────────────────────

def _make_fake_model_client(name: str, content: str):
    from core.model_registry import ModelClient

    async def fake_create(**kwargs):
        msg = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=msg)
        return types.SimpleNamespace(choices=[choice])

    completions = types.SimpleNamespace(create=fake_create)
    chat_obj = types.SimpleNamespace(completions=completions)
    fake_client = types.SimpleNamespace(chat=chat_obj)

    return ModelClient(
        name=name,
        provider_kind="deepseek",
        model=f"{name}-model",
        tool_call_mode="function_calling",
        prompt_style="narrative",
        params={},
        client=fake_client,
    )


@pytest.mark.asyncio
async def test_diary_multi_char_each_generation_uses_own_preset(monkeypatch, sandbox):
    """白名单两个角色、卡路由不同 → 各自生成日记时 get_model_client 收到各自的 char_id
    （Brief 30 · §1 现存 bug 的修复验证：修复前两次调用都不带 char_id）。
    """
    from core.scheduler.triggers import time_based

    monkeypatch.setattr(
        "core.scheduler.triggers.time_based.get_char_name",
        lambda char_id: char_id,
    )
    monkeypatch.setattr(
        "core.memory.event_log.get_recent_days",
        lambda oid, days=1, **kw: "## 14:30\n**用户**：在干嘛\n**A**：想你了\n---\n",
    )
    monkeypatch.setattr("core.integrity_check.check_diary_facts", lambda text: [])

    _presets = {"char_a": "preset-a", "char_b": "preset-b"}
    seen: list[tuple[str, str | None]] = []

    def _fake_get_model_client(call_category, *, char_id=None):
        seen.append((call_category, char_id))
        preset = _presets.get(char_id, "preset-default")
        return _make_fake_model_client(preset, f"内容-{preset}")

    monkeypatch.setattr("core.llm_client.get_model_client", _fake_get_model_client)

    await time_based._generate_and_store_diary("owner1", "char_a")
    await time_based._generate_and_store_diary("owner1", "char_b")

    assert seen == [
        ("chat", "char_a"), ("chat", "char_a"),
        ("chat", "char_b"), ("chat", "char_b"),
    ]

    diary_a = sandbox.yexuan_inner_diary(char_id="char_a")
    diary_b = sandbox.yexuan_inner_diary(char_id="char_b")
    assert any(diary_a.iterdir())
    assert any(diary_b.iterdir())


# ─────────────────────────────────────────────────────────────────────────────
# 5. 缓存：两个 preset 交替解析，client 实例各自稳定复用、互不串
# ─────────────────────────────────────────────────────────────────────────────

class TestClientCacheStableAcrossChars:
    def test_alternating_chars_reuse_stable_clients_with_no_crosstalk(self, monkeypatch):
        import core.model_registry as mr
        monkeypatch.setattr(mr, "_get_preset_config", lambda: _MP_CONFIG)
        monkeypatch.setattr(mr, "_model_clients", {})
        _patch_char_card(monkeypatch, {
            "charA": {"model_routing": "claude-main"},
            "charB": {},  # 无 override → 全局 default → ds
        })

        mc_a1 = mr.get_model_client("chat", char_id="charA")
        mc_b1 = mr.get_model_client("chat", char_id="charB")
        mc_a2 = mr.get_model_client("chat", char_id="charA")
        mc_b2 = mr.get_model_client("chat", char_id="charB")

        assert mc_a1.name == "claude"
        assert mc_b1.name == "ds"
        assert mc_a1 is mc_a2, "同一 preset 应复用同一 ModelClient 实例"
        assert mc_b1 is mc_b2, "同一 preset 应复用同一 ModelClient 实例"
        assert mc_a1 is not mc_b1, "不同 preset 的 client 不得互相串用"
