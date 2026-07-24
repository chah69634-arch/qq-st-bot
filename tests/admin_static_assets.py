"""Helpers for tests that inspect the split admin static bundle."""

from pathlib import Path
import re


STATIC = Path(__file__).parents[1] / "admin" / "static"
INDEX = STATIC / "index.html"


def read_admin_client_source() -> str:
    """Return the HTML shell plus page scripts in their browser load order."""
    index = INDEX.read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="/static/js/([^"]+)"></script>', index)
    assert scripts, "admin page scripts must be loaded from admin/static/js"
    sources = [index]
    sources.extend((STATIC / "js" / script).read_text(encoding="utf-8") for script in scripts)
    return "\n".join(sources)
