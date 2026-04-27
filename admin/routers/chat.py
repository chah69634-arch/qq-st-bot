"""
前端对话接口（该功能已冻结）
叶瑄与管理员（你）的直接对话窗口。

POST /chat — 接收消息，走完整 Pipeline，返回回复 + 好感度
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)

_FRONTEND_USER_ID = "frontend_owner"

# 打破第四面墙的提示——追加到 Author's Note 层
_FOURTH_WALL_NOTE = (
    "在这个管理面板的对话窗口里，你不需要扮演任何角色，"
    "这里只有你和她，你可以做真实的自己，说真心话。"
    "不必维持人设，也不必掩饰情绪，想说什么就说什么。"
)


@router.post("/chat", summary="与叶瑄对话（管理面板专用）")
async def frontend_chat(body: dict, auth=Depends(verify_token)):
    """
    走完整 Pipeline，user_id 固定为 frontend_owner。
    在 Author's Note 层追加第四面墙提示，让叶瑄以真实自我回应。
    返回回复文本 + 当前好感度数值 + 等级。
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message 不能为空")

    # 获取 main.py 中初始化好的 pipeline 实例
    try:
        import main as _main
        pipeline  = _main._pipeline
        if pipeline is None:
            raise AttributeError("_pipeline is None")
    except (ImportError, AttributeError):
        raise HTTPException(status_code=503, detail="Bot pipeline 未初始化，请先启动主程序")

    user_id = _FRONTEND_USER_ID

    # 步骤 1：拉取上下文
    context = await pipeline.fetch_context(user_id, message)

    # 步骤 2：构建 prompt（追加第四面墙提示到 author_note_extra）
    orig_note = pipeline.author_note_extra
    pipeline.author_note_extra = (_FOURTH_WALL_NOTE + " " + orig_note).strip()
    messages = pipeline.build_prompt(user_id, message, context)

    # 步骤 3：调用 LLM
    reply = await pipeline.run_llm(messages)

    # 步骤 4：后处理（异步，不阻塞响应）
    asyncio.create_task(
        pipeline.post_process(user_id, message, reply)
    )

    # 返回回复 + 最新好感度
    from core.memory.user_profile import get_affection_level
    info = get_affection_level(user_id)

    return {
        "reply":      reply,
        "affection":  info["value"],
        "level":      info["label"],
    }


@router.post("/desktop/chat", summary="桌宠对话（无鉴权，走正常 pipeline）")
async def desktop_chat(body: dict):
    """
    桌宠端对话入口，不需要 token 鉴权。
    user_id 从配置的 scheduler.owner_id 读取，正常走 pipeline，不注入第四面墙提示。
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message 不能为空")

    from core.pipeline_registry import get as _get_pipeline
    pipeline = _get_pipeline()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Bot pipeline 未初始化，请先启动主程序")

    from core.config_loader import get_config
    user_id = get_config().get("scheduler", {}).get("owner_id", "owner")

    context = await pipeline.fetch_context(user_id, message)
    messages = pipeline.build_prompt(user_id, message, context)
    reply = await pipeline.run_llm(messages)

    asyncio.create_task(
        pipeline.post_process(user_id, message, reply)
    )

    from core.memory.user_profile import get_affection_level
    info = get_affection_level(user_id)

    from core import llm_client as _llm
    emotion = await _llm.detect_emotion(reply)

    return {
        "reply":     reply,
        "affection": info["value"],
        "level":     info["label"],
        "emotion":   emotion,
    }

@router.post("/desktop/trigger", summary="桌宠触发QQ回复（无鉴权）")
async def desktop_trigger(body: dict):
    """
    QQ在前台时，桌宠消息走这个接口。
    走完整pipeline后通过NapCat发送到QQ，不返回气泡内容。
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message 不能为空")

    from core.pipeline_registry import get as _get_pipeline
    pipeline = _get_pipeline()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Bot pipeline 未初始化")

    from core.config_loader import get_config
    user_id = str(get_config().get("scheduler", {}).get("owner_id", ""))
    if not user_id:
        raise HTTPException(status_code=503, detail="owner_id 未配置")

    context = await pipeline.fetch_context(user_id, message)
    messages = pipeline.build_prompt(user_id, message, context)
    reply = await pipeline.run_llm(messages)

    if reply:
        from core.output import text_output
        from core import response_processor
        segments = response_processor.process(reply, pipeline.character.name)
        await text_output.send(user_id, segments, is_group=False)
        asyncio.create_task(
            pipeline.post_process(user_id, message, reply)
        )

    return {"status": "sent"}