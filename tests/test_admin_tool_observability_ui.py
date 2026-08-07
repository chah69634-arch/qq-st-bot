from admin_static_assets import read_admin_client_source


def test_tool_observability_page_uses_read_only_trace_and_shared_mcp_ledger():
    source = read_admin_client_source()

    for marker in (
        'data-page="observe-tools"',
        'id="page-observe-tools"',
        "loadObserveTools()",
        "loadObserveToolUidList()",
        "/observability/tool-traces",
        "getMcpRecentCalls(caller, limit = 1)",
        "_loadObserveToolMcpLedger",
        "action_trace",
        'value="probe"',
        "category === 'probe' ? '/observe/probe' : '/observability/tool-traces'",
        "await loadObserveProbe(el, uid)",
        "exposure_path || 'path_a'",
        "exposure_categories",
    ):
        assert marker in source


def test_prompt_inspector_groups_repeated_message_records_by_layer():
    source = read_admin_client_source()
    for marker in (
        "const groupedLayers = new Map()",
        "group.content = [group.content, lyr.content].filter(Boolean).join('\\n\\n')",
    ):
        assert marker in source
