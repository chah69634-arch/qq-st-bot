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
    ):
        assert marker in source
