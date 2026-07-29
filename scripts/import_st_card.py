"""
SillyTavern 角色卡 → Presence 格式转换器

用法:
    python scripts/import_st_card.py <酒馆卡.json> [--out userdata/characters/cards/<id>.json] [--id <id>]
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，以便引用 core/safe_write
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from core.safe_write import safe_write_text  # noqa: E402


# ─── 位置判断 ────────────────────────────────────────────────────────────────

def _classify_position(entry: dict) -> str:
    """
    返回 "before" 或 "after"，用于决定常驻条目去哪。

    ST 位置体系：
        position 字段 (str): "before_char" → before, "after_char" / "chat" → after
        extensions.position (int): 0 → before, 1/2/3/4 → after
    不确定时默认 "before"（折进 description，保守且不丢内容）。
    """
    pos_str: str = entry.get("position", "")
    ext_pos = entry.get("extensions", {}).get("position", None)

    if pos_str:
        pos_lower = pos_str.lower()
        if "before" in pos_lower:
            return "before"
        if "after" in pos_lower or "chat" in pos_lower:
            return "after"

    if ext_pos is not None:
        try:
            p = int(ext_pos)
        except (TypeError, ValueError):
            p = -1
        if p == 0:
            return "before"
        if p in (1, 2, 3, 4):
            return "after"

    return "before"


# ─── 主转换逻辑 ──────────────────────────────────────────────────────────────

def convert(src_path: Path, out_path: Path, char_id: str) -> dict:
    """
    读取酒馆卡，转换为 Presence 格式，写入 out_path。
    返回转换报告 dict（供打印）。
    """
    raw = json.loads(src_path.read_text(encoding="utf-8-sig"))

    # ── spec 检测 ──
    spec = raw.get("spec", "")
    supported = {"chara_card_v2", "chara_card_v3"}
    if spec.lower() not in supported:
        print(
            f"[WARNING] spec='{spec}' 不是 chara_card_v2/v3，将按扁平格式处理。",
            file=sys.stderr,
        )

    # ── 真实数据层：V2/V3 数据在 data.* 内 ──
    inner = raw.get("data") or {}
    def get(key: str, default=None):
        """优先 data 层，回落顶层。"""
        v = inner.get(key)
        if v is None:
            v = raw.get(key)
        return v if v is not None else default

    # ── 直接平移字段 ──
    name        = get("name", char_id)
    description = get("description", "")
    personality = get("personality", "")
    scenario    = get("scenario", "")
    first_mes   = get("first_mes", "")
    mes_example = get("mes_example", "")
    system_prompt = get("system_prompt", "")

    # 确保 description 是 str（有的卡给 list）
    if isinstance(description, list):
        description = "".join(description)
    if isinstance(personality, list):
        personality = "".join(personality)
    if isinstance(scenario, list):
        scenario = "".join(scenario)
    if isinstance(mes_example, list):
        mes_example = "".join(mes_example)
    if isinstance(system_prompt, list):
        system_prompt = "".join(system_prompt)

    # ── 世界书转换 ──
    raw_entries: list[dict] = []
    char_book = get("character_book") or {}
    if isinstance(char_book, dict):
        raw_entries = char_book.get("entries", [])
    elif isinstance(char_book, list):
        raw_entries = char_book

    before_blocks: list[str] = []   # 常驻 before → 折进 description 末尾
    after_blocks:  list[str] = []   # 常驻 after  → post_history_extra
    world_book:    list[dict] = []  # 关键词条目

    stats = {"skipped": 0, "constant_before": 0, "constant_after": 0, "keyword": 0, "warned": []}

    for entry in raw_entries:
        if not entry.get("enabled", True):
            stats["skipped"] += 1
            continue
        content = (entry.get("content") or "").strip()
        if not content:
            stats["skipped"] += 1
            continue

        comment = (entry.get("comment") or entry.get("name") or "").strip()
        keys: list = entry.get("keys") or []
        is_constant = entry.get("constant", False) or not keys

        # 忽略项警告
        if entry.get("regex_scripts") or entry.get("tavern_helper"):
            w = f"条目 '{comment}': regex_scripts/tavern_helper 已忽略"
            stats["warned"].append(w)
            print(f"[WARNING] {w}", file=sys.stderr)

        if is_constant:
            pos = _classify_position(entry)
            label = f"[常驻设定:{comment}]" if comment else "[常驻设定]"
            block = f"{label}\n{content}"
            if pos == "before":
                before_blocks.append(block)
                stats["constant_before"] += 1
            else:
                after_blocks.append(block)
                stats["constant_after"] += 1
        else:
            # 关键词条目
            secondary = entry.get("secondary_keys") or []
            sel_logic  = entry.get("extensions", {}).get("selectiveLogic")
            probability = entry.get("extensions", {}).get("probability")
            if secondary:
                w = f"条目 '{comment}': secondary_keys {secondary!r} 暂不支持（已忽略）"
                stats["warned"].append(w)
                print(f"[WARNING] {w}", file=sys.stderr)
            if sel_logic is not None:
                w = f"条目 '{comment}': selectiveLogic={sel_logic!r} 暂不支持（已忽略）"
                stats["warned"].append(w)
                print(f"[WARNING] {w}", file=sys.stderr)
            if probability is not None and probability != 100:
                w = f"条目 '{comment}': probability={probability} 已按 100% 处理"
                stats["warned"].append(w)
                print(f"[WARNING] {w}", file=sys.stderr)

            use_regex = bool(entry.get("use_regex") or entry.get("regex"))
            order = entry.get("insertion_order", 100)
            try:
                order = int(order)
            except (TypeError, ValueError):
                order = 100

            world_book.append({
                "keywords": list(keys),
                "content": content,
                "regex": use_regex,
                "insertion_order": order,
                "enabled": True,
            })
            stats["keyword"] += 1

    # ── 将 before 常驻块折进 description ──
    if before_blocks:
        sep = "\n\n" if description else ""
        description = description + sep + "\n\n".join(before_blocks)

    # ── 组装 post_history_extra ──
    post_history_extra = "\n\n".join(after_blocks) if after_blocks else ""

    # ── alternate_greetings ──
    alt_greetings = get("alternate_greetings") or []
    if not isinstance(alt_greetings, list):
        alt_greetings = [str(alt_greetings)]

    # ── post_history_instructions ──
    post_history_instructions = get("post_history_instructions") or ""

    # ── 元数据 ──
    import_meta: dict = {}
    for k in ("creator", "creator_notes", "character_version", "tags"):
        v = get(k)
        if v:
            import_meta[k] = v

    # ── 组装输出 JSON ──
    output: dict = {}
    output["name"] = name
    if system_prompt:
        output["system_prompt"] = system_prompt
    if description:
        output["description"] = description
    if personality:
        output["personality"] = personality
    if scenario:
        output["scenario"] = scenario
    if mes_example:
        output["mes_example"] = mes_example
    if first_mes:
        output["first_mes"] = first_mes
    output["world_book"] = world_book
    if alt_greetings:
        output["alternate_greetings"] = alt_greetings
    if post_history_instructions:
        output["post_history_instructions"] = post_history_instructions
    if post_history_extra:
        output["post_history_extra"] = post_history_extra
    if import_meta:
        output["_import_meta"] = import_meta

    # ── 原子写入 ──
    payload = json.dumps(output, ensure_ascii=False, indent=2)
    ok = safe_write_text(out_path, payload)
    if not ok:
        print(f"[ERROR] 写入失败: {out_path}", file=sys.stderr)
        sys.exit(1)

    return {
        "name": name,
        "out_path": out_path,
        "world_book_total": len(raw_entries),
        "skipped": stats["skipped"],
        "constant_before": stats["constant_before"],
        "constant_after": stats["constant_after"],
        "keyword": stats["keyword"],
        "alt_greetings": len(alt_greetings),
        "has_post_history_instructions": bool(post_history_instructions),
        "has_post_history_extra": bool(post_history_extra),
        "import_meta": import_meta,
        "warnings": stats["warned"],
    }


# ─── 报告打印 ────────────────────────────────────────────────────────────────

def print_report(r: dict) -> None:
    print("\n========== 转换报告 ==========")
    print(f"角色名:        {r['name']}")
    print(f"输出文件:      {r['out_path']}")
    print()
    print(f"世界书条目:    共 {r['world_book_total']} 条")
    print(f"  ├ 跳过:      {r['skipped']} 条（disabled 或内容为空）")
    print(f"  ├ 常驻→description: {r['constant_before']} 条")
    print(f"  ├ 常驻→post_history_extra: {r['constant_after']} 条")
    print(f"  └ 关键词→world_book: {r['keyword']} 条")
    print()
    print(f"备用开场白:    {r['alt_greetings']} 条")
    print(f"post_history_instructions: {'有' if r['has_post_history_instructions'] else '无'}")
    print(f"post_history_extra:        {'有' if r['has_post_history_extra'] else '无'}")

    if r["import_meta"]:
        print()
        print("来源元数据:")
        for k, v in r["import_meta"].items():
            val_str = str(v)
            if len(val_str) > 80:
                val_str = val_str[:77] + "..."
            print(f"  {k}: {val_str}")

    if r["warnings"]:
        print()
        print(f"警告 ({len(r['warnings'])} 条):")
        for w in r["warnings"]:
            print(f"  ! {w}")

    print("================================\n")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _default_id(src: Path) -> str:
    stem = src.stem
    # 去掉非字母数字汉字下划线连字符
    cleaned = re.sub(r"[^\w\-]", "_", stem, flags=re.UNICODE)
    return cleaned.lower()


def resolve_output_path(*, char_id: str, explicit_out: str | None, repo_root: Path = _REPO_ROOT) -> Path:
    """Choose a canonical default while refusing explicit legacy-root writes."""
    if not explicit_out:
        return repo_root / "userdata" / "characters" / "cards" / f"{char_id}.json"

    out_path = Path(explicit_out)
    resolved_out = out_path.resolve()
    for legacy_root in ("characters", "content", "defaults", "examples"):
        root = (repo_root / legacy_root).resolve()
        if resolved_out.is_relative_to(root):
            raise ValueError(
                f"--out 指向只读 legacy/public root ({legacy_root}/)；"
                "请改用 userdata/characters/cards/ 或仓库外的显式导出路径。"
            )
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="将 SillyTavern 角色卡 (.json) 转换为 Presence 格式"
    )
    parser.add_argument("src", help="输入的酒馆卡 JSON 文件路径")
    parser.add_argument("--out", help="输出路径，默认 userdata/characters/cards/<id>.json")
    parser.add_argument("--id",  help="角色 ID，默认取输入文件名 stem")
    args = parser.parse_args()

    src_path = Path(args.src)
    if not src_path.exists():
        print(f"[ERROR] 输入文件不存在: {src_path}", file=sys.stderr)
        sys.exit(1)

    char_id = args.id or _default_id(src_path)

    try:
        out_path = resolve_output_path(char_id=char_id, explicit_out=args.out)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)

    print(f"正在转换: {src_path} → {out_path}  (id={char_id})")

    report = convert(src_path, out_path, char_id)
    print_report(report)
    print(f"完成。生成文件: {out_path}")


if __name__ == "__main__":
    main()
