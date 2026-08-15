"""
tests/memeval/conftest.py — memeval 专用 fixture

复用 tests/conftest.py 的 sandbox 隔离，并将当前工作目录切到 ``tmp_path``。
这样 asset registry 只会扫描临时 ``userdata/``，不会在仓库根 ``characters/``
写任何 generated fixture。
"""

from pathlib import Path
import time

import pytest

from tests.memeval import engine


def _production_data_entries(root: Path) -> set[Path]:
    """Snapshot production data without xdist's shared test-only namespace."""
    return {
        path
        for path in root.rglob("*")
        if path.relative_to(root).parts[:1] != ("test_sandbox",)
    }


def _stable_production_data_entries(root: Path, before: set[Path]) -> set[Path]:
    """Allow an in-flight atomic-write temp file to finish before asserting.

    xdist can finish a neighboring worker's test while this teardown is
    running.  A ``*.json.tmp`` is only an intermediate safe-write artifact;
    persistent files still fail immediately, and a temp artifact that does not
    disappear within the short grace window remains a real pollution failure.
    """
    after = _production_data_entries(root)
    for _ in range(10):
        new_files = after - before
        if not new_files or any(path.suffix != ".tmp" for path in new_files):
            return after
        time.sleep(0.05)
        after = _production_data_entries(root)
    return after


@pytest.fixture
def case_env(tmp_path, monkeypatch, sandbox):
    """在临时 userdata 下铺一次性角色卡（并发 worker 不共享文件名）。

    产出 char_id 字符串，供 engine.run_case(..., char_id=case_env) 使用。
    """
    monkeypatch.chdir(tmp_path)
    # config_loader deliberately resolves config.yaml from cwd.  Keep that
    # read-only dependency pointed at the repository configuration while all
    # generated authored files stay inside tmp_path.
    import core.config_loader as config_loader
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", Path(__file__).parents[2] / "config.yaml")
    monkeypatch.setattr(config_loader, "_config", None)
    monkeypatch.setattr(config_loader, "_config_mtime", None)
    import core.data_paths as data_paths
    repo_root = Path(__file__).parents[2]
    monkeypatch.setattr(data_paths.DataPaths, "bundled_root", lambda _self: repo_root / "bundled")
    char_id = engine.new_test_char_id()
    engine.install_test_character(char_id)
    try:
        yield char_id
    finally:
        engine.remove_test_character(char_id)


@pytest.fixture(autouse=True)
def _production_data_untouched():
    """Brief 44 §5：跑完 memeval 后生产 data/ 目录不得出现任何新文件。

    sandbox fixture 已把 DataPaths._base 重定向到 tmp_path，这里是防御性复核——
    万一某个调用路径绕过了 DataPaths 直接拼裸路径，这个断言能第一时间抓到。
    ``data/test_sandbox`` 是其他 xdist worker 的测试隔离区，不属于生产 runtime，
    不能作为本用例的跨 worker 污染证据。
    """
    root = Path(__file__).parent.parent.parent / "data"
    before = _production_data_entries(root) if root.exists() else set()
    yield
    after = _stable_production_data_entries(root, before) if root.exists() else set()
    new_files = after - before
    assert not new_files, f"memeval 用例污染了生产 data/ 目录，新增文件：{new_files}"
