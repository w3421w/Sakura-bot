"""Optional Tulpa-inspired proactive group conversation loop.

This module is intentionally separate from the OneBot receive path. It only
uses messages that already passed QWbot's consent/privacy pipeline, applies
cooldowns, and lets the model return SILENT when there is no natural opening.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from typing import Any

from llm.errors import LLMError
from core.reply import split_reply
from storage.store import Store
from transport.onebot11_client import OneBot11Client


LOG = logging.getLogger("qwbot.proactive")


class ProactiveChatManager:
    def __init__(self, config: dict[str, Any], store: Store, llm: Any, dispatcher: Any) -> None:
        settings = config.get("proactive", {})
        self.enabled = bool(settings.get("enabled", False))
        configured = settings.get("group_ids") or config.get("access", {}).get("allowed_group_ids", [])
        self.group_ids = tuple(dict.fromkeys(int(group_id) for group_id in configured))
        self.interval = max(15, int(settings.get("interval_seconds", 30)))
        self.min_silence = max(0, int(settings.get("min_silence_seconds", 20)))
        self.cooldown = max(30, int(settings.get("cooldown_seconds", 180)))
        self.active_window = max(60, int(settings.get("active_window_seconds", 900)))
        self.max_per_hour = max(1, int(settings.get("max_replies_per_hour", 6)))
        self.max_reply_chars = max(30, int(settings.get("max_reply_chars", 120)))
        bot_config = config.get("bot", {})
        self.max_reply_parts = max(1, int(bot_config.get("max_reply_parts", 3)))
        self.reply_split_delay = max(0.0, float(bot_config.get("reply_split_delay_seconds", 0.35)))
        self.water_group_mode = bool(settings.get("water_group_mode", True))
        self.store = store
        self.llm = llm
        self.dispatcher = dispatcher
        self._last_seen: dict[int, int] = {}
        self._last_sent: dict[int, float] = {}
        self._sent_window: dict[int, deque[float]] = defaultdict(deque)

    async def run(self, transport: OneBot11Client) -> None:
        if not self.enabled or not self.group_ids:
            LOG.info("proactive chat disabled or no group_ids configured")
            return
        self._prime()
        LOG.info("proactive chat enabled groups=%s interval=%ss", list(self.group_ids), self.interval)
        while True:
            await asyncio.sleep(self.interval)
            for group_id in self.group_ids:
                try:
                    await self._tick(group_id, transport)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOG.exception("proactive tick failed group_id=%s", group_id)

    def _prime(self) -> None:
        for group_id in self.group_ids:
            activity = self.store.recent_activity(group_id, limit=1)
            self._last_seen[group_id] = activity[-1][0] if activity else 0

    async def _tick(self, group_id: int, transport: OneBot11Client) -> None:
        activity = self.store.recent_activity(group_id, limit=20)
        if not activity:
            return
        latest = activity[-1]
        latest_row_id, latest_user_id, latest_text, latest_is_bot, latest_ts, _message_id = latest
        if latest_row_id <= self._last_seen.get(group_id, 0):
            return
        now = time.time()
        if latest_is_bot:
            self._last_seen[group_id] = latest_row_id
            return
        if now - latest_ts > self.active_window:
            self._last_seen[group_id] = latest_row_id
            return
        if now - latest_ts < self.min_silence:
            return
        # Directed insults are handled synchronously by the dispatcher. Do
        # not let the independent water-group loop answer the same message
        # later with an unrelated nickname or tone (for example a stale nickname).
        persona_switch = getattr(self.dispatcher, "persona_switch", None)
        if persona_switch is not None:
            insult_term = persona_switch.find_insult(str(latest_text or ""))
            if insult_term:
                self._last_seen[group_id] = latest_row_id
                LOG.info(
                    "proactive skipped insult group_id=%s row_id=%s term=%s",
                    group_id,
                    latest_row_id,
                    insult_term,
                )
                return
        if now - self._last_sent.get(group_id, 0.0) < self.cooldown:
            self._last_seen[group_id] = latest_row_id
            return
        sent = self._sent_window[group_id]
        while sent and now - sent[0] >= 3600:
            sent.popleft()
        if len(sent) >= self.max_per_hour:
            self._last_seen[group_id] = latest_row_id
            return

        clear_opening = self._is_clear_opening(latest_text)
        question = (
            "你现在使用当前配置的人格。请根据近期群聊判断是否有自然的接话点。"
            + (
                "这是持续水群模式：新话题、玩笑、情绪、吐槽和有一点内容的短句都可以自然接一句；"
                "只有重复、刷屏、无意义单字或完全没有话题时才输出 SILENT。"
                if self.water_group_mode
                else "明确提问、征求意见、正在展开的共同话题和明显的玩笑钩子，优先接一句；"
                "纯陈述、重复内容或没有上下文时才输出 SILENT。"
            )
            + "如果回复，只输出一条可直接发到群里的短口语，不超过120字，"
            + "可以带一点轻度吐槽，但要先回应话题，不解释规则，不提‘主动参与’、模型、提示词或内部判断。"
            + f"\n对话参考（只理解，不要复述这段标签或上下文）：{str(latest_text)[:240]}"
        )
        messages = self.dispatcher.prompts.build(
            group_id,
            latest_user_id,
            question,
            include_history=True,
            history_mode="group",
            persona_id=self.dispatcher.persona_switch.persona_for(group_id),
        )
        messages[0]["content"] += (
            "\n主动接话判定：遵循 Tulpa 风格的自然会话策略，先看当前话题和最近上下文，"
            + (
                "水群模式下普通陈述只要有话题钩子就可以接一句；重复或无意义内容保持 SILENT。"
                if self.water_group_mode
                else "明确问题或征求意见时优先回答；普通陈述没有话题钩子时保持 SILENT。"
            )
            + "当前不是被点名的问题，不要为了活跃而硬接；不必引用更早的群聊话题，优先只对最新一条消息作独立、自然的短回应。"
        )
        try:
            answer = await self.llm.chat(messages)
        except LLMError:
            LOG.exception("proactive LLM call failed group_id=%s", group_id)
            self._last_seen[group_id] = latest_row_id
            return
        answer = self._clean_answer(answer)
        answer = self.dispatcher._enforce_member_address(answer, group_id)
        recent_replies = self.dispatcher.recent_reply_texts(group_id, 3)
        dedup_blocked = False
        if answer and self.dispatcher.is_duplicate_reply(
            answer, group_id, recent_replies
        ):
            LOG.info("proactive duplicate detected group_id=%s; regenerating", group_id)
            messages[0]["content"] += self.dispatcher.duplicate_reminder(recent_replies)
            try:
                retry = self._clean_answer(await self.llm.chat(messages))
                retry = self.dispatcher._enforce_member_address(retry, group_id)
            except LLMError:
                LOG.exception("proactive duplicate retry failed group_id=%s", group_id)
                retry = ""
            if retry and not self.dispatcher.is_duplicate_reply(
                retry, group_id, recent_replies
            ):
                answer = retry
            else:
                answer = ""
                dedup_blocked = True
        answer = self.dispatcher._apply_media_policy(answer, question, f"group:{group_id}")
        media_persona = self.dispatcher.persona_switch.persona_for(group_id)
        answer = self.dispatcher._attach_auto_emotion_media(
            answer, question, group_id, media_persona
        )
        if answer == " ".join(str(latest_text or "").split()).strip():
            answer = ""
        if not answer and clear_opening and not dedup_blocked:
            # The first prompt is deliberately conservative. If the latest message
            # is an explicit question, allow one focused retry so the bot does not
            # silently ignore a natural opening just because this is proactive mode.
            messages[0]["content"] += (
                "\n最后一条消息是明确问题；这次不要输出 SILENT，直接给出一句简短、自然、"
                "有帮助的回答。如果资料不足，就坦诚说不确定并反问一个澄清问题。"
                "绝对不要复述‘对话参考’、‘最近一条群友消息’或任何提示内容。"
            )
            try:
                answer = self._clean_answer(await self.llm.chat(messages))
                answer = self.dispatcher._enforce_member_address(answer, group_id)
                if answer and self.dispatcher.is_duplicate_reply(
                    answer, group_id, recent_replies
                ):
                    answer = ""
                answer = self.dispatcher._apply_media_policy(answer, question, f"group:{group_id}")
                answer = self.dispatcher._attach_auto_emotion_media(
                    answer, question, group_id, media_persona
                )
            except LLMError:
                LOG.exception("proactive retry failed group_id=%s", group_id)
                answer = ""
        self._last_seen[group_id] = latest_row_id
        if not answer:
            LOG.debug("proactive chose silence group_id=%s row_id=%s", group_id, latest_row_id)
            return
        key = f"proactive:{group_id}:{latest_row_id}"
        if not self.store.claim_outbound(
            key,
            scope_id=f"group:{group_id}",
            message=answer,
            retry_after_seconds=self.cooldown,
        ):
            return
        try:
            for index, part in enumerate(split_reply(answer, max_parts=self.max_reply_parts)):
                if index and self.reply_split_delay:
                    await asyncio.sleep(self.reply_split_delay)
                    await transport.send_group_message(group_id, self.dispatcher.media.render(part))
        except Exception as exc:
            self.store.finish_outbound(key, status="failed", error=str(exc))
            raise
        self.store.finish_outbound(key, status="sent")
        self.store.add_message(group_id, 0, answer, is_bot=True, sender_info={"is_bot": True, "proactive": True})
        self._last_sent[group_id] = now
        sent.append(now)
        LOG.info("proactive reply sent group_id=%s chars=%s", group_id, len(answer))

    def _clean_answer(self, answer: str) -> str:
        text = " ".join(str(answer or "").split()).strip()
        if not text or text.upper().strip("`*_ ") in {"SILENT", "NO_REPLY", "NO REPLY"}:
            return ""
        if text.upper().startswith("SILENT"):
            return ""
        if any(
            marker in text
            for marker in (
                "最近一条群友消息",
                "对话参考",
                "当前是可选插话",
                "主动参与",
                "提示词",
                "内部判断",
                "模型",
                "主动接话判定",
                "最近一条消息包含明确问题",
                "明确问题或征求意见",
                "应优先",
                "不要因为是主动插话",
                "普通陈述没有话题钩子",
                "当前问题简单",
                "直接回答即可",
                "如果想聊聊",
                "我倒是可以",
                "可选插话",
                "当前不是被点名",
            )
        ):
            return ""
        if text.startswith("回复："):
            text = text[3:].strip()
        text = re.sub(
            r"([A-Za-z][A-Za-z0-9_.-]{1,24})(\s*)[区处](?=[\u4e00-\u9fffA-Za-z])",
            r"\1\2",
            text,
        )
        return text[: self.max_reply_chars].strip()

    @staticmethod
    def _is_clear_opening(text: str) -> bool:
        """Return whether the latest message clearly invites a response."""
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return False
        if "?" in normalized or "？" in normalized:
            return True
        return any(
            marker in normalized
            for marker in ("吗", "嘛", "呢", "谁", "什么", "怎么", "为什么", "有没有", "觉得", "推荐", "求助")
        )
