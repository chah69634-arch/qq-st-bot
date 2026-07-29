#!/usr/bin/env python3
"""Update an unpacked PresenceKit release package without replacing user data.

The batch entry point deliberately stays tiny: a running ``.bat`` cannot safely
replace itself.  This program downloads and verifies an entire release before it
touches the installed program files, and it never overwrites private state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


RELEASES_URL = "https://api.github.com/repos/cicikat/PresenceKit/releases?per_page=100"
ASSET_RE = re.compile(r"^PresenceKit-(.+)-win64-setup\.zip$")
PROTECTED_ROOTS = frozenset({"data", "userdata", ".venv", "_presencekit_upgrade"})
PROTECTED_FILES = frozenset({"config.yaml", "config.local.yaml", "secrets.local.yaml"})
PROTECTED_PATHS = frozenset({PurePosixPath("tools/uv.exe")})

# This is intentionally a single, release-specific bridge rather than a
# general migration framework.  v0.2.2 is the only pre-v1 installation layout
# that the public updater accepts directly.
V0_2_2_VERSION = "v0.2.2"
V1_0_0_VERSION = "v1.0.0"
V0_2_2_TO_V1_MARKER = PurePosixPath("_presencekit_upgrade/v0.2.2_to_v1_bridge_completed")

# C1.4 only removes these former release-owned files.  It never recursively
# removes a legacy root: an old installation may contain unknown private files.
SUPERSEDED_PUBLIC_ASSETS = frozenset({
    PurePosixPath("characters/default.json"),
    PurePosixPath("characters/default_author_notes.json"),
    *(PurePosixPath(f"characters/dream_postcards/templates/{name}.md") for name in (
        "diary_fragment", "note", "postcard", "sms", "untitled",
    )),
    *(PurePosixPath(f"content/characters/default/{name}.yaml") for name in ("activity_pool", "traits")),
    *(PurePosixPath(f"defaults/{name}") for name in (
        "blacklist.yaml", "jailbreak_entries.json", "lorebook.yaml", "relations.yaml",
    )),
    *(PurePosixPath(f"defaults/dream_worlds/_default/{name}") for name in (
        "lorebook.yaml", "mes_example.md", "ruleset.md", "vocab.json",
    )),
    PurePosixPath("examples/character_template.json"),
    *(PurePosixPath(f"examples/{name}") for name in (
        "activity_pool.example.yaml", "assistant.example.json", "benwo.example.json",
        "jailbreak_preset.example.json", "traits.example.yaml",
    )),
})


class UpdateError(RuntimeError):
    """A user-actionable update failure; the current installation is retained."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_protected_relative_path(path: Path) -> bool:
    """Return whether a release path must never overwrite a local installation path."""
    normalized = PurePosixPath(*(part.lower() for part in path.parts))
    if not normalized.parts:
        return False
    if normalized.parts[0].lower() in PROTECTED_ROOTS:
        return True
    if len(normalized.parts) == 1 and normalized.name.lower() in PROTECTED_FILES:
        return True
    return normalized in PROTECTED_PATHS


def current_version(root: Path) -> str:
    marker = root / "VERSION"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value
    return "未知旧版"


def _version_key(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", value.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _version_at_least(value: str, floor: str) -> bool:
    value_key, floor_key = _version_key(value), _version_key(floor)
    if value_key is None or floor_key is None:
        return False
    width = max(len(value_key), len(floor_key))
    return value_key + (0,) * (width - len(value_key)) >= floor_key + (0,) * (width - len(floor_key))


def bridge_marker_path(root: Path) -> Path:
    return root.joinpath(*V0_2_2_TO_V1_MARKER.parts)


def _backup_path(root: Path, version: str) -> Path:
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", version) or "unknown"
    return root / f"_update_backup_{safe_version}"


def _backup_is_v0_2_2(root: Path) -> bool:
    backup_version = current_version(_backup_path(root, V0_2_2_VERSION))
    return backup_version == V0_2_2_VERSION


def select_update_mode(installation: Path, source_version: str, target_version: str) -> str:
    """Select the sole supported pre-v1 bridge or a normal v1 forward update."""
    if source_version == V0_2_2_VERSION:
        if target_version != V1_0_0_VERSION:
            raise UpdateError(
                "v0.2.2 只支持直接升级到 v1.0.0；请下载 v1.0.0 release，"
                "或先完成该升级后再继续 v1 forward update。"
            )
        return "v0.2.2_to_v1"

    # A failed bridge has already copied the v1 program files, but deliberately
    # has no completion marker.  Its full v0.2.2 backup is the only retry
    # signal; it is not a version-agnostic migration registry.
    if (
        _version_at_least(source_version, V1_0_0_VERSION)
        and target_version == V1_0_0_VERSION
        and not bridge_marker_path(installation).is_file()
        and _backup_is_v0_2_2(installation)
    ):
        return "v0.2.2_to_v1_retry"

    if (
        _version_at_least(source_version, V1_0_0_VERSION)
        and target_version == V1_0_0_VERSION
        and bridge_marker_path(installation).is_file()
        and _backup_is_v0_2_2(installation)
    ):
        return "v0.2.2_to_v1_repeat"

    if not _version_at_least(source_version, V1_0_0_VERSION):
        raise UpdateError(
            "无法识别为受支持的升级来源。仅支持 v0.2.2 直接升级到 v1.0.0；"
            "更早版本请先升级到 v0.2.2，或从人工备份恢复。"
        )
    if not _version_at_least(target_version, V1_0_0_VERSION):
        raise UpdateError("v1 不支持 downgrade；请从升级前备份人工恢复。")
    if is_downgrade(source_version, target_version):
        raise UpdateError("v1 不支持 downgrade；请从升级前备份人工恢复。")
    return "v1_forward"


def _read_proxy_config(root: Path) -> dict[str, str]:
    """Read the same proxy fields managed by the admin /proxy control surface."""
    config = root / "config.yaml"
    if not config.is_file():
        return {}
    try:
        import yaml  # Present in a normally installed release virtualenv.

        parsed = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        proxy = parsed.get("proxy", {})
        if not isinstance(proxy, dict) or not proxy.get("enabled", False):
            return {}
        result = {}
        for scheme, key in (("http", "http"), ("https", "https")):
            value = str(proxy.get(key, "")).strip()
            if value:
                result[scheme] = value
        return result
    except Exception as exc:
        print(f"[update] 无法读取代理配置，将直连下载：{exc}")
        return {}


def _opener(root: Path) -> urllib.request.OpenerDirector:
    proxies = _read_proxy_config(root)
    # Do not let an unrelated shell HTTP_PROXY setting quietly change the update
    # route.  The admin-controlled config is the source of truth.
    return urllib.request.build_opener(urllib.request.ProxyHandler(proxies))


def download(url: str, destination: Path, opener: urllib.request.OpenerDirector) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with opener.open(request, timeout=45) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (urllib.error.URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{url}\n{exc}") from exc
    os.replace(temporary, destination)


def fetch_releases(root: Path) -> list[dict[str, Any]]:
    opener = _opener(root)
    temporary = root / "_update_releases.json"
    try:
        download(RELEASES_URL, temporary, opener)
        payload = json.loads(temporary.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UpdateError) as exc:
        raise UpdateError(
            "无法从 GitHub 获取版本列表。请检查网络或 config.yaml 的代理设置；"
            "也可以手动下载 release zip 后只覆盖程序文件。\n" + str(exc)
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    if not isinstance(payload, list):
        raise UpdateError("GitHub 返回的版本列表格式无效，未修改当前安装。")
    return [release for release in payload if isinstance(release, dict) and not release.get("draft")]


def parse_release_choice(value: str, releases: list[dict[str, Any]]) -> int:
    choice = value.strip()
    if not choice:
        return 0
    try:
        index = int(choice) - 1
    except ValueError as exc:
        raise UpdateError("请输入版本前的数字，或直接回车选择最新版。") from exc
    if not 0 <= index < len(releases):
        raise UpdateError("版本编号超出范围。")
    return index


def _release_assets(release: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError(f"{release.get('tag_name', '所选版本')} 没有可下载资产。")
    zip_asset = next((asset for asset in assets if isinstance(asset, dict) and ASSET_RE.match(str(asset.get("name", "")))), None)
    if zip_asset is None:
        raise UpdateError("所选版本没有 PresenceKit Windows 安装 zip。")
    checksum_name = f"{zip_asset['name']}.sha256"
    checksum_asset = next((asset for asset in assets if isinstance(asset, dict) and asset.get("name") == checksum_name), None)
    if checksum_asset is None:
        raise UpdateError(f"所选版本缺少校验文件 {checksum_name}，为安全起见不会更新。")
    return zip_asset, checksum_asset


def verify_sha256(archive: Path, checksum_file: Path) -> None:
    match = re.search(r"\b([a-fA-F0-9]{64})\b", checksum_file.read_text(encoding="utf-8-sig", errors="replace"))
    if not match:
        raise UpdateError("SHA256 校验文件格式无效，未修改当前安装。")
    actual = sha256_file(archive)
    if actual.lower() != match.group(1).lower():
        raise UpdateError("SHA256 校验失败，下载文件可能不完整或被篡改；未修改当前安装。")


def extract_release(archive: Path, destination: Path) -> Path:
    try:
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                relative = PurePosixPath(entry.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise UpdateError("发行包包含不安全路径，未修改当前安装。")
            package.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise UpdateError("下载的 release zip 无法解压，未修改当前安装。") from exc

    # Current packages are flat.  Accept one enclosing directory as a future
    # packaging-compatible layout, but reject arbitrary/missing payloads.
    children = [child for child in destination.iterdir() if child.name not in {"__MACOSX"}]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    if not (destination / "scripts" / "update_release.py").is_file():
        raise UpdateError("发行包缺少更新器，未修改当前安装。")
    return destination


def _copy_program_files(source: Path, installation: Path, backup: Path) -> list[tuple[Path, bool]]:
    replaced: list[tuple[Path, bool]] = []
    try:
        for candidate in sorted(source.rglob("*")):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(source)
            if is_protected_relative_path(relative):
                continue
            target = installation / relative
            had_original = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            # copy2 writes the fully staged file to a temporary sibling and swaps it
            # in, so interruption cannot leave a partially written program file.
            temporary = target.with_suffix(target.suffix + ".update-new")
            try:
                shutil.copy2(candidate, temporary)
                os.replace(temporary, target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            replaced.append((target, had_original))
    except Exception:
        # Keep this local list available for a mid-copy failure.  Returning a
        # list only on success would otherwise lose the already replaced paths.
        _rollback_program_files(installation, backup, replaced)
        raise
    return replaced


def _rollback_program_files(installation: Path, backup: Path, replaced: list[tuple[Path, bool]]) -> None:
    for target, had_original in reversed(replaced):
        relative = target.relative_to(installation)
        if had_original:
            original = backup / relative
            if original.exists():
                temporary = target.with_suffix(target.suffix + ".update-rollback")
                shutil.copy2(original, temporary)
                os.replace(temporary, target)
        elif target.exists():
            target.unlink()


def _cleanup_superseded_public_assets(
    source: Path, installation: Path, backup: Path, replaced: list[tuple[Path, bool]],
) -> None:
    """Remove only known old public files after a bundled-root update.

    Empty directories are removed opportunistically with ``rmdir``; a private
    or ignored file makes that operation a no-op, so unknown legacy assets are
    never deleted or traversed recursively.
    """
    if not (source / "bundled").is_dir():
        return
    parent_dirs: set[Path] = set()
    for relative in SUPERSEDED_PUBLIC_ASSETS:
        target = installation.joinpath(*relative.parts)
        if not target.is_file():
            continue
        target.unlink()
        replaced.append((target, True))
        for parent in target.parents:
            try:
                parent.relative_to(installation)
            except ValueError:
                break
            parent_dirs.add(parent)
    for directory in sorted(parent_dirs, key=lambda item: len(item.parts), reverse=True):
        if directory == installation:
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def _prune_old_backups(root: Path, keep: Path) -> None:
    for candidate in root.glob("_update_backup_*"):
        if candidate != keep and candidate.is_dir():
            shutil.rmtree(candidate)


def _create_installation_backup(installation: Path, backup: Path) -> None:
    """Create a complete pre-update snapshot before changing any installation file."""
    try:
        backup.mkdir(parents=True)
        for candidate in sorted(installation.rglob("*")):
            relative = candidate.relative_to(installation)
            # A backup lives under the installation.  Never recursively copy it,
            # previous backups, or the verified release staging area into itself.
            if relative.parts and (
                relative.parts[0].startswith("_update_backup_") or relative.parts[0] == "_update_tmp"
            ):
                continue
            destination = backup / relative
            if candidate.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif candidate.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, destination)
    except Exception as exc:
        shutil.rmtree(backup, ignore_errors=True)
        raise UpdateError(f"升级前备份失败，当前安装未开始更新：{exc}") from exc


def apply_release(
    installation: Path, source: Path, old_version: str, *, reuse_existing_backup: bool = False,
    backup_version: str | None = None,
) -> Path:
    """Overlay verified program files and retain one restorable pre-update backup."""
    backup = _backup_path(installation, backup_version or old_version)
    if not reuse_existing_backup:
        if backup.exists():
            shutil.rmtree(backup)
        _create_installation_backup(installation, backup)
    elif not backup.is_dir():
        raise UpdateError("未找到可供 bridge 重试的 v0.2.2 升级前备份。")
    replaced: list[tuple[Path, bool]] = []
    try:
        replaced = _copy_program_files(source, installation, backup)
        _cleanup_superseded_public_assets(source, installation, backup, replaced)
    except Exception as exc:
        _rollback_program_files(installation, backup, replaced)
        raise UpdateError(f"程序文件复制失败，已恢复本次已替换的程序文件：{exc}") from exc
    _prune_old_backups(installation, backup)
    return backup


def run_existing_v1_migration_bootstrap(installation: Path) -> None:
    """Run the existing read-compatibility bootstrap without starting the service.

    v1 has no release-wide data rewrite to execute here: `core.migration.for_read`
    is the existing compatibility layer and runtime bootstraps remain normal
    startup responsibilities.  The bridge verifies that this released layout can
    resolve the v1 bundled default before its completion marker is written.
    """
    bundled_card = installation / "bundled" / "characters" / "default" / "card.json"
    legacy_card = installation / "characters" / "default.json"
    if not bundled_card.is_file():
        raise UpdateError("v1 release 缺少 bundled 默认资产，bridge 未完成。")
    from core.migration import for_read

    if for_read(bundled_card, legacy_card) != bundled_card:
        raise UpdateError("v1 bundled 默认资产无法通过既有兼容读取校验，bridge 未完成。")


def _write_bridge_marker(installation: Path) -> None:
    marker = bridge_marker_path(installation)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".new")
    temporary.write_text("v0.2.2_to_v1_bridge_completed\n", encoding="utf-8")
    os.replace(temporary, marker)


def run_v0_2_2_to_v1_bridge(installation: Path) -> None:
    """Complete the single supported v0.2.2-to-v1 bridge, once and idempotently."""
    if bridge_marker_path(installation).is_file():
        return
    if not (installation / "bundled").is_dir():
        raise UpdateError("v1 release 未提供 bundled/，bridge 未完成。")
    run_existing_v1_migration_bootstrap(installation)
    _write_bridge_marker(installation)


def restore_installation_from_backup(installation: Path, backup: Path) -> None:
    """Explicitly restore a complete pre-update backup; this is the downgrade path."""
    resolved_installation = installation.resolve()
    resolved_backup = backup.resolve()
    try:
        relative_backup = resolved_backup.relative_to(resolved_installation)
    except ValueError as exc:
        raise UpdateError("恢复备份必须位于当前安装目录内。") from exc
    if not relative_backup.parts or not relative_backup.parts[0].startswith("_update_backup_"):
        raise UpdateError("恢复目标不是 updater 创建的升级前备份。")
    if not resolved_backup.is_dir():
        raise UpdateError("指定的升级前备份不存在。")

    for candidate in sorted(resolved_installation.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = candidate.relative_to(resolved_installation)
        if relative.parts and relative.parts[0].startswith("_update_backup_"):
            continue
        if relative.parts and relative.parts[0] == "_update_tmp":
            continue
        if candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            try:
                candidate.rmdir()
            except OSError:
                pass
    for candidate in sorted(resolved_backup.rglob("*")):
        relative = candidate.relative_to(resolved_backup)
        destination = resolved_installation / relative
        if candidate.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif candidate.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination)


def _service_is_running() -> bool:
    try:
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='pythonw.exe'", "get", "CommandLine"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return "main.py" in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        # A missing legacy WMIC should not make an update unsafe by pretending
        # success.  The batch entry performs the same check before Python starts.
        return False


def is_downgrade(current: str, target: str) -> bool:
    current_key, target_key = _version_key(current), _version_key(target)
    if current_key is None or target_key is None:
        return False
    width = max(len(current_key), len(target_key))
    return target_key + (0,) * (width - len(target_key)) < current_key + (0,) * (width - len(current_key))


def sync_dependencies(root: Path) -> None:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise UpdateError("未找到 .venv；请先运行 AA1安装并启动.bat 完成首次安装。")
    bundled_uv = root / "tools" / "uv.exe"
    if bundled_uv.is_file():
        command = [str(bundled_uv), "pip", "sync", "requirements.lock", "--python", str(python)]
    else:
        command = [str(python), "-m", "pip", "install", "-r", "requirements.lock"]
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode:
        raise UpdateError("依赖同步失败；程序文件已更新但没有回滚，请检查网络或终端错误后重试。")


def choose_release(releases: list[dict[str, Any]], noninteractive: bool) -> dict[str, Any]:
    if not releases:
        raise UpdateError("GitHub 上没有可用 release。")
    print("可选版本（默认最新）：")
    for index, release in enumerate(releases, 1):
        suffix = "（预发布）" if release.get("prerelease") else ""
        print(f"  {index}. {release.get('tag_name', '未命名版本')}{suffix}")
    choice = "" if noninteractive else input("请选择版本编号（直接回车=最新）: ")
    return releases[parse_release_choice(choice, releases)]


def update(root: Path, args: argparse.Namespace) -> None:
    if _service_is_running():
        raise UpdateError("检测到 PresenceKit 服务仍在运行。请先停止服务后再更新。")
    old = current_version(root)
    stage = root / "_update_tmp"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    if args.source_zip:
        archive = Path(args.source_zip).resolve()
        checksum = Path(args.sha256_file).resolve() if args.sha256_file else archive.with_suffix(archive.suffix + ".sha256")
        target = args.target_version or "本地测试包"
        if not archive.is_file() or not checksum.is_file():
            raise UpdateError("本地测试包或其 .sha256 文件不存在。")
    else:
        release = choose_release(fetch_releases(root), args.yes)
        target = str(release.get("tag_name") or "所选版本")
        zip_asset, checksum_asset = _release_assets(release)
        archive = stage / str(zip_asset["name"])
        checksum = stage / str(checksum_asset["name"])
        opener = _opener(root)
        print(f"当前版本：{old} → 目标版本：{target}")
        download(str(zip_asset["browser_download_url"]), archive, opener)
        download(str(checksum_asset["browser_download_url"]), checksum, opener)

    verify_sha256(archive, checksum)
    source = extract_release(archive, stage / "package")
    mode = select_update_mode(root, old, target)
    backup = apply_release(
        root,
        source,
        old,
        reuse_existing_backup=mode in {"v0.2.2_to_v1_retry", "v0.2.2_to_v1_repeat"},
        backup_version=V0_2_2_VERSION if mode in {"v0.2.2_to_v1_retry", "v0.2.2_to_v1_repeat"} else None,
    )
    if mode.startswith("v0.2.2_to_v1"):
        # Do this after program files are in place.  If it fails, the marker is
        # absent and the preserved v0.2.2 snapshot makes a later retry explicit.
        run_v0_2_2_to_v1_bridge(root)
    if not args.skip_sync:
        sync_dependencies(root)
    shutil.rmtree(stage)
    print(f"更新完成：{old} → {current_version(root)}")
    print(f"已备份被替换的程序文件：{backup.name}（只保留最近一份）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="非交互模式：选择最新版本并确认降级")
    parser.add_argument("--source-zip", help="本地 release zip（仅用于离线演练）")
    parser.add_argument("--sha256-file", help="本地 release zip 的 .sha256 文件")
    parser.add_argument("--target-version", help="离线演练显示的目标版本")
    parser.add_argument("--skip-sync", action="store_true", help="跳过依赖同步（仅用于离线演练）")
    parser.add_argument("--restore-backup", help="显式从 updater 创建的升级前备份恢复；这是 downgrade/失败后的人工路线")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        if args.restore_backup:
            if _service_is_running():
                raise UpdateError("检测到 PresenceKit 服务仍在运行。请先停止服务后再恢复备份。")
            restore_installation_from_backup(root, Path(args.restore_backup))
            print(f"已从升级前备份恢复：{args.restore_backup}")
        else:
            update(root, args)
    except UpdateError as exc:
        print(f"[update] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
