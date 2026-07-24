from pathlib import Path
import re


STATIC = Path(__file__).parents[1] / "admin" / "static"


def test_admin_html_is_a_shell_with_ordered_plain_static_assets():
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/static/style.css">' in index
    assert "<style>" not in index
    assert '<script src="/static/i18n.js"></script>' in index
    scripts = re.findall(r'<script src="/static/js/([^"]+)"></script>', index)
    assert scripts[0] == "core.js"
    assert len(scripts) >= 2
    assert all((STATIC / "js" / script).is_file() for script in scripts)
    assert "<script>" not in index
    assert "type=\"module\"" not in index


def test_split_static_assets_keep_global_navigation_and_inline_handler_functions():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    source = "\n".join(
        (STATIC / "js" / name).read_text(encoding="utf-8")
        for name in re.findall(r'<script src="/static/js/([^"]+)"></script>', index)
    )

    for function in ("goto", "api", "escapeHtml", "loadMcpPage", "loadDreamSettings", "loadObserveVisual"):
        assert re.search(rf"(?:async )?function {function}\(", source)

    handlers = set(re.findall(r'onclick="([A-Za-z_]\w*)\(', index))
    missing = sorted(
        name for name in handlers
        if not re.search(rf"(?:async )?function {name}\(", source)
    )
    assert not missing, f"inline handlers must remain global functions: {missing}"
