from pathlib import Path

from admin_static_assets import read_admin_client_source

INDEX = Path(__file__).parents[1] / "admin" / "static" / "index.html"


def test_group_prompt_filter_excludes_private_and_direct_chat_snapshots():
    source = read_admin_client_source()

    assert "return origin.origin === 'stage' && origin.group_id === groupId;" in source
    assert "snapshots.filter(snapshot => _isStagePromptForGroup(snapshot, id))" in source
    assert "origin.origin === 'private_exchange'" in source


def test_group_private_exchange_prompt_capture_wired_into_group_page():
    """Brief 106 §5: raw build_prompt capture for private_exchange, not just the
    transcript, must be reachable from the group observability page so §3/§4's
    identity/instruction-framing fixes can be verified against a real prompt."""
    source = read_admin_client_source()

    assert "_isPrivatePromptForGroup" in source
    assert "origin.origin !== 'private_exchange'" in source
    assert "_renderPrivatePromptSnapshot" in source
    assert "privatePromptSnapshots" in source


def test_group_observability_uses_read_only_sources_and_required_empty_state():
    source = read_admin_client_source()

    assert "/relations/private-log?${query}" in source
    assert "/observe/prompt-layers/${encodeURIComponent(uid)}?n=0" in source
    assert "这两位还没私下聊过" in source
    assert "t('group.private_none', '这两位还没私下聊过')" in source
    assert "privateEnabled?t('common.enabled','已启用'):t('common.disabled','未启用')" in source
