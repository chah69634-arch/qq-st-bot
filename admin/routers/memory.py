"""
记忆管理路由
"""

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import verify_token

router = APIRouter()


# ── 短期记忆 ──────────────────────────────────────────────────────────────────

@router.get("/{user_id}/short-term", summary="获取短期记忆")
async def get_short_term(user_id: str, auth=Depends(verify_token)):
    """返回用户最近的对话历史（滚动窗口内的全部消息）"""
    from core.memory import short_term
    history = short_term.load(user_id)
    return {"user_id": user_id, "history": history, "count": len(history)}


@router.delete("/{user_id}/short-term", summary="清除短期记忆")
async def clear_short_term(user_id: str, auth=Depends(verify_token)):
    """清空用户短期对话历史（写入空列表）"""
    from core.memory import short_term
    short_term.clear(user_id)
    return {"message": f"用户 {user_id} 短期记忆已清除"}

