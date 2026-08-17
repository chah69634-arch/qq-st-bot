#!/usr/bin/env python3
"""Dry-run-first, resumable import of legacy Markdown Memory Events."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from core.backup_state import BackupError, create_snapshot, verify_snapshot
from core.memory.event_migration import apply_batch, scan_legacy
from core.memory.scope import MemoryScope


def _backup(output: Path) -> dict[str, object]:
    created = create_snapshot(ROOT, output, protection_mode="protected_volume")
    verified = verify_snapshot(output)
    if not verified.get("ok"):
        raise BackupError("backup_verify_failed", "migration backup verification failed")
    manifest_checksum = (output / "manifest.sha256").read_text(encoding="ascii").strip()
    if len(manifest_checksum) != 64:
        raise BackupError("backup_verify_failed", "migration backup checksum is invalid")
    return {
        "backup_id": created["backup_id"],
        "file_count": created["file_count"],
        "verified": True,
        "manifest_sha256": manifest_checksum,
        "protection_mode": created["protection_mode"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", required=True)
    parser.add_argument("--char-id", required=True)
    parser.add_argument("--apply", action="store_true", help="append one batch after a verified offline backup")
    parser.add_argument("--backup-output", type=Path, help="new protected-volume snapshot directory; required with --apply")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    scope = MemoryScope.reality_scope(args.uid, args.char_id)
    plan = scan_legacy(scope)
    report = {key: value for key, value in plan.items() if key != "entries"}
    if not args.apply:
        report["mode"] = "dry_run"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.backup_output is None:
        parser.error("--apply requires --backup-output")
    try:
        backup = _backup(args.backup_output)
        report = apply_batch(scope, plan, batch_size=args.batch_size, backup=backup)
        report["mode"] = "apply"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (BackupError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": getattr(exc, "code", type(exc).__name__)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
