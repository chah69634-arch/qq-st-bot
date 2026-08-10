"""
Token registry — 多 token + scope 存储（SEC-AUTH-2 P1 加载/校验 + P3 管理 API 支持）。
加载 data/runtime/auth/tokens.yaml，按 mtime 热重载（模式抄 core/config_loader.py）。
只存 sha256(token)，不存明文。
"""

import hmac
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from core.sandbox import get_paths
from core.safe_write import safe_write_text
from admin.scopes import expand_scopes

logger = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"^[a-z0-9-]{1,32}$")
RESERVED_LABEL = "legacy-admin"
PLACEHOLDER_ADMIN_SECRET = "YOUR_ADMIN_SECRET"


class TokenLabelError(ValueError):
    """label 非法 / 已存在 / 是保留字 时抛出。"""


@dataclass(frozen=True)
class TokenRecord:
    label: str
    hash: str                  # "sha256:<hex>"
    scopes: frozenset[str]     # profile 已展开
    expires_at: str | None
    disabled: bool
    created_at: str | None = None
    profiles: frozenset[str] = frozenset()


_records: list[TokenRecord] | None = None
_mtime: float | None = None


def hash_token(raw: str) -> str:
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_plaintext() -> str:
    return "emt_" + secrets.token_urlsafe(32)


def _read_raw() -> list[dict]:
    """读取 tokens.yaml 原始条目（scopes 字段未展开，保留 profile:* 记法）。"""
    path = get_paths().auth_tokens_file()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.error(f"[token_registry] tokens.yaml 读取失败，registry 视为空: {e}")
        return []
    return list(data.get("tokens", []) or [])


def _write_raw(entries: list[dict]) -> None:
    path = get_paths().auth_tokens_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        {"tokens": entries}, allow_unicode=True, default_flow_style=False, sort_keys=False,
    )
    safe_write_text(path, content)
    # 强制下次 get_records() 重新读盘，不等 mtime 判定（同一秒内写两次时 mtime 可能不变）。
    global _records, _mtime
    _records = None
    _mtime = None


def _load() -> list[TokenRecord]:
    records: list[TokenRecord] = []
    for entry in _read_raw():
        label = entry.get("label", "?")
        try:
            raw_scopes = list(entry.get("scopes", []) or [])
            records.append(TokenRecord(
                label=entry["label"],
                hash=entry["hash"],
                scopes=expand_scopes(raw_scopes),
                expires_at=entry.get("expires_at"),
                disabled=bool(entry.get("disabled", False)),
                created_at=entry.get("created_at"),
                profiles=frozenset(
                    item[len("profile:"):]
                    for item in raw_scopes
                    if isinstance(item, str) and item.startswith("profile:")
                ),
            ))
        except (KeyError, ValueError) as e:
            logger.error(f"[token_registry] 跳过非法 token 记录 label={label!r}: {e}")
    return records


def get_records() -> list[TokenRecord]:
    """返回当前 registry；tokens.yaml mtime 变化时自动重载。文件不存在时返回空表。"""
    global _records, _mtime
    path = get_paths().auth_tokens_file()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _records is None or mtime != _mtime:
        _records = _load()
        _mtime = mtime
    return _records


def list_records() -> list[TokenRecord]:
    return get_records()


def _is_expired(record: TokenRecord) -> bool:
    if not record.expires_at:
        return False
    try:
        expires = datetime.fromisoformat(record.expires_at)
    except ValueError:
        return False
    now = datetime.now(expires.tzinfo) if expires.tzinfo else datetime.now()
    return now >= expires


def find_by_hash(token_hash: str) -> TokenRecord | None:
    """按 sha256 摘要查表；跳过 disabled / 已过期记录。用 hmac.compare_digest 逐条比对。"""
    for record in get_records():
        if record.disabled or _is_expired(record):
            continue
        if hmac.compare_digest(record.hash, token_hash):
            return record
    return None


# ── 管理操作（P3：admin/routers/auth_tokens.py 调用）────────────────────────────

def _validate_label(label: str, *, allow_reserved: bool = False) -> None:
    if not _LABEL_RE.fullmatch(label or ""):
        raise TokenLabelError(f"非法 label：{label!r}（须匹配 ^[a-z0-9-]{{1,32}}$）")
    if not allow_reserved and label == RESERVED_LABEL:
        raise TokenLabelError(f"label {RESERVED_LABEL!r} 是保留字，不可创建/吊销")


def create_token(label: str, *, scopes: list[str], expires_at: str | None = None) -> str:
    """新建一条 token 记录，返回明文（仅此一次，调用方负责展示后立即丢弃）。"""
    _validate_label(label)
    expand_scopes(scopes)  # 校验 scope/profile 名称合法，展开结果本身不需要
    entries = _read_raw()
    if any(e.get("label") == label for e in entries):
        raise TokenLabelError(f"label {label!r} 已存在")
    raw = _generate_plaintext()
    entries.append({
        "label": label,
        "hash": hash_token(raw),
        "scopes": list(scopes),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "disabled": False,
    })
    _write_raw(entries)
    return raw


def rotate_token(label: str) -> str:
    """给已有 label 换新 token 值，scope 不变，返回新明文（仅此一次）。旧值立即失效。"""
    _validate_label(label, allow_reserved=False)
    entries = _read_raw()
    for entry in entries:
        if entry.get("label") == label:
            raw = _generate_plaintext()
            entry["hash"] = hash_token(raw)
            _write_raw(entries)
            return raw
    raise KeyError(label)


def set_disabled(label: str, disabled: bool) -> bool:
    """启用/停用 token（标记，不删除）。返回是否找到该 label。"""
    _validate_label(label, allow_reserved=False)
    entries = _read_raw()
    found = False
    for entry in entries:
        if entry.get("label") == label:
            entry["disabled"] = disabled
            found = True
            break
    if found:
        _write_raw(entries)
    return found


def delete_token(label: str) -> bool:
    """吊销一条 token（物理删除）。返回是否真的删除了（label 不存在返回 False）。"""
    _validate_label(label, allow_reserved=False)
    entries = _read_raw()
    remaining = [e for e in entries if e.get("label") != label]
    if len(remaining) == len(entries):
        return False
    _write_raw(remaining)
    return True
