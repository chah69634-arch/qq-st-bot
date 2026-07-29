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
PROTECTED_ROOTS = frozenset({"data", "userdata", ".venv"})
PROTECTED_FILES = frozenset({"config.yaml", "secrets.local.yaml"})
PROTECTED_PATHS = frozenset({PurePosixPath("tools/uv.exe")})

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
    for candidate in sorted(source.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(source)
        if is_protected_relative_path(relative):
            continue
        target = installation / relative
        backup_target = backup / relative
        had_original = target.exists()
        if had_original:
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # copy2 writes the fully staged file to a temporary sibling and swaps it
        # in, so interruption cannot leave a partially written program file.
        temporary = target.with_suffix(target.suffix + ".update-new")
        shutil.copy2(candidate, temporary)
        os.replace(temporary, target)
        replaced.append((target, had_original))
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
        backup_target = backup.joinpath(*relative.parts)
        backup_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_target)
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


def apply_release(installation: Path, source: Path, old_version: str) -> Path:
    """Overlay verified program files and retain one restorable pre-update backup."""
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", old_version) or "unknown"
    backup = installation / f"_update_backup_{safe_version}"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    replaced: list[tuple[Path, bool]] = []
    try:
        replaced = _copy_program_files(source, installation, backup)
        _cleanup_superseded_public_assets(source, installation, backup, replaced)
    except Exception:
        _rollback_program_files(installation, backup, replaced)
        raise
    _prune_old_backups(installation, backup)
    return backup


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


def _version_key(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", value.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


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

    if is_downgrade(old, target) and not args.yes:
        confirm = input("目标版本低于当前版本，data 格式可能不兼容。输入 Y 确认降级: ")
        if confirm.strip().upper() != "Y":
            print("已取消，当前安装未修改。")
            return

    verify_sha256(archive, checksum)
    source = extract_release(archive, stage / "package")
    backup = apply_release(root, source, old)
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
    args = parser.parse_args()
    root = Path.cwd().resolve()
    try:
        update(root, args)
    except UpdateError as exc:
        print(f"[update] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
