from pathlib import Path

import pytest

from tests.identity_eval import engine


def _production_data_entries(root: Path) -> set[Path]:
    return {
        path
        for path in root.rglob("*")
        if path.relative_to(root).parts[:1] != ("test_sandbox",)
    }


@pytest.fixture
def identity_case_env(tmp_path, monkeypatch, sandbox):
    """Install eval-only character cards in this worker's private cwd."""
    monkeypatch.chdir(tmp_path)
    repo_root = Path(__file__).parents[2]
    import core.config_loader as config_loader
    import core.data_paths as data_paths

    monkeypatch.setattr(config_loader, "_CONFIG_PATH", repo_root / "config.yaml")
    monkeypatch.setattr(config_loader, "_config", None)
    monkeypatch.setattr(config_loader, "_config_mtime", None)
    monkeypatch.setattr(data_paths.DataPaths, "bundled_root", lambda _self: repo_root / "bundled")
    primary = engine.new_test_char_id()
    alternate = engine.new_test_char_id()
    engine.install_test_character(primary)
    engine.install_test_character(alternate)
    try:
        yield {"primary": primary, "alternate": alternate}
    finally:
        engine.remove_test_character(primary)
        engine.remove_test_character(alternate)


@pytest.fixture(autouse=True)
def _production_data_untouched():
    root = Path(__file__).parent.parent.parent / "data"
    before = _production_data_entries(root) if root.exists() else set()
    yield
    after = _production_data_entries(root) if root.exists() else set()
    assert not after - before, f"identity eval polluted production data: {after - before}"
