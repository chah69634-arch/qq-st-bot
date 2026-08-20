from pathlib import Path
import re

from admin_static_assets import read_admin_client_source, read_admin_page


ROOT = Path(__file__).parents[1]
I18N = ROOT / "admin" / "static" / "i18n.js"


def _dictionary_keys(runtime: str, language: str) -> set[str]:
    if language == "zh-CN":
        body = re.search(r"'zh-CN': \{(.*?)\n    \},\n    en: \{", runtime, re.S)
    else:
        body = re.search(r"\n    en: \{(.*?)\n    \},\n  \};", runtime, re.S)
    assert body is not None
    return set(re.findall(r"^\s+'([^']+)':", body.group(1), re.M))


def test_every_builtin_tool_has_bilingual_ui_description_without_changing_schema_text():
    from core.tool_dispatcher import _TOOL_REGISTRY

    runtime = I18N.read_text(encoding="utf-8")
    zh = _dictionary_keys(runtime, "zh-CN")
    en = _dictionary_keys(runtime, "en")
    missing = {
        name
        for name, spec in _TOOL_REGISTRY.items()
        if spec.get("category") != "mcp"
        and (f"tools.description.{name}" not in zh or f"tools.description.{name}" not in en)
    }
    assert not missing
    assert "tools.description.desktop_minimize" in zh
    assert "tools.description.clear_midterm" in zh
    assert "仅在用户明确要求清除最近记忆时调用" in runtime
    assert "does not affect episodic memory or the stable profile" in runtime
    assert "_toolUiDescription(tool)" in read_admin_client_source()


def test_mcp_ux_preserves_remote_raw_boundary_and_domain_selector_contract():
    source = read_admin_client_source()
    page = read_admin_page("mcp")
    for marker in (
        "const MCP_DEFAULT_HEADERS = Object.freeze({});",
        "allowEmpty: true",
        "mcp.header.name",
        "mcp.metadata.mapping_help",
        "_mcpDomainChips(server, selector)",
        "_renderMcpManualDomainChips(input, server)",
        "mcp-domain-manual-chips-",
        "data-mcp-domain-choice",
        "calendar, health, files, hardware",
        "mcp.remote_description_label",
        "class=\"i18n-raw\"",
        "mcp.state.session_exposed",
        "mcp.state.remote_category",
        "mcp.state.final_category",
        "mcp.state.classification_status",
    ):
        assert marker in source
    assert "domain1, domain2" not in source
    assert "data-i18n=\"mcp.field.name\"" in page
    assert "data-i18n=\"mcp.metadata.namespace\"" in page
    assert "data-i18n=\"mcp.console.arguments\"" in page


def test_mcp_import_and_console_static_copy_use_semantic_i18n_keys():
    runtime = I18N.read_text(encoding="utf-8")
    page = read_admin_page("mcp")
    keys = (
        "mcp.field.name",
        "mcp.field.url",
        "mcp.field.transport",
        "mcp.field.timeout",
        "mcp.add_header",
        "mcp.header.name",
        "mcp.header.value",
        "mcp.metadata.mapping_help",
        "mcp.metadata.schema_version_field",
        "mcp.metadata.domains_field",
        "mcp.metadata.interaction_field",
        "mcp.console.arguments",
        "mcp.console.add_argument",
    )
    for key in keys:
        assert runtime.count(f"'{key}'") == 2
    assert "<span>name</span>" not in page
    assert "<span>url</span>" not in page
    assert "<span>transport</span>" not in page
    assert "Add header" not in page
    assert "Add argument" not in page
