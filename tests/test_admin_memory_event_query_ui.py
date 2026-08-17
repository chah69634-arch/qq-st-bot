from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_memory_event_query_page_is_registered_and_cache_busted():
    index = (ROOT / "admin/static/index.html").read_text(encoding="utf-8")
    core = (ROOT / "admin/static/js/core.js").read_text(encoding="utf-8")
    script = (ROOT / "admin/static/js/observability.js").read_text(encoding="utf-8")
    fragment = (ROOT / "admin/static/pages/observe-memory-events.html").read_text(encoding="utf-8")

    assert 'data-page="observe-memory-events"' in index
    assert 'id="page-observe-memory-events"' in index
    assert "ADMIN_UI_FRAGMENT_VERSION = 'brief-199-memory-events-1'" in core
    assert '<script src="/static/js/core.js?v=brief-199-memory-events-1"></script>' in index
    assert '<script src="/static/js/observability.js?v=brief-199-memory-events-1"></script>' in index
    assert "loadMemoryEventSearch" in script
    assert "/memory-events/query-trace" in script
    assert 'id="event-query-result"' in fragment
