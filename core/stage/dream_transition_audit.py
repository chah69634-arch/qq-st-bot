"""Safe, append-only observability for Group Dream transitions."""
from __future__ import annotations

import json
import time

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths


def append(group_id: str, *, action: str, result: str, code: str = "", dream_id: str = "", group_status: str = "", solo_status: str = "", conversation_busy: bool = False, transition_busy: bool = False) -> None:
    safe_append_jsonl(get_paths().dream_group_transition_audit(group_id), {
        "ts": time.time(), "group_id": group_id, "action": action, "result": result,
        "code": code, "dream_id": dream_id, "group_status": group_status,
        "solo_status": solo_status, "conversation_busy": bool(conversation_busy), "transition_busy": bool(transition_busy),
    })


def query(group_id: str, limit: int) -> list[dict]:
    path = get_paths().dream_group_transition_audit(group_id)
    if not path.exists(): return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return list(reversed(rows[-limit:]))
