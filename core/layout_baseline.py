"""Small v1 data-layout baseline marker.

This is intentionally an installation marker, not a migration framework.  It
only records the first successful v1 initialization and rejects a marker the
current program cannot understand.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.safe_write import safe_write_json
from core.sandbox import get_paths


PRODUCT_BASELINE = "v1"
DATA_LAYOUT_SCHEMA_VERSION = 1
FIRST_V1_VERSION = "v1.0.0"


class LayoutBaselineError(RuntimeError):
    """The on-disk layout marker is missing required v1 compatibility data."""


def _first_initialized_version(installation_root: Path) -> str:
    version_file = installation_root / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    return value if value.startswith("v1") else FIRST_V1_VERSION


def _validate_marker(payload: object) -> None:
    if not isinstance(payload, dict):
        raise LayoutBaselineError("data/layout_version.json 格式无效，无法确认 v1 数据布局。")
    if payload.get("product_baseline") != PRODUCT_BASELINE:
        raise LayoutBaselineError("data/layout_version.json 不是受支持的 v1 baseline。")
    if payload.get("data_layout_schema_version") != DATA_LAYOUT_SCHEMA_VERSION:
        raise LayoutBaselineError("data/layout_version.json 的 schema 高于或不兼容当前程序。")
    if not isinstance(payload.get("first_initialized_version"), str) or not payload["first_initialized_version"]:
        raise LayoutBaselineError("data/layout_version.json 缺少 first_initialized_version。")


def ensure_v1_layout_baseline(*, installation_root: Path | None = None) -> bool:
    """Create the v1 marker once after normal startup initialization.

    Returns ``True`` only when this call creates a fresh marker. Existing
    markers are validated and never rewritten, preserving the first v1 version
    that initialized this data directory.
    """
    paths = get_paths()
    marker = paths.layout_version()
    if marker.is_file():
        try:
            _validate_marker(json.loads(marker.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LayoutBaselineError("无法读取 data/layout_version.json，已停止启动以保护数据。") from exc
        return False

    root = Path.cwd() if installation_root is None else Path(installation_root)
    payload = {
        "product_baseline": PRODUCT_BASELINE,
        "data_layout_schema_version": DATA_LAYOUT_SCHEMA_VERSION,
        "first_initialized_version": _first_initialized_version(root),
    }
    if not safe_write_json(marker, payload, keep_bak=False):
        raise LayoutBaselineError("无法创建 data/layout_version.json，已停止启动以保护数据。")
    return True
