from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_runtime_signals_admin_page_is_read_only_and_wired_to_its_endpoint():
    index = (ROOT / "admin" / "static" / "index.html").read_text(encoding="utf-8")
    page = (ROOT / "admin" / "static" / "pages" / "observe-runtime-signals.html").read_text(encoding="utf-8")
    script = (ROOT / "admin" / "static" / "js" / "observability.js").read_text(encoding="utf-8")

    assert 'data-page="observe-runtime-signals"' in index
    assert 'id="page-observe-runtime-signals" data-page-fragment="observe-runtime-signals"' in index
    assert 'data-action="loadRuntimeSignals"' in page
    assert "async function loadRuntimeSignals()" in script
    assert "api('GET', '/observability/runtime-signals')" in script
    assert "POST" not in page and "DELETE" not in page
