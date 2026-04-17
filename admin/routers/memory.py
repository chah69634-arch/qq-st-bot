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


# ── 长期 RAG 记忆（已冻结：long_term_rag 模块已移除）────────────────────────

@router.get("/{user_id}/rag/search", summary="搜索长期记忆（已禁用）")
async def search_rag(user_id: str, query: str, auth=Depends(verify_token)):
    raise HTTPException(status_code=410, detail="长期 RAG 记忆功能已移除")


@router.delete("/{user_id}/rag", summary="清除长期记忆（已禁用）")
async def clear_rag(user_id: str, auth=Depends(verify_token)):
    raise HTTPException(status_code=410, detail="长期 RAG 记忆功能已移除")


# ── 好感度（已冻结）──────────────────────────────────────────────────────────

@router.get("/{user_id}/affection", summary="获取用户好感度（已冻结）")
async def get_affection(user_id: str, auth=Depends(verify_token)):
    raise HTTPException(status_code=410, detail="好感度功能已冻结")


@router.put("/{user_id}/affection", summary="设置用户好感度（已冻结）")
async def set_affection(user_id: str, body: dict, auth=Depends(verify_token)):
    raise HTTPException(status_code=410, detail="好感度功能已冻结")
