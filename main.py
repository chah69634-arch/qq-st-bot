"""
QQ-SillyTavern Bot 主程序
整合所有模块，实现完整的消息处理流程

启动方式：python main.py
依赖安装：pip install openai aiohttp websockets pyyaml fastapi uvicorn ddgs
"""

import asyncio
import logging
import os
import sys

# ── 日志基础配置 ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── 工作目录：切换到 main.py 所在目录，保证相对路径正确 ──────────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════════════════
# 全局对象（在 _init_modules 中初始化）
# ═══════════════════════════════════════════════════════════════════════════════

_pipeline = None   # core.pipeline.Pipeline 实例


def _init_modules():
    """同步初始化：加载配置、角色卡、世界书、Pipeline"""
    global _pipeline

    logger.info("正在加载配置文件...")
    from core.config_loader import get_config
    cfg = get_config()
    logger.info("配置文件加载完成")

    logger.info("正在加载角色卡...")
    from core import character_loader
    char_filename = cfg.get("character", {}).get("default", "default.json")
    character = character_loader.load(char_filename)
    logger.info(f"角色 '{character.name}' 已就绪")

    logger.info("正在初始化世界书引擎...")
    from core.lore_engine import LoreEngine
    lore_engine = LoreEngine(character.world_book)
    lore_engine.load()

    logger.info("正在初始化 Pipeline...")
    from core.pipeline import Pipeline
    _pipeline = Pipeline(character, lore_engine)

    from core import scheduler as _scheduler
    _scheduler.set_pipeline(_pipeline)

    logger.info("模块初始化完成")


# ═══════════════════════════════════════════════════════════════════════════════
# 核心消息处理函数
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_message(message: dict):
    """
    处理单条消息的完整流程（骨架）

    message 格式：{user_id, group_id, content, sender_name, timestamp}
    本函数由 message_queue 串行调用，同一会话不会并发。
    """
    user_id: str      = message["user_id"]
    group_id: str | None = message.get("group_id")
    content: str      = message["content"]
    sender_name: str  = message.get("sender_name", user_id)

    session_key = f"group_{group_id}" if group_id else f"user_{user_id}"
    target_id   = group_id if group_id else user_id
    is_group    = bool(group_id)

    logger.info(
        f"[handle_message] 收到消息 | {'群' if is_group else '私'} "
        f"{target_id} | {sender_name}: {content[:50]}"
    )

    from core import (
        session_state as ss,
        tool_dispatcher,
        response_processor,
    )
    from core.memory import group_context
    from core.output import text_output

    # ── 步骤1：群聊记录群消息流 ─────────────────────────────────────────────
    if is_group:
        group_context.append(group_id, sender_name, content)

    # ── 步骤2：会话状态机（等待确认 / 等待补充参数）──────────────────────────
    state = ss.get(session_key)

    if state.status == ss.SessionState.WAITING_CONFIRM:
        if content.strip() == "确认":
            logger.info(f"[handle_message] 用户确认执行工具: {state.pending_tool}")
            tool_result, _ = await tool_dispatcher.execute(
                tool_name=state.pending_tool,
                tool_args=state.pending_args or {},
                user_id=user_id,
                target_id=target_id,
                is_group=is_group,
                session_state=state,
            )
            state.clear()
            if tool_result:
                await _reply_with_tool_result(tool_result, user_id, target_id, is_group)
        else:
            logger.info("[handle_message] 用户取消了工具执行")
            state.clear()
            await text_output.send(target_id, ["好的，已取消～"], is_group)
        return

    elif state.status == ss.SessionState.WAITING_INPUT:
        logger.info(f"[handle_message] 收到补充参数: {content}")
        if state.pending_args is not None and state.pending_arg_key:
            state.pending_args[state.pending_arg_key] = content
        tool_result, ask_text = await tool_dispatcher.execute(
            tool_name=state.pending_tool,
            tool_args=state.pending_args or {},
            user_id=user_id,
            target_id=target_id,
            is_group=is_group,
            session_state=state,
        )
        state.clear()
        if ask_text:
            await text_output.send(target_id, [ask_text], is_group)
            return
        if tool_result:
            await _reply_with_tool_result(tool_result, user_id, target_id, is_group)
        return

    # ── 步骤2.5：处理图片和文件 ─────────────────────────────────────────────
    image_urls = message.get("image_urls", [])
    file_info = message.get("file_info")
    media_context = ""

    if file_info:
        try:
            from core.media_processor import process_file
            file_text = await process_file(file_info)
            if file_text:
                fname = file_info.get("name", "文件")
                media_context = f"（你发来了一个文件：{fname}，内容如下）\n{file_text[:3000]}"
                logger.info(f"[handle_message] 文件已读取: {fname} {len(file_text)}字")
        except Exception as e:
            from core.error_handler import log_error
            log_error("handle_message.file", e)

    if image_urls and not media_context:
        try:
            from core.media_processor import process_image
            img_desc = await process_image(image_urls[0], content)
            if img_desc:
                media_context = f"（你发来了一张图片，图片内容：{img_desc}）"
                logger.info(f"[handle_message] 图片已识别: {img_desc[:50]}")
        except Exception as e:
            from core.error_handler import log_error
            log_error("handle_message.image", e)

    if media_context:
        content = media_context + ("\n" + content if content else "")

    # ── 步骤3：工具调用探测 ──────────────────────────────────────────────────
    from core import llm_client
    from core.config_loader import get_config
    cfg = get_config()

    tool_result_text: str | None = None
    tool_mode = cfg.get("llm", {}).get("tool_call_mode", "function_calling")

    from datetime import datetime
    _now = datetime.now()
    _time_str = _now.strftime("%Y年%m月%d日 %H:%M 星期") + ["一", "二", "三", "四", "五", "六", "日"][_now.weekday()]
    from core.memory import user_profile as _up
    _profile = _up.load(user_id)
    _location = _profile.get("location", "杭州")
    tool_detection_messages = [
        {
            "role": "system",
            "content": (
                f"你是{_pipeline.character.name}。当前时间：{_time_str}。用户所在城市：{_location}。"
                "判断用户的消息是否需要调用工具（天气/备忘录/搜索）。"
                "查询天气时使用用户所在城市，除非用户明确指定其他城市。"
                "如果不需要工具，回复空字符串。"
            ),
        },
        {"role": "user", "content": content},
    ]
    tools_schema = tool_dispatcher.get_tools_schema()
    try:
        probe_response = await llm_client.chat(tool_detection_messages, tools=tools_schema)
    except Exception:
        probe_response = ""

    tool_calls = llm_client.parse_tool_call_response(probe_response)
    if tool_calls:
        for tc in tool_calls:
            t_name = tc.get("name", "")
            t_args = tc.get("arguments", {})
            logger.info(f"[handle_message] 检测到工具调用: {t_name}({t_args})")
            t_result, ask_text = await tool_dispatcher.execute(
                tool_name=t_name,
                tool_args=t_args,
                user_id=user_id,
                target_id=target_id,
                is_group=is_group,
                session_state=state,
            )
            if ask_text:
                logger.info(f"[handle_message] 高危工具 {t_name}，等待用户确认")
                await text_output.send(target_id, [ask_text], is_group)
                return
            if t_result:
                tool_result_text = t_result
                break

    # ── 步骤4：拉取上下文（并发）────────────────────────────────────────────
    logger.debug("[handle_message] 并发拉取上下文...")
    context = await _pipeline.fetch_context(user_id, content, group_id)

    # ── 步骤5：组装 prompt ───────────────────────────────────────────────────
    logger.debug("[handle_message] 组装 prompt...")
    messages = _pipeline.build_prompt(user_id, content, context, tool_result=tool_result_text)

    # ── 步骤6：调用主 LLM ────────────────────────────────────────────────────
    logger.info("[handle_message] 调用主 LLM...")
    raw_reply = await _pipeline.run_llm(messages)
    logger.info(
        f"[handle_message] LLM 回复长度={len(raw_reply) if raw_reply else 0}"
        f"，预览: {(raw_reply or '')[:60]!r}"
    )

    # ── 步骤7：后处理回复 ────────────────────────────────────────────────────
    segments = response_processor.process(raw_reply, _pipeline.character.name)
    logger.info(f"[handle_message] 后处理完成，共 {len(segments)} 段")
    if not segments:
        logger.warning("[handle_message] LLM 回复经处理后为空，本轮不发送")
        return

    # ── 步骤8：发送回复 ──────────────────────────────────────────────────────
    logger.info(f"[handle_message] 发送到 {'群' if is_group else '私聊'}{target_id}")
    try:
        await text_output.send(target_id, segments, is_group)
    except Exception as e:
        from core.error_handler import log_error
        log_error("main.handle_message.send", e)
        logger.error(f"[handle_message] 发送异常: {type(e).__name__}: {e}")
        return
    logger.info(f"[handle_message] 回复已发送，共 {len(segments)} 段")

    # ── 步骤9：异步后处理（写记忆、TTS 等，不阻塞本轮）──────────────────────
    final_reply = "\n".join(segments)
    asyncio.create_task(
        _pipeline.post_process(user_id, content, final_reply, target_id, is_group)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

async def _reply_with_tool_result(
    tool_result: str,
    user_id: str,
    target_id: str,
    is_group: bool,
):
    """工具确认流程结束后，用完整 prompt 生成角色语气回复"""
    from core.memory import short_term, user_profile, group_context, character_growth
    from core import user_relation, response_processor
    from core.output import text_output
    from core.error_handler import log_error

    group_id = target_id if is_group else None
    context = {
        "history":             short_term.load(user_id),
        "profile":             user_profile.load(user_id),
        "relation":            user_relation.get_relation(user_id),
        "group_context":       group_context.get_recent(group_id),
        "growth_content":      character_growth.load(_pipeline.character.name, user_id),
        "event_search_result": "",
        "lore_entries":        [],
    }
    messages = _pipeline.build_prompt(
        user_id, "（工具已执行，请告知结果）", context, tool_result=tool_result
    )
    try:
        raw_reply = await _pipeline.run_llm(messages)
        segments = response_processor.process(raw_reply, _pipeline.character.name)
        await text_output.send(target_id, segments, is_group)
    except Exception as e:
        log_error("main._reply_with_tool_result", e)



# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    logger.info("=" * 60)
    logger.info("  QQ-SillyTavern Bot 启动中...")
    logger.info("=" * 60)

    _init_modules()

    from core.config_loader import get_config
    cfg = get_config()

    from core import session_state
    session_state.start_cleanup_task()
    logger.info("会话超时清理任务已启动")

    # 主动行为调度器
    from core import scheduler as _scheduler
    _scheduler.start()
    logger.info("主动行为调度器已启动")

    from core import tool_dispatcher, qq_adapter, message_queue
    tool_dispatcher.register_send_callback(qq_adapter.send_message)
    logger.info("工具调度器已初始化")

    message_queue.set_handler(handle_message)
    logger.info("消息队列处理器已注册")

    async def on_message_received(msg: dict):
        await message_queue.enqueue(msg)

    qq_adapter.on_message(on_message_received)
    logger.info("QQ 消息回调已注册")

    tasks = []
    admin_cfg = cfg.get("admin", {})
    if admin_cfg.get("enabled", False) and admin_cfg.get("auto_start", True):
        logger.info("管理面板已启用，正在启动...")
        from admin.admin_server import start_admin_server
        tasks.append(asyncio.create_task(start_admin_server()))
    else:
        logger.info("管理面板未启用（config.admin.enabled 或 auto_start 为 false）")

    logger.info(f"正在连接 NapCat: ws://{cfg['qq']['host']}:{cfg['qq']['port']}")
    logger.info("Bot 已就绪，等待消息...")
    logger.info("=" * 60)

    tasks.append(asyncio.create_task(qq_adapter.connect_and_listen()))

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("收到退出信号，Bot 正在关闭...")
    except Exception as e:
        from core.error_handler import log_error
        log_error("main", e)
        logger.error(f"主循环异常退出: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot 已停止")
