"""Helpers for tests that inspect the split admin static bundle."""

from pathlib import Path
import re


STATIC = Path(__file__).parents[1] / "admin" / "static"
INDEX = STATIC / "index.html"
PAGES = STATIC / "pages"


def read_admin_page(page: str) -> str:
    """Read one lazily injected admin page fragment."""
    return (PAGES / f"{page}.html").read_text(encoding="utf-8")


def read_admin_client_source() -> str:
    """Return the HTML shell, page fragments, and scripts in browser load order."""
    index = INDEX.read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="/static/js/([^"]+)"></script>', index)
    assert scripts, "admin page scripts must be loaded from admin/static/js"
    sources = [index]
    fragments = sorted(PAGES.glob("*.html"))
    assert fragments, "admin pages must be split into admin/static/pages"
    sources.extend(fragment.read_text(encoding="utf-8") for fragment in fragments)
    sources.extend((STATIC / "js" / script).read_text(encoding="utf-8") for script in scripts)
    return "\n".join(sources)
