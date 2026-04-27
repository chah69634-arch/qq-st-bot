"""
episodic_memory — 情景记忆系统。
存储叶瑄视角的情节单元，支持标签检索+强度衰减。
与event_log并行，不替换它。
"""

import json
import logging
import math
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MEM_ROOT = Path("data/episodic_memory")
_INDEX_ROOT = Path("data/memory_index")


def _mem_file(user_id: str) -> Path:
    _MEM_ROOT.mkdir(parents=True, exist_ok=True)
    return _MEM_ROOT / f"{user_id}.json"


def _index_file(user_id: str) -> Path:
    _INDEX_ROOT.mkdir(parents=True, exist_ok=True)
    return _INDEX_ROOT / f"{user_id}.json"


def _load_memories(user_id: str) -> list:
    try:
        return json.loads(_mem_file(user_id).read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_memories(user_id: str, memories: list) -> None:
    _mem_file(user_id).write_text(
        json.dumps(memories, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_index(user_id: str) -> dict:
    try:
        return json.loads(_index_file(user_id).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_index(user_id: str, index: dict) -> None:
    _index_file(user_id).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    if not a or not b:
        return False
    shorter = a if len(a) <= len(b) else b
    longer = b if len(a) <= len(b) else a
    overlap = sum(1 for ch in shorter if ch in longer)
    return overlap / max(len(shorter), 1) >= threshold


def _rebuild_index(user_id: str, memories: list) -> None:
    """按标签建倒排索引：tag -> [memory_id, ...]"""
    index = {}
    for mem in memories:
        for tag in mem.get("tags", []):
            index.setdefault(tag, [])
            if mem["id"] not in index[tag]:
                index[tag].append(mem["id"])
    _save_index(user_id, index)


def write_episode(user_id: str, episode: dict) -> None:
    """
    写入一条情景记忆。
    episode格式：
    {
      "id": "ep_timestamp",
      "timestamp": float,
      "summary": "叶瑄视角的情节概括",
      "yexuan_feeling": "叶瑄当时的感受",
      "emotion_peak": "gentle",
      "tags": ["失眠", "深夜", "陪伴"],
      "strength": 0.8,
      "retrieval_count": 0,
      "last_retrieved": null
    }
    """
    memories = _load_memories(user_id)

    # 去重：与最近10条做summary相似度检查
    new_summary = episode.get("summary", "")
    for existing in memories[-10:]:
        if _is_similar(new_summary, existing.get("summary", "")):
            logger.info(f"[episodic] 重复记忆跳过: {new_summary}")
            return

    # 上限控制：超过200条时删掉strength最低的20条
    MAX_MEMORIES = 200
    if len(memories) >= MAX_MEMORIES:
        memories.sort(key=lambda m: m.get("strength", 0))
        memories = memories[20:]
        logger.info(f"[episodic] 记忆库裁剪至{len(memories)}条")

    # 双轨strength修正：LLM给初始值，规则叠加校正
    s = episode.get("strength", 0.5)
    ep = episode.get("emotion_peak", "neutral")
    tags = episode.get("tags", [])

    if ep in ("sad", "angry"):
        s = min(1.0, s + 0.1)
    if ep in ("happy", "surprised"):
        s = min(1.0, s + 0.05)
    if len(tags) >= 4:
        s = min(1.0, s + 0.05)
    conflict_tags = {"吵架", "道歉", "哭", "生气", "误会", "和好"}
    if any(t in conflict_tags for t in tags):
        s = min(1.0, s + 0.2)
    first_tags = {"第一次", "初次", "第一回", "生日", "纪念"}
    if any(t in first_tags for t in tags):
        s = min(1.0, s + 0.15)
        episode["is_core"] = True

    episode["strength"] = round(s, 3)

    memories.append(episode)
    _save_memories(user_id, memories)
    _rebuild_index(user_id, memories)
    logger.info(f"[episodic] 写入情景记忆: {episode['id']}")


def retrieve(user_id: str, topic: str = "", emotion: str = "", top_k: int = 3) -> list:
    """
    按话题标签+情绪检索最相关的情景记忆，检索后强化strength。
    返回list[dict]，按相关性排序。
    """
    memories = _load_memories(user_id)
    if not memories:
        return []

    index = _load_index(user_id)
    now = time.time()

    # 候选集：标签匹配
    candidate_ids = set()
    if topic:
        for tag, ids in index.items():
            if any(kw in tag for kw in topic.split()):
                candidate_ids.update(ids)

    # 无匹配时全量参与评分
    if not candidate_ids:
        candidate_ids = {m["id"] for m in memories}

    # 评分
    scored = []
    for mem in memories:
        if mem["id"] not in candidate_ids:
            continue

        days = (now - mem["timestamp"]) / 86400
        decay = math.exp(-0.05 * days)
        strength = mem.get("strength", 0.5)
        emotion_bonus = 0.2 if mem.get("emotion_peak") == emotion else 0.0
        score = strength * decay + emotion_bonus
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 浮起阈值：分数太低的记忆不注入，宁可不说也不强行关联
    MIN_SCORE = 0.15
    scored = [(score, mem) for score, mem in scored if score >= MIN_SCORE]
    scored.sort(key=lambda x: x[0], reverse=True)

    # 核心记忆优先
    core = [mem for _, mem in scored if mem.get("is_core")]
    normal = [mem for _, mem in scored if not mem.get("is_core")]
    result = (core + normal)[:top_k]

    # 检索后强化
    ids_to_strengthen = {m["id"] for m in result}
    changed = False
    for mem in memories:
        if mem["id"] in ids_to_strengthen:
            mem["strength"] = min(1.0, mem.get("strength", 0.5) + 0.15)
            mem["retrieval_count"] = mem.get("retrieval_count", 0) + 1
            mem["last_retrieved"] = now
            changed = True

    if changed:
        _save_memories(user_id, memories)

    return result


def decay_all(user_id: str) -> None:
    """每日衰减，按情绪强度和被提及次数差异化处理。核心记忆不衰减。"""
    memories = _load_memories(user_id)
    now = time.time()
    for mem in memories:
        if mem.get("is_core"):
            continue
        days = (now - mem["timestamp"]) / 86400
        ep = mem.get("emotion_peak", "neutral")
        retrieval = mem.get("retrieval_count", 0)

        if ep in ("sad", "angry"):
            base_rate = 0.015
        elif ep == "neutral":
            base_rate = 0.05
        else:
            base_rate = 0.03

        recall_factor = max(0.3, 1.0 - retrieval * 0.1)
        rate = base_rate * recall_factor

        mem["strength"] = max(0.05, mem.get("strength", 0.5) * math.exp(-rate * days))

    _save_memories(user_id, memories)


def format_for_prompt(
    memories: list,
    char_name: str = "叶瑄",
    current_emotion: str = "neutral",
) -> str:
    """把情景记忆列表格式化成prompt注入文本，带时间锚点和情绪染色。"""
    if not memories:
        return ""

    now = time.time()
    lines = [f"{char_name}脑海里浮现的片段："]

    for mem in memories:
        summary = mem.get("summary", "")
        feeling = mem.get("yexuan_feeling", "")
        if not summary:
            continue

        days = (now - mem["timestamp"]) / 86400
        if days < 1:
            time_str = "今天"
        elif days < 3:
            time_str = "前几天"
        elif days < 7:
            time_str = "上周"
        elif days < 30:
            time_str = f"大约{int(days)}天前"
        else:
            time_str = f"{int(days // 30)}个月前"

        texture = mem.get("emotion_texture", "")
        arc = mem.get("emotion_arc", "")
        feeling = mem.get("yexuan_feeling", "")

        if texture:
            if current_emotion in ("sad", "gentle"):
                feeling_str = f"——{texture}"
            else:
                feeling_str = f"，{texture}"
        elif feeling:
            feeling_str = f"，他{feeling}"
        else:
            feeling_str = ""

        arc_str = f"（{arc}）" if arc else ""

        core_mark = "【重要】" if mem.get("is_core") else ""
        lines.append(f"- {core_mark}{time_str}，{summary}{feeling_str}{arc_str}")

    return "\n".join(lines)
