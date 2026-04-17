"""
QQ 资料设置接口
通过 NapCat WebSocket 修改机器人的头像、昵称和群名片。

接口列表：
  PUT /qq-avatar       修改头像（base64 图片）
  PUT /qq-nickname     修改昵称
  GET /qq-groups       获取 bot 所在群列表
  PUT /qq-group-card   修改指定群的群名片
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin.auth import verify_token

router = APIRouter()


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

async def _ws(action: str, params: dict) -> dict:
    """调用 NapCat WS API，失败时抛出 HTTPException"""
    from core import qq_adapter
    result = await qq_adapter.ws_call(action, params, timeout=8.0)
    if result is None:
        raise HTTPException(status_code=503, detail="NapCat 未连接或请求超时")
    if result.get("status") not in ("ok", "OK"):
        raise HTTPException(
            status_code=502,
            detail=f"NapCat 返回错误: {result.get('message', result.get('msg', '未知'))}"
        )
    return result.get("data") or {}


# ─── 头像 ──────────────────────────────────────────────────────────────────────

class AvatarUpdate(BaseModel):
    base64: str   # 纯 base64，不含 data:image 前缀


@router.put("/qq-avatar", summary="修改 bot 头像")
async def set_avatar(body: AvatarUpdate, auth=Depends(verify_token)):
    """接收 base64 图片，调用 NapCat set_qq_avatar"""
    if not body.base64.strip():
        raise HTTPException(status_code=422, detail="base64 不能为空")
    await _ws("set_qq_avatar", {"file": f"base64://{body.base64.strip()}"})
    return {"message": "头像已更新"}


# ─── 昵称 ──────────────────────────────────────────────────────────────────────

class NicknameUpdate(BaseModel):
    nickname: str


@router.put("/qq-nickname", summary="修改 bot 昵称")
async def set_nickname(body: NicknameUpdate, auth=Depends(verify_token)):
    """调用 NapCat set_qq_profile 修改昵称"""
    if not body.nickname.strip():
        raise HTTPException(status_code=422, detail="昵称不能为空")
    await _ws("set_qq_profile", {"nickname": body.nickname.strip()})
    return {"message": f"昵称已改为 {body.nickname.strip()!r}"}


# ─── 群列表 ───────────────────────────────────────────────────────────────────

@router.get("/qq-groups", summary="获取 bot 所在群列表")
async def get_groups(auth=Depends(verify_token)):
    """调用 NapCat get_group_list 返回群列表"""
    from core import qq_adapter
    result = await qq_adapter.ws_call("get_group_list", {}, timeout=8.0)
    if result is None:
        raise HTTPException(status_code=503, detail="NapCat 未连接或请求超时")
    groups = result.get("data") or []
    return {
        "groups": [
            {
                "group_id":   str(g.get("group_id", "")),
                "group_name": g.get("group_name", ""),
                "member_count": g.get("member_count", 0),
            }
            for g in groups
        ]
    }


# ─── 群名片 ───────────────────────────────────────────────────────────────────

class GroupCardUpdate(BaseModel):
    group_id: str
    card: str     # 新名片，留空则清除名片


@router.put("/qq-group-card", summary="修改 bot 在指定群的群名片")
async def set_group_card(body: GroupCardUpdate, auth=Depends(verify_token)):
    """调用 NapCat set_group_card"""
    if not body.group_id.strip():
        raise HTTPException(status_code=422, detail="group_id 不能为空")
    await _ws("set_group_card", {
        "group_id": int(body.group_id),
        "user_id":  0,   # 0 表示修改自己
        "card":     body.card,
    })
    return {"message": f"群 {body.group_id} 名片已设置为 {body.card!r}"}
