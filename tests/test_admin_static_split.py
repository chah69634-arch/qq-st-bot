from pathlib import Path
import re

from admin_static_assets import PAGES, read_admin_client_source


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


def test_every_page_is_a_lazy_fragment_with_its_original_placeholder():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    fragments = sorted(PAGES.glob("*.html"))

    assert len(fragments) == 33
    for fragment in fragments:
        page = fragment.stem
        assert f'id="page-{page}" data-page-fragment="{page}"' in index
        assert fragment.read_text(encoding="utf-8").strip()

    source = read_admin_client_source()
    assert "async function loadPageFragment(page)" in source
    assert "fetch(`/static/pages/${encodeURIComponent(page)}.html`)" in source
    assert "window.AdminI18n?.applyI18n(container)" in source


def test_removed_legacy_pet_and_chat_panels_have_no_static_entrypoint():
    index = (STATIC / "index.html").read_text(encoding="utf-8")

    for page in ("pet", "yexuan"):
        assert not (PAGES / f"{page}.html").exists()
        assert f'data-page="{page}"' not in index
        assert f'data-page-fragment="{page}"' not in index
    assert "pet-chat.js" not in index


def test_removed_legacy_pet_api_and_storage_module_have_no_entrypoint():
    from admin.routers.system import router

    route_paths = {route.path for route in router.routes}
    assert not route_paths.intersection({"/pet", "/pet/interact"})
    assert not (Path(__file__).parents[1] / "core" / "pet.py").exists()


def test_page_fragments_are_served_as_static_html():
    from fastapi.testclient import TestClient

    from admin.admin_server import app

    client = TestClient(app)
    for page in ("status", "observe-tools", "observe-resource-completeness"):
        response = client.get(f"/static/pages/{page}.html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


def test_split_pages_have_no_inline_style_or_onclick_and_actions_are_bound():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    html = "\n".join([index, *(path.read_text(encoding="utf-8") for path in PAGES.glob("*.html"))])
    source = read_admin_client_source()
    css = (STATIC / "style.css").read_text(encoding="utf-8")

    assert 'onclick="' not in html
    setup_source = (STATIC / "js" / "setup.js").read_text(encoding="utf-8")
    assert 'onclick="' not in setup_source
    assert 'style="' not in html
    assert "function bindPageActions(scope)" in source
    assert "element.addEventListener('click', _runAction)" in source
    assert "function bindShellActions()" in source

    actions = set(re.findall(r'data-action="([^"]+)"', html))
    assert actions
    for action in actions - {"focus-element"}:
        assert re.search(rf"(?:async )?function {re.escape(action)}\(", source), action

    utility_classes = set(re.findall(r"\b(admin-inline-\d+)\b", html))
    assert utility_classes
    assert all(f".{name}{{" in css for name in utility_classes)
