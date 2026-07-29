"""Deterministic resource-level read resolution for authored user/legacy roots.

Writers deliberately do not use this module: canonical writer targets remain
owned by ``DataPaths``.  These helpers only merge discovery and resolve an
effective read path without ever copying, moving, or modifying assets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

logger = logging.getLogger(__name__)

Source = Literal["user", "legacy"]


@dataclass(frozen=True)
class LayeredAsset:
    logical_id: str
    path: Path
    source: Source
    shadowed_source: Source | None = None


def _iter_files(root: Path | None, *, suffixes: Iterable[str] | None, recursive: bool) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    suffix_set = {suffix.lower() for suffix in suffixes} if suffixes is not None else None
    iterator = root.rglob("*") if recursive else root.glob("*")
    return sorted(
        (path for path in iterator if path.is_file() and (suffix_set is None or path.suffix.lower() in suffix_set)),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def _observe(logical_asset: str, item: LayeredAsset) -> None:
    if item.source == "legacy" or item.shadowed_source is not None:
        fields = [
            f"logical_asset={logical_asset}",
            f"logical_id={item.logical_id}",
            f"effective_read_source={item.source}",
        ]
        if item.shadowed_source is not None:
            fields.append(f"shadowed_source={item.shadowed_source}")
        logger.info("[authored-resolver] %s", " ".join(fields))


def resolve_layered_files(
    user_dir: Path | None,
    legacy_dir: Path | None,
    *,
    logical_asset: str,
    suffixes: Iterable[str] | None = None,
    recursive: bool = False,
    logical_id: Callable[[Path], str] | None = None,
) -> list[LayeredAsset]:
    """Merge files from both roots; user wins only the same logical resource."""
    records: dict[str, LayeredAsset] = {}
    for source, root in (("legacy", legacy_dir), ("user", user_dir)):
        if root is None:
            continue
        for path in _iter_files(root, suffixes=suffixes, recursive=recursive):
            relative = path.relative_to(root)
            asset_id = logical_id(relative) if logical_id else relative.as_posix()
            previous = records.get(asset_id)
            records[asset_id] = LayeredAsset(
                logical_id=asset_id,
                path=path,
                source=source,  # type: ignore[arg-type]
                shadowed_source=previous.source if previous is not None else None,
            )
    result = sorted(records.values(), key=lambda item: (item.logical_id.casefold(), item.logical_id))
    for item in result:
        _observe(logical_asset, item)
    return result


def resolve_layered_directories(
    user_dir: Path | None,
    legacy_dir: Path | None,
    *,
    logical_asset: str,
    include: Callable[[Path], bool] | None = None,
) -> list[LayeredAsset]:
    """Merge immediate package directories; a selected package is never mixed."""
    records: dict[str, LayeredAsset] = {}
    for source, root in (("legacy", legacy_dir), ("user", user_dir)):
        if root is None or not root.is_dir():
            continue
        for path in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: (p.name.casefold(), p.name)):
            if include is not None and not include(path):
                continue
            previous = records.get(path.name)
            records[path.name] = LayeredAsset(
                logical_id=path.name,
                path=path,
                source=source,  # type: ignore[arg-type]
                shadowed_source=previous.source if previous is not None else None,
            )
    result = sorted(records.values(), key=lambda item: (item.logical_id.casefold(), item.logical_id))
    for item in result:
        _observe(logical_asset, item)
    return result


def resolve_layered_file(
    user_dir: Path | None,
    legacy_dir: Path | None,
    filename: str,
    *,
    logical_asset: str,
) -> LayeredAsset | None:
    """Resolve one relative file without allowing an empty user root to shadow legacy."""
    for item in resolve_layered_files(
        user_dir,
        legacy_dir,
        logical_asset=logical_asset,
        recursive=False,
    ):
        if item.logical_id == filename:
            return item
    return None
