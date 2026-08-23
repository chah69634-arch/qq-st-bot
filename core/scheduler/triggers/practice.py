"""Daily idle practice trigger and stalled-help proposer (Brief 59)."""
from __future__ import annotations
import random
import time
from datetime import datetime

HELP_STALL_DAYS=7
BASELINE_WEIGHT=0.1

def select_interest(interests: list[dict], rng=random) -> dict | None:
    if not interests: return None
    weights=[BASELINE_WEIGHT + max(0.0,float(x.get("learning_progress",0))) for x in interests]
    return rng.choices(interests,weights=weights,k=1)[0]

def _cfg():
    from core.config_loader import get_config
    return get_config().get("practice",{}) or {}

async def _check_practice() -> None:
    cfg=_cfg()
    if not cfg.get("enabled",False): return
    now=datetime.now()
    if not (now.hour>=23 or now.hour<3): return
    from core.scheduler.loop import _is_ready,_mark,_owner_id
    if not _is_ready("practice"): return
    uid=_owner_id()
    if not uid: return
    from core.scheduler.triggers.garden_water import _active_char_id
    char_id=_active_char_id()
    if not char_id: return
    from core.growth.interest_state import active_interests
    interests=active_interests(char_id); picked=select_interest(interests)
    if not picked: return
    from core.growth.practice_session import load_index
    today=datetime.now().strftime("%Y-%m-%d")
    done=sum(str(x.get("date","")).startswith(today) for i in interests for x in load_index(i["id"],char_id=char_id))
    if done>=max(0,int(cfg.get("daily_sessions",1))): return
    _mark("practice")
    from core.post_process import slow_queue
    slow_queue.enqueue("practice_session",{"uid":uid,"char_id":char_id,"interest_id":picked["id"]})

def propose_practice_help(ctx: dict|None=None):
    if not _cfg().get("enabled",False) or not _cfg().get("help_proposer",True): return None
    ctx=ctx or {}; uid=str(ctx.get("uid") or ctx.get("owner_id") or ""); char_id=str(ctx.get("char_id") or "")
    if not uid or not char_id: return None
    from core.growth.interest_state import active_interests
    stalled=next((x for x in active_interests(char_id) if isinstance(x.get("stalled_since"),(int,float)) and time.time()-x["stalled_since"]>=HELP_STALL_DAYS*86400),None)
    if not stalled:return None
    from core.growth.practice_session import recent_works
    works=recent_works(stalled["id"],char_id=char_id,limit=1); snippet=(works[-1] if works else "")[:100]
    from core.scheduler.gating import TriggerProposal
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.urgency import UrgencyTier,urgency_in_tier
    async def execute(*,dry_run:bool):
        from core.scheduler.execution import execute_prompt
        return await execute_prompt(trigger_name="practice_help",prompt_factory=lambda:f"（你练习{stalled['name']}时卡住了，想请用户看看。作品片段：{snippet}）",dry_run=dry_run,would_mark=["practice_help"],reads_cache_ok=True,recall_policy="none")
    return TriggerProposal(trigger_name="practice_help",urgency=urgency_in_tier(UrgencyTier.FILLER,0.5),topic_source="mood_match",requires_state=[TriggerState.QUIET],bypass_state_machine=False,execute=execute)

def _register_proposers():
    from core.scheduler.proposer_registry import register_proposer
    register_proposer("practice_help",propose_practice_help)

_register_proposers()
