"""Admin Dream operations page is wired into the versioned static shell."""
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_admin_dream_operations_static_wiring():
    index = (ROOT / "admin/static/index.html").read_text(encoding="utf-8")
    core = (ROOT / "admin/static/js/core.js").read_text(encoding="utf-8")
    i18n = (ROOT / "admin/static/i18n.js").read_text(encoding="utf-8")
    assert "observe-dream-operations" in index
    assert "dream-operations-1" in index
    assert "observe-dream-operations" in core
    assert "dream_ops.title" in i18n
    assert "dream_ops.title" in (ROOT / "admin/static/pages/observe-dream-operations.html").read_text(encoding="utf-8")
