"""Background practice sessions, blind review and portfolio (Briefs 59-60)."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from core.data_paths import DEFAULT_CHAR_ID

logger = logging.getLogger(__name__)
LEVEL_THRESHOLDS = {1: 6.0, 2: 6.8, 3: 7.5, 4: 8.2}
MAX_LEVEL = 5
HELP_SNIPPET_CHARS = 100
SIMPLIFIED_CONSTRAINTS = {
    "writing": "保持在8行以内，只练一个清楚的技巧。",
    "music": "只写一个短小段落或旋律构想，不追求完整作品。",
    "drawing": "只做一个简单构图或单一对象的文字画面方案。",
    "other": "把练习收窄为一个小动作，在有限范围内完成。",
}
REVIEW_RUBRIC = "按当前学习等级而非专业标准盲评：完成度、控制力、具体进步各占合理权重。"


def _works_dir(interest_id: str, char_id: str):
    from core.sandbox import get_paths
    return get_paths().growth_works_dir(interest_id, char_id=char_id)


def load_index(interest_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> list[dict]:
    path = _works_dir(interest_id, char_id) / "index.json"
    if not path.exists(): return []
    try:
        value=json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value,list) else []
    except Exception: return []


def recent_works(interest_id: str, *, char_id: str = DEFAULT_CHAR_ID, limit: int = 2) -> list[str]:
    root=_works_dir(interest_id,char_id); result=[]
    for item in load_index(interest_id,char_id=char_id)[-limit:]:
        try: result.append((root/item["file"]).read_text(encoding="utf-8"))
        except Exception: pass
    return result


def build_practice_prompt(interest: dict, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[str,list[dict]]:
    from core.character_loader import load as load_character
    from core.growth import notes
    char=load_character(char_id); anchors=notes.load(interest["id"],char_id=char_id)
    note_text="\n".join(f"- {x['text']}" for x in anchors)[:notes.MAX_PROMPT_CHARS]
    works=recent_works(interest["id"],char_id=char_id)
    parts=[f"你是{char.name}。角色摘要：{char.personality[:500]}",f"你正在学习：{interest['name']}，当前 level {interest['level']}。","在已有基础上试着比上次进步一点，不要调用模型先验一步做成大师作品。"]
    if int(interest["level"]) <= 2: parts.append("简化约束："+SIMPLIFIED_CONSTRAINTS.get(interest.get("domain","other"),SIMPLIFIED_CONSTRAINTS["other"]))
    if note_text: parts.append("这些是你摸索出的心得，练习时有意识地运用它们：\n"+note_text)
    if works: parts.append("最近两件作品（含旧评语，仅作水平锚）：\n"+"\n---\n".join(works))
    parts.append("只输出本次练习作品正文。")
    return "\n\n".join(parts), anchors


def _json(text: str) -> dict | None:
    try:
        m=re.search(r"\{.*\}",text,re.S); obj=json.loads(m.group(0) if m else text)
        return obj if isinstance(obj,dict) else None
    except Exception: return None


async def _review(work: str, interest: dict, *, char_id: str) -> dict | None:
    from core import llm_client
    from core.config_loader import get_config
    practice_cfg = get_config().get("practice", {}) or {}
    preset = str(practice_cfg.get("reviewer_preset") or "").strip() or None
    category = str(practice_cfg.get("reviewer_category") or "consolidation").strip()
    if not category:
        raise ValueError("practice.reviewer_category must not be empty")
    prompt=f"{REVIEW_RUBRIC}\n学习项目：{interest['name']}；level={interest['level']}。\n作品：\n{work}\n只输出 JSON：{{\"score\":0到10,\"strengths\":[\"...\"],\"one_improvement\":\"...\"}}"
    obj=_json(await llm_client.chat(
        [{"role":"user","content":prompt}],
        call_category=category,
        char_id=char_id,
        preset_name=preset,
    ))
    if not obj or not isinstance(obj.get("score"),(int,float)) or not 0 <= float(obj["score"]) <= 10 or not isinstance(obj.get("one_improvement"),str): return None
    return obj


def _save_work(interest: dict, work: str, review: dict, *, char_id: str, artifact_ref: str = "") -> dict:
    from core.safe_write import safe_write_json, safe_write_text
    root=_works_dir(interest["id"],char_id); root.mkdir(parents=True,exist_ok=True)
    index=load_index(interest["id"],char_id=char_id); day=datetime.now().strftime("%Y%m%d")
    n=1+sum(str(x.get("file","")).startswith(day+"_") for x in index); filename=f"{day}_{n}.md"
    strengths="、".join(str(x) for x in review.get("strengths",[])[:3])
    body=f"# {interest['name']} · {day}_{n}\n\n{work}\n\n## 盲评\n\n- 分数：{float(review['score']):.1f}\n- 做得好的：{strengths}\n- 下一步：{review['one_improvement']}\n"
    if artifact_ref: body += f"- 媒介产物：{artifact_ref}\n"
    safe_write_text(root/filename,body)
    item={"date":datetime.now().isoformat(timespec="seconds"),"score":float(review["score"]),"summary":str(review["one_improvement"])[:80],"file":filename}
    if artifact_ref: item["artifact_ref"]=artifact_ref
    index.append(item); safe_write_json(root/"index.json",index)
    return item


async def _learn_note(interest: dict, work: str, review: dict, existing: list[dict], source: str, *, char_id: str, uid: str) -> None:
    from core import llm_client
    from core.growth import notes
    prompt=f"从这次练习提炼一条第一人称具体心得，最多{notes.MAX_NOTE_CHARS}字；没学到新东西就 null。\n作品：{work}\n改进意见：{review['one_improvement']}\n已有：{json.dumps([x['text'] for x in existing],ensure_ascii=False)}\n只输出 JSON：{{\"note\":\"我发现……\"或null,\"replaces\":null或行号}}"
    obj=_json(await llm_client.chat([{"role":"user","content":prompt}],call_category="chat",char_id=char_id))
    if obj: notes.apply_note(interest["id"],obj.get("note"),source=source,replaces=obj.get("replaces"),char_id=char_id,uid=uid)


async def run_session(payload: dict) -> dict | None:
    uid=str(payload["uid"]); char_id=str(payload["char_id"]); interest_id=str(payload["interest_id"])
    from core.growth import interest_state, notes
    interest=next((x for x in interest_state.active_interests(char_id) if x["id"]==interest_id),None)
    if interest is None: return None
    prompt, injected_notes=build_practice_prompt(interest,char_id=char_id)
    from core import llm_client
    work=(await llm_client.chat([{"role":"user","content":prompt}],call_category="chat",char_id=char_id)).strip()
    if not work: return None
    review=await _review(work,interest,char_id=char_id)
    if review is None: return None
    previous_scores=list(interest.get("recent_scores",[])); item=_save_work(interest,work,review,char_id=char_id,artifact_ref=str(payload.get("artifact_ref") or ""))
    updated=await interest_state.record_score(interest_id,float(review["score"]),char_id=char_id,uid=uid)
    if previous_scores and float(review["score"])>previous_scores[-1] and injected_notes: notes.increment_hits(interest_id,char_id=char_id)
    try:
        from core.memory import action_trace
        action_trace.record(uid,char_id,tool="practice",origin="assistant_loop",status="ok",result_digest=f"练了{interest['name']}，{str(review['one_improvement'])[:40]}",echo_event_log=True)
    except Exception: pass
    if updated and int(updated["level"]) < MAX_LEVEL and len(updated["recent_scores"]) >= 5 and sum(updated["recent_scores"][-5:])/5 >= LEVEL_THRESHOLDS[int(updated["level"])]:
        upgraded,old=await interest_state.set_level(interest_id,int(updated["level"])+1,char_id=char_id,uid=uid)
        if upgraded: await _record_unlock(uid,char_id,upgraded,old)
    try: await _learn_note(interest,work,review,injected_notes,item["file"].removesuffix(".md"),char_id=char_id,uid=uid)
    except Exception: logger.exception("[practice] note extraction failed")
    return {"work":item,"review":review,"interest":updated}


async def _record_unlock(uid: str,char_id: str,interest: dict,old_level: int) -> None:
    try:
        from core.growth.mcp_proficiency import newly_unlocked
        unlocked=newly_unlocked(interest.get("domain","other"),old_level,int(interest["level"]))
        if not unlocked: return
        from core.memory import action_trace,provenance_log
        for entry in unlocked:
            note=entry.get("unlock_note") or "一项新的方法"
            action_trace.record(uid,char_id,tool="growth_unlock",origin="assistant_loop",status="ok",result_digest=f"琢磨明白了{note}",echo_event_log=True)
            provenance_log.append(uid,char_id,artifact="mcp_proficiency",field=entry["tool"],after_gist=str(note),trigger_signal="tier_unlocked",origin={"source":"practice"})
    except Exception: logger.debug("[practice] unlock trace failed",exc_info=True)


async def handler_practice_session(payload: dict) -> None:
    await run_session(payload)
