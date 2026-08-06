"""Read-only audit for obvious test data left in the runtime memory tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from core.sandbox import get_paths
from core.test_data_guard import classify_test_directories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--archive-known",
        action="store_true",
        help="move only classified test UID directories",
    )
    args = parser.parse_args()

    paths = get_paths()
    memory_root = paths.memory_char_root().parent
    findings = classify_test_directories(memory_root)
    archived: list[dict[str, str]] = []
    if args.archive_known:
        archive_root = paths.test_data_archive_root() / "runtime_memory"
        for finding in findings:
            source = Path(finding["path"])
            target = archive_root / finding["char_id"] / finding["user_id"]
            if not source.is_dir():
                continue
            if target.exists():
                raise RuntimeError(f"archive target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            archived.append({"source": str(source), "target": str(target)})
    payload = {
        "mode": paths.mode,
        "test_session_id": paths.test_session_id,
        "memory_root": str(memory_root),
        "findings": findings,
        "archived": archived,
        "read_only": not args.archive_known,
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
    else:
        print(f"mode={payload['mode']} test_session_id={payload['test_session_id']!r}")
        print(f"memory_root={payload['memory_root']}")
        for finding in findings:
            print(f"test_uid: {finding['char_id']}/{finding['user_id']} -> {finding['path']}")
        action = "archived" if args.archive_known else "read-only"
        print(f"findings={len(findings)} ({action})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
