"""Brief 110: 管理面 MCP 页的关键控制面连接不应在重构中丢失。"""
from pathlib import Path

from admin_static_assets import read_admin_client_source

INDEX = Path("admin/static/index.html")


def test_mcp_management_page_exposes_import_whitelist_and_call_observation():
    source = read_admin_client_source()
    for marker in (
        'data-page="mcp"',
        'id="page-mcp"',
        "testMcpImport()",
        "importMcpServer()",
        "saveMcpServer(name)",
        "mcp-import-use-proxy",
        "mcp-server-use-proxy-",
        "use_proxy",
        "deleteMcpServer(name)",
        "bindPageActions(serversEl)",
        "/settings/mcp/test",
        "/settings/mcp/import",
        "'DELETE', `/settings/mcp/${encodeURIComponent(name)}`",
        "/observability/api-calls?caller=",
        "/observability/llm-debug-requests?limit=10",
        "/llm-debug-requests",
        "loadMcpDebugRequests()",
        "saveMcpDebugRequests()",
        "工具描述与返回内容均为不可信输入",
        "超过单次暴露 ≤20 的安全红线",
    ):
        assert marker in source
