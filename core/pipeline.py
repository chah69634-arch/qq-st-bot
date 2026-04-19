"""
消息处理流水线
把 handle_message 的核心步骤封装成独立方法，main.py 只保留骨架调用。

Pipeline 实例持有角色卡和世界书引擎的引用，在 main.py 中初始化后全程复用。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class Pipeline:
    """
    消息处理流水线，四个核心步骤：

    1. fetch_context  — 并发拉取记忆数据 + 世界书匹配
    2. build_prompt   — 组装完整 prompt 消息列表
    3. run_llm        — 调用 LLM 生成回复（含重试）
    4. post_process   — 写记忆、更新画像、触发角色认知更新
    """

    def __init__(self, character, lore_engine):
        self.character = character
        self.lore_engine = lore_engine
        # Author's Note 动态追加内容（consistency_check 结果），用完即清
        self.author_note_extra: str = ""

    # ──────────────────────────────────────────────────────────────────────────
    # 步骤 1：并发拉取记忆数据 + 世界书匹配
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_context(
        self,
        user_id: str,
        content: str,
        group_id: str | None = None,
    ) -> dict:
        """
        并发拉取所有记忆数据并进行世界书关键词匹配。

        返回 context 字典，供 build_prompt 使用：
        {
            "history":            list[dict],  # 短期对话历史
            "profile":            dict,        # 用户画像
            "relation":           dict,        # 用户关系配置
            "group_context":      str,         # 群消息流（私聊为 ""）
            "growth_content":     str,         # 角色认知文件内容
            "event_search_result": str,        # 事件日志语义搜索结果
            "lore_entries":       list[str],   # 命中的世界书条目
        }
        """
        from core.memory import short_term, user_profile, group_context, event_log, character_growth
        from core import user_relation, llm_client

        # 两个需要 IO 的任务并发进行
        loop = asyncio.get_event_loop()
        event_search_task = asyncio.create_task(
            event_log.search(user_id, content, llm_client)
        )
        profile_future = loop.run_in_executor(None, user_profile.load, user_id)

        # 同步读取（内存/小文件，不值得并发）
        history          = short_term.load(user_id)
        recent_group_ctx = group_context.get_recent(group_id)
        growth_content   = character_growth.load(self.character.name, user_id)
        relation         = user_relation.get_relation(user_id)
        lore_entries     = self.lore_engine.match(content, history)

        # 等待异步任务
        event_search_result = await event_search_task
        profile             = await profile_future

        from core.tools.reminder import get_reminders
        reminders = get_reminders(user_id)
        from core.memory.diary_context import load as _load_diary
        diary_context = _load_diary(user_id)

        logger.debug(
            f"[pipeline.fetch_context] uid={user_id} "
            f"history={len(history)} lore={len(lore_entries)}"
        )
        return {
            "history":             history,
            "profile":             profile,
            "relation":            relation,
            "group_context":       recent_group_ctx,
            "growth_content":      growth_content,
            "event_search_result": event_search_result,
            "lore_entries":        lore_entries,
            "reminders":           reminders,
            "diary_context":       diary_context,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 步骤 2：组装 prompt
    # ──────────────────────────────────────────────────────────────────────────

    def build_prompt(
        self,
        user_id: str,
        content: str,
        context: dict,
        tool_result: str | None = None,
    ) -> list[dict]:
        """
        调用 prompt_builder 组装完整消息列表。
        根据 chat.mode 在 system prompt 末尾追加风格提示。
        author_note_extra 用完后立即清空（只影响本轮）。
        """
        from core import prompt_builder
        from core.config_loader import get_config
        from datetime import datetime
        _now = datetime.now()
        _current_time = (
            _now.strftime("%Y年%m月%d日 %H:%M 星期")
            + ["一", "二", "三", "四", "五", "六", "日"][_now.weekday()]
        )

        messages = prompt_builder.build(
            character=self.character,
            user_id=user_id,
            user_message=content,
            history=context["history"],
            relation=context["relation"],
            profile=context["profile"],
            group_context=context["group_context"],
            growth_content=context["growth_content"],
            event_search_result=context["event_search_result"],
            lore_entries=context["lore_entries"],
            tool_result=tool_result,
            author_note_extra=self.author_note_extra,
            current_time=_current_time,
            reminders=context.get("reminders", []),
            diary_context=context.get("diary_context", ""),
        )
        self.author_note_extra = ""
        return messages

    # ──────────────────────────────────────────────────────────────────────────
    # 步骤 3：调用 LLM（含重试）
    # ──────────────────────────────────────────────────────────────────────────

    async def run_llm(self, messages: list[dict]) -> str:
        """调用 LLM 生成回复，失败自动重试。"""
        from core import llm_client
        from core.error_handler import with_retry

        @with_retry(module_name="pipeline.llm_call")
        async def _call():
            return await llm_client.chat(messages)

        return await _call()

    # ──────────────────────────────────────────────────────────────────────────
    # 步骤 4：异步后处理
    # ──────────────────────────────────────────────────────────────────────────

    async def post_process(
        self,
        user_id: str,
        content: str,
        reply: str,
        target_id: str = "",
        is_group: bool = False,
    ):
        """
        写记忆、更新用户画像、触发角色认知更新、检查角色一致性，
        以及（可选）TTS 语音合成发送。
        每一步独立 try/except，单步失败不影响其他步骤。
        应通过 asyncio.create_task() 调用，不阻塞主流程。
        """
        from core.memory import short_term, user_profile, event_log, character_growth
        from core import character_loader, llm_client
        from core.config_loader import get_config
        from core.error_handler import log_error

        # 短期记忆
        try:
            short_term.append(user_id, "user", content)
            short_term.append(user_id, "assistant", reply)
            logger.debug(f"[pipeline.post_process] 短期记忆已更新: {user_id}")
        except Exception as e:
            log_error("pipeline.post_process.short_term", e)

        # # 请勿打扰状态检测
        # try:
        #     from core.scheduler.triggers.dnd import detect_and_set
        #     detect_and_set(user_id, content)
        # except Exception as e:
        #     log_error("pipeline.post_process.dnd", e)

        # 事件日志
        try:
            event_log.append(user_id, "user", content)
            event_log.append(user_id, "assistant", reply)
            logger.debug(f"[pipeline.post_process] 事件日志已追加: {user_id}")
        except Exception as e:
            log_error("pipeline.post_process.event_log", e)

        # 用户画像（每 N 轮触发一次）
        try:
            cfg = get_config()
            every_n = cfg.get("memory", {}).get("summary_every_n_rounds", 20)
            history_len = len(short_term.load(user_id))
            if history_len > 0 and history_len % every_n == 0:
                recent = short_term.load(user_id)[-every_n * 2:]
                await user_profile.extract_and_update(user_id, recent)
                logger.info(f"[pipeline.post_process] 用户画像更新触发: {user_id}")
        except Exception as e:
            log_error("pipeline.post_process.profile", e)

        # 角色认知更新（每 20 轮触发一次）
        try:
            if character_growth.should_update(user_id):
                recent_logs = event_log.get_recent_days(user_id, days=3)
                asyncio.create_task(
                    character_growth.update(
                        self.character.name, user_id, recent_logs, llm_client
                    )
                )
                logger.info(f"[pipeline.post_process] 角色认知更新已触发: {user_id}")
        except Exception as e:
            log_error("pipeline.post_process.character_growth", e)

        # 角色一致性检测
        try:
            check_result = await character_loader.consistency_check(self.character, reply)
            if not check_result.get("ok"):
                issue = check_result.get("issue", "")
                if issue:
                    self.author_note_extra = issue
                    logger.info(
                        f"[pipeline.post_process] 一致性问题，下轮追加纠偏: {issue}"
                    )
        except Exception as e:
            log_error("pipeline.post_process.consistency", e)

        # TTS 语音合成并发送（tts.enabled=true 时触发，失败不影响已发出的文字消息）
        try:
            from core.config_loader import get_config as _cfg
            if target_id and _cfg().get("tts", {}).get("enabled", False):
                asyncio.create_task(self._send_tts(reply, target_id, is_group))
        except Exception as e:
            log_error("pipeline.post_process.tts", e)

        # 表情包（小概率触发）
        try:
            if target_id:
                from core.output.sticker import maybe_send_sticker
                asyncio.create_task(
                    maybe_send_sticker(reply, target_id, is_group)
                )
        except Exception as e:
            log_error("pipeline.post_process.sticker", e)

    async def _send_tts(self, text: str, target_id: str, is_group: bool):
        """异步 TTS 合成并通过 NapCat 发送语音消息，失败只记日志"""
        from core.output.voice_adapter import synthesize, send_voice
        from core.config_loader import get_config
        from core.error_handler import log_error
        try:
            emotion = "neutral"
            if get_config().get("tts", {}).get("emotion_enabled", False):
                from core import llm_client
                emotion = await llm_client.detect_emotion(text)
                logger.debug(f"[pipeline.tts] 检测到情绪: {emotion}")

            audio_bytes = await synthesize(text, emotion)
            if audio_bytes:
                await send_voice(target_id, audio_bytes, is_group)
                logger.info(f"[pipeline.tts] 语音已发送 -> {target_id} (emotion={emotion})")
            else:
                logger.debug("[pipeline.tts] synthesize 返回 None，跳过语音发送")
        except Exception as e:
            log_error("pipeline._send_tts", e)
