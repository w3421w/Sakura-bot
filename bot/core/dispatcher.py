"""OneBot -> privacy -> Store -> memory/RAG -> configured LLM pipeline."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from core.commands import CommandRouter
from llm.errors import LLMError
from llm.prompt_builder import PromptBuilder
from memory.extractor import MemoryExtractor
from storage.store import Store
from transport.events import OneBotEvent, mentioned, parse_event, text_only
from transport.onebot11_client import OneBot11Client
from web.search import SearchClient, SearchResponse
from core.tulpa_compat import TulpaPolicy
from core.reply import split_reply
from core.persona_switch import PersonaSwitchManager
from knowledge.deck_advisor import DeckAdvisor
from core.persona_lines import (
    BLACK_INSULT_LINES,
    BLACK_SWITCH_LINES,
    FIRST_INSULT_LINES,
    FORCE_BLACK_LINES,
    FORCE_SAKURA_LINES,
    SECOND_INSULT_LINES,
    LineRotator,
)
from core.emotion_media import EmotionMediaSelector
from transport.media import MediaRegistry


LOG = logging.getLogger("qwbot.dispatcher")

BLACK_REPLY_CONTRACT = (
    "\n【当前人格：黑樱｜硬性要求】"
    "你已经处于黑樱状态。你不是原版樱，禁止撒娇、赔笑、照顾式关心、主动道歉；"
    "少用“呢/哦/呀/嘛”做软收尾；不要连续称呼“前辈”；"
    "不要再说“第一次/第二次/第三次”这类计数，也不要用“请别再这样叫我”“这样说我会难过”"
    "这类原版樱警告句式；回复一到两句，尽量不超过40字，切换台词不超过60字；冷、平、短、留白。"
    "对方挑衅时像毒蛇一样安静收紧：先接一句，再冷下来；可以有礼、带笑，但内容要让人发冷。"
    "参考我妻由乃的排他、时崎狂三的从容、蛇喰梦子的兴奋；只取气质，不复制台词。"
    "称呼群成员只用“短称+前辈”，禁止哥/姐/叔/姨/老师/学长/学姐/先生/小姐/老板等后缀；"
    "历史中标记为“[pop子]”或“原版樱”的旧回复只作事实参考，不要模仿语气。"
)

ADDRESS_SUFFIXES = (
    "前辈", "老师", "学长", "学姐", "师兄", "师姐", "先生", "小姐", "老板", "哥", "姐", "叔", "姨",
)


class MessageDispatcher:
    def __init__(
        self,
        config: dict[str, Any],
        store: Store,
        llm: Any,
        persona_path: str,
    ) -> None:
        self.config = config
        self.store = store
        self.llm = llm
        self.prompts = PromptBuilder(store, persona_path, config)
        self.memory_extractor = MemoryExtractor(config)
        self.commands = CommandRouter(store, config, persona_catalog=self.prompts.persona_catalog)
        self.policy = TulpaPolicy(config)
        access = config.get("access", {})
        self.allowed_groups: set[int] = set(access.get("allowed_group_ids", set()))
        self.group_consent_confirmed = bool(access.get("group_consent_confirmed", False))
        self.require_user_consent = bool(access.get("require_user_consent", True))
        self.allow_private = bool(access.get("allow_private_messages", False))
        self.max_reply_chars = int(config.get("bot", {}).get("max_reply_chars", 600))
        bot_config = config.get("bot", {})
        self.max_reply_parts = max(1, int(bot_config.get("max_reply_parts", 3)))
        self.reply_split_delay = max(0.0, float(bot_config.get("reply_split_delay_seconds", 0.35)))
        transport_config = config.get("transport", {})
        self.event_dedup_ttl = int(transport_config.get("event_dedup_ttl_seconds", 7 * 86400))
        self.outbound_retry_after = int(transport_config.get("outbound_retry_after_seconds", 30))
        search_config = config.get("search", {})
        self.search = SearchClient(search_config)
        self.search_auto = bool(search_config.get("auto", True))
        self.media = MediaRegistry(config.get("assets", {}))
        media_config = config.get("media", {})
        self.auto_emotion_media = bool(media_config.get("auto_emotion_enabled", True))
        self.auto_media_cooldown_seconds = max(
            30, int(media_config.get("auto_media_cooldown_seconds", 600))
        )
        self._last_auto_media_at: dict[str, float] = {}
        self.emotion_media = EmotionMediaSelector(self.media, media_config)
        try:
            self.deck_advisor = DeckAdvisor(config)
        except Exception:
            LOG.exception("Hearthstone deck advisor failed to initialize")
            self.deck_advisor = None
        self.persona_switch = PersonaSwitchManager(config, store)
        self.lines = LineRotator()
        self._last_black_reply: dict[int, str] = {}
        self._black_locks: dict[int, asyncio.Lock] = {}
        self._member_address_cache: dict[int, dict[str, str]] = {}
        raw_aliases = config.get("persona_switch", {}).get("address_aliases", {})
        self.address_aliases = (
            {
                str(source).strip(): str(target).strip()
                for source, target in raw_aliases.items()
                if str(source).strip() and str(target).strip()
            }
            if isinstance(raw_aliases, dict)
            else {}
        )
        self.account_id: int | None = None
        LOG.info(
            "dispatcher ready allowed_group_ids=%s allow_private_messages=%s group_consent_confirmed=%s",
            sorted(self.allowed_groups),
            self.allow_private,
            self.group_consent_confirmed,
        )

    async def _sync_persona_avatar(
        self,
        transport: OneBot11Client,
        group_id: int,
        mode: str,
        *,
        reason: str,
    ) -> None:
        avatar = self.persona_switch.avatar_for(mode)
        LOG.info(
            "persona switched group_id=%s mode=%s reason=%s avatar=%s",
            group_id,
            mode,
            reason,
            avatar,
        )
        if avatar is None or not avatar.exists():
            LOG.warning("persona avatar unavailable mode=%s path=%s", mode, avatar)
            return
        try:
            await transport.set_qq_avatar(str(avatar))
            LOG.info("QQ avatar switch requested mode=%s path=%s", mode, avatar)
        except Exception:
            LOG.exception("QQ avatar switch failed mode=%s path=%s", mode, avatar)

    @staticmethod
    async def _wait_for_connection(transport: OneBot11Client, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            health = getattr(transport, "health", None)
            if callable(health):
                try:
                    if health().get("connected"):
                        return True
                except Exception:
                    pass
            await asyncio.sleep(1)
        return False

    async def persona_restore_loop(self, transport: OneBot11Client) -> None:
        """Restore persisted avatars on startup and expire black mode on quiet."""
        # Expire first, so a bot that was offline past the quiet window does not
        # briefly re-apply the black avatar before the loop restores it.
        restored_on_start = self.persona_switch.restore_expired()
        persisted_black = [
            group_id
            for group_id, state in self.persona_switch.states().items()
            if state.mode == "black"
        ]
        if (restored_on_start or persisted_black) and await self._wait_for_connection(
            transport
        ):
            for group_id in restored_on_start:
                await self._sync_persona_avatar(
                    transport,
                    group_id,
                    "sakura",
                    reason="启动时发现黑樱已超过30分钟",
                )
            for group_id in persisted_black:
                if self.persona_switch.state(group_id).mode == "black":
                    await self._sync_persona_avatar(
                        transport,
                        group_id,
                        "black",
                        reason="启动恢复持久化的黑樱状态",
                    )
        while True:
            await asyncio.sleep(30)
            for group_id in self.persona_switch.restore_expired():
                await self._sync_persona_avatar(
                    transport,
                    group_id,
                    "sakura",
                    reason="黑樱30分钟到期后自动恢复",
                )

    @staticmethod
    def _llm_mode(question: str) -> str:
        """Choose a cheap chat profile for water-chat and reasoning when needed."""
        text = re.sub(r"\s+", " ", str(question or "")).strip()
        if not text:
            return "fast"
        if re.match(r"^/(?:深度|推理|分析)\b", text, flags=re.IGNORECASE):
            return "reasoning"
        if len(text) >= 80:
            return "reasoning"
        reasoning_terms = (
            "分析", "比较", "对比", "为什么", "如何", "解释", "总结", "规划", "方案",
            "推理", "计算", "代码", "调试", "评价", "预测", "证据", "优缺点", "区别",
            "判断", "复盘", "论证", "综合", "利弊", "原理", "步骤",
        )
        return "reasoning" if any(term in text for term in reasoning_terms) else "fast"

    @staticmethod
    def _normalize_reply_identity(text: str) -> str:
        """Normalize a reply for exact-repeat detection, ignoring media/punctuation."""
        stripped = re.sub(
            r"\[(?:image|sticker|face):[^\]]+\]", "", str(text or ""), flags=re.IGNORECASE
        )
        stripped = re.sub(r"[\s，,。.!！？?…、；;：:\"'“”‘’]+", "", stripped)
        return stripped.casefold()

    def recent_reply_texts(self, scope_id: int, limit: int = 3) -> list[str]:
        try:
            return self.store.recent_bot_texts(int(scope_id), limit)
        except Exception:
            LOG.exception("recent reply lookup failed scope_id=%s", scope_id)
            return []

    def is_duplicate_reply(
        self,
        text: str,
        scope_id: int,
        recent: list[str] | None = None,
    ) -> bool:
        normalized = self._normalize_reply_identity(text)
        # Very short replies such as “嗯”/“好的” are natural chat and are exempt.
        if len(normalized) < 6:
            return False
        candidates = recent if recent is not None else self.recent_reply_texts(scope_id, 3)
        return any(
            normalized == self._normalize_reply_identity(item) for item in candidates
        )

    @staticmethod
    def duplicate_reminder(recent: list[str]) -> str:
        samples = [str(item).strip()[:60] for item in recent if str(item).strip()][:3]
        return (
            "\n【避免重复】你最近已经说过："
            + " / ".join(samples)
            + "。这次必须换一种说法，不要复述，也不要只改一两个词。"
        )

    @staticmethod
    def _normalize_black_text(text: str) -> str:
        stripped = re.sub(
            r"\[(?:image|sticker|face):[^\]]+\]", "", str(text or ""), flags=re.IGNORECASE
        )
        return re.sub(r"[\s，,。.!！？?…\"“”'‘’]+", "", stripped).casefold()

    @staticmethod
    def _clean_black_reply(raw: str, *, switched: bool) -> str:
        """Strip media/meta from a model reply and keep it short and in-voice."""
        text = re.sub(r"\[CQ:[^\]]+\]", "", str(raw or ""), flags=re.IGNORECASE)
        text = re.sub(
            r"\[(?:image|sticker|face):[^\]]+\]", "", text, flags=re.IGNORECASE
        )
        text = text.strip().strip('"“”\'‘’')
        text = re.sub(r"^(?:黑樱|回复|答)\s*[:：]\s*", "", text)
        text = " ".join(text.split())
        if not text:
            return ""
        folded = text.casefold()
        blocked = (
            "作为ai",
            "作为 ai",
            "抱歉",
            "无法回答",
            "无法提供",
            "无法满足",
            "系统提示",
            "提示词",
            "人格设定",
            "语言模型",
            "人工智能",
            "请别再这样叫我",
            "这样说我会难过",
            "可别让樱把这句话记住",
            "我已经提醒过前辈了",
            "silent",
            "no_reply",
        )
        if any(token in folded for token in blocked):
            return ""
        if not switched and re.search(r"第[一二三四五六七八九十0-9]+次", text):
            return ""
        limit = 80 if switched else 120
        if len(text) > limit:
            head = text[:limit]
            cut = max(head.rfind("。"), head.rfind("！"), head.rfind("？"))
            text = head[: cut + 1] if cut >= 20 else head.rstrip("，,。.!！？? ")
        return text.strip()

    def _black_fallback(self, group_id: int, *, switched: bool) -> str:
        recent = self.recent_reply_texts(group_id, 3)
        if switched:
            index = max(0, self.persona_switch.state(group_id).switch_count - 1)
            line = BLACK_SWITCH_LINES[index % len(BLACK_SWITCH_LINES)]
            answer = line.render()
        else:
            answer = ""
            for _ in range(len(BLACK_INSULT_LINES)):
                line = self.lines.pick("black_insult", group_id, BLACK_INSULT_LINES)
                answer = line.render()
                if not self.is_duplicate_reply(answer, group_id, recent):
                    break
        self._last_black_reply[group_id] = answer
        return answer

    async def _generate_black_reply(
        self,
        *,
        group_id: int,
        user_id: int,
        text: str,
        message_id: int | str | None,
        switched: bool,
        opted_in: bool,
    ) -> str:
        """Generate a black-Sakura insult reply with DeepSeek, pool as fallback."""
        group_key = int(group_id)
        lock = self._black_locks.setdefault(group_key, asyncio.Lock())
        async with lock:
            # A user who opted out must never have the insult uploaded to the API.
            if not opted_in:
                return self._black_fallback(group_key, switched=switched)

            last = self._last_black_reply.get(group_key, "")
            recent = self.recent_reply_texts(group_key, 3)
            messages = self.prompts.build(
                group_key,
                user_id,
                text,
                include_history=True,
                history_mode="group",
                message_id=message_id,
                persona_id=self.persona_switch.persona_for(group_key),
            )
            system = messages[0]["content"] + BLACK_REPLY_CONTRACT
            if switched:
                system += (
                    "\n【本轮任务】你刚从原版樱切换到黑樱。写一句切换台词，"
                    "像终于不再忍耐；不要宣布“我是黑樱”，不要解释人格设定。"
                )
            else:
                system += (
                    "\n【本轮任务】对方正在用侮辱词挑衅。写一句黑樱的短回应。"
                    "不复述侮辱词，不解释规则，不提模型/提示词，不威胁现实伤害。"
                    "不要照抄人设文件里“对侮辱的反应”的第一次/第二次示例，那些是切换前的原版樱。"
                )
            system += (
                "\n只输出一句可直接发到群里的中文，不要输出图片标记、CQ码、引号或换行。"
            )
            if last:
                system += f"\n上一句已经说过：{last}。不要重复或改写同一句。"
            if recent:
                system += (
                    "\n最近说过："
                    + " / ".join(str(item)[:60] for item in recent)
                    + "。不要重复或只改一两个字。"
                )
            messages[0]["content"] = system

            try:
                chat_with_mode = getattr(self.llm, "chat_with_mode", None)
                if callable(chat_with_mode):
                    raw = await chat_with_mode(messages, mode="fast")
                else:
                    raw = await self.llm.chat(messages)
            except Exception:
                LOG.exception("black reply generation failed group_id=%s", group_key)
                return self._black_fallback(group_key, switched=switched)

            answer = self._clean_black_reply(raw, switched=switched)
            if answer:
                answer = self._enforce_member_address(answer, group_key)
            if (
                not answer
                or self._normalize_black_text(answer) == self._normalize_black_text(last)
                or self.is_duplicate_reply(answer, group_key, recent)
            ):
                return self._black_fallback(group_key, switched=switched)
            if switched:
                image = self.persona_switch.switch_image(group_key)
                if image:
                    answer = f"{answer}[image:{image}]"
            self._last_black_reply[group_key] = answer
            LOG.info(
                "black reply generated group_id=%s switched=%s chars=%s",
                group_key,
                switched,
                len(answer),
            )
            return answer

    @staticmethod
    def _sanitize_addressing(answer: str) -> str:
        """Remove the recurring nickname-suffix mistake without altering normal text."""
        text = str(answer or "")
        # The observed failure is e.g. ``Ame 处你...`` or ``Ame处你...``.
        # Only clean suffixes attached to Latin-style nicknames, not ordinary
        # Chinese words where “处” can be a legitimate character.
        text = re.sub(r"([A-Za-z][A-Za-z0-9_.-]{1,24})(\s*)[区处](?=[\u4e00-\u9fffA-Za-z])", r"\1\2", text)
        # Do not stack the generic “前辈” suffix onto a nickname that already
        # contains a kinship/title suffix, e.g. “甲哥前辈” -> “甲哥”.
        return re.sub(
            r"([\u4e00-\u9fffA-Za-z0-9_.-]{1,24}?)(哥|姐|叔|姨|老师|学长|学姐|师兄|师姐|先生|小姐|老板|前辈)前辈",
            r"\1\2",
            text,
        )

    def _member_address_map(self, group_id: int) -> dict[str, str]:
        """Map configured legacy honorific forms to “短称+前辈”."""
        group_key = int(group_id)
        cached = self._member_address_cache.get(group_key)
        if cached is not None:
            return cached
        mapping: dict[str, str] = dict(self.address_aliases)
        try:
            profiles = self.store.list_user_profiles(group_key)
        except Exception:
            LOG.exception("member address map failed group_id=%s", group_key)
            profiles = []
        for row in profiles:
            tokens: list[str] = []
            for field in (row.get("preferred_name"), row.get("nickname")):
                text = str(field or "").strip()
                if not text:
                    continue
                tokens.extend(
                    part.strip()
                    for part in re.split(r"[/、,，\s]+", text)
                    if part.strip()
                )
            for token in tokens:
                base = token
                for suffix in ADDRESS_SUFFIXES:
                    if token.endswith(suffix) and len(token) > len(suffix):
                        base = token[: -len(suffix)]
                        break
                if not base or len(base) > 12:
                    continue
                # Generate the honorific forms the model is likely to use.
                for suffix in ADDRESS_SUFFIXES:
                    source = f"{base}{suffix}"
                    target = f"{base}前辈"
                    if source != target:
                        mapping[source] = target
                if token != base:
                    mapping[token] = f"{base}前辈"
        self._member_address_cache[group_key] = mapping
        return mapping

    def _enforce_member_address(self, text: str, group_id: int) -> str:
        result = str(text or "")
        if not result:
            return result
        mapping = self._member_address_map(group_id)
        for source in sorted(mapping, key=len, reverse=True):
            if source in result:
                result = result.replace(source, mapping[source])
        return re.sub(r"前辈(?:前辈)+", "前辈", result)

    def _apply_media_policy(self, answer: str, question: str, scope_id: str) -> str:
        """Allow one emotion-matched image, with explicit requests bypassing cooldown."""
        text = str(answer or "")
        matches = list(re.finditer(r"\[image:([^\]\s]{1,120})\]", text, flags=re.IGNORECASE))
        if not matches:
            return text
        explicit = bool(re.search(r"图片|图|表情包|立绘|发图|发一张|发个|来张|哪张|那张", str(question or "")))
        now = time.monotonic()
        restricted = {
            "sakura_user_playful_flirt", "sakura_user_teasing", "sakura_user_flower_playful",
            "sakura_user_dark_threat", "sakura_user_dark_sitting", "sakura_user_night_calm",
            "sakura_user_bar_dress",
        }
        black_names = {
            "black_sakura_calm_closed_eye", "black_sakura_dark_smile", "black_sakura_invite",
            "black_sakura_manic_laugh", "black_sakura_warning", "black_sakura_provoking",
        }
        black_cues = {
            "black_sakura_calm_closed_eye": ("沉默", "受伤", "难过", "记住", "我听见", "安静", "不想解释"),
            "black_sakura_dark_smile": ("呵呵", "冷笑", "哦？", "调皮", "介意", "吃醋", "占有", "回来", "惩罚", "记住"),
            "black_sakura_invite": ("黑樱", "圣杯", "影", "剧情", "继续说", "陪前辈"),
            "black_sakura_manic_laugh": ("哈哈", "呵呵呵", "疯狂", "高潮", "失控", "强烈"),
            "black_sakura_warning": ("第三次", "警告", "别再", "适可而止", "停止", "边界", "不喜欢", "越界", "惩罚"),
            "black_sakura_provoking": ("挑衅", "说完", "继续", "再说", "哦？", "调皮", "惩罚", "把话说完", "逼近"),
        }
        emotion_context = f"{question or ''} {text}".casefold()
        last = self._last_auto_media_at.get(scope_id, 0.0)
        cooldown_active = (now - last) < self.auto_media_cooldown_seconds
        kept = False

        def replace(match: re.Match[str]) -> str:
            nonlocal kept
            name = match.group(1)
            if kept or self.media.resolve("image", name) is None:
                return ""
            if not explicit and (not self.auto_emotion_media or cooldown_active or name.casefold() in restricted):
                return ""
            lowered_name = name.casefold()
            if not explicit and lowered_name in black_names:
                cues = black_cues.get(lowered_name, ())
                if cues and not any(cue.casefold() in emotion_context for cue in cues):
                    return ""
            kept = True
            return match.group(0)

        filtered = re.sub(r"\[image:([^\]\s]{1,120})\]", replace, text, flags=re.IGNORECASE)
        if kept and not explicit:
            self._last_auto_media_at[scope_id] = now
        return re.sub(r"[ \t]{2,}", " ", filtered).strip()

    def _attach_auto_emotion_media(
        self,
        answer: str,
        question: str,
        scope_id: str | int,
        persona: str,
    ) -> str:
        """Add one local emotion image when the model did not already choose one."""
        if not self.auto_emotion_media or not answer:
            return answer
        if re.search(r"\[(?:image|sticker|face):", answer, flags=re.IGNORECASE):
            return answer
        if len(answer) > 160:
            return answer
        now = time.monotonic()
        if now - self._last_auto_media_at.get(scope_id, 0.0) < self.auto_media_cooldown_seconds:
            return answer
        try:
            name = self.emotion_media.pick(f"{question}\n{answer}", persona, scope_id)
        except Exception:
            LOG.exception("auto emotion media selection failed scope=%s", scope_id)
            return answer
        if not name:
            return answer
        self._last_auto_media_at[scope_id] = now
        LOG.info(
            "auto emotion media selected scope=%s persona=%s name=%s",
            scope_id,
            persona,
            name,
        )
        return f"{answer}[image:{name}]"

    async def handle_raw(self, transport: OneBot11Client, raw: str | bytes) -> None:
        data = parse_event(raw)
        if data is None:
            LOG.warning("ignored invalid OneBot JSON")
            return
        LOG.info(
            "OneBot event parsed post_type=%s message_type=%s user_id=%s group_id=%s message_id=%s",
            data.post_type,
            data.message_type,
            data.user_id,
            data.group_id,
            data.message_id,
        )
        if data.post_type == "message":
            LOG.info(
                "OneBot message event user_id=%s group_id=%s message_id=%s message=%r",
                data.user_id,
                data.group_id,
                data.message_id,
                data.message,
            )
        if "echo" in data.raw:
            if data.raw.get("status") != "ok" or int(data.raw.get("retcode", 0)) != 0:
                LOG.error("OneBot action failed: %s", str(data.raw)[:500])
            return
        if data.self_id is not None:
            if self.account_id is None:
                self.account_id = data.self_id
                LOG.info("OneBot account verified self_id=%s", self.account_id)
            elif data.self_id != self.account_id:
                LOG.error(
                    "event filtered: OneBot account changed expected=%s actual=%s",
                    self.account_id,
                    data.self_id,
                )
                return
        if not data.is_group_message and not (self.allow_private and data.is_private_message):
            LOG.info(
                "event filtered: unsupported or disabled message scope post_type=%s message_type=%s",
                data.post_type,
                data.message_type,
            )
            return
        if data.user_id is not None and data.self_id is not None and data.user_id == data.self_id:
            LOG.info("event filtered: self message user_id=%s", data.user_id)
            return
        if not self.policy.scope_allowed(data):
            LOG.warning(
                "event filtered: scope is not authorized conversation_id=%s allowed_groups=%s allowed_private_users=%s",
                data.conversation_id,
                sorted(self.allowed_groups),
                sorted(self.policy.allowed_private_users),
            )
            return
        if not self.store.claim_event(
            self.policy.event_key(data),
            event_type=data.post_type or "unknown",
            scope_id=data.conversation_id,
            message_id=data.message_id,
            ttl_seconds=self.event_dedup_ttl,
        ):
            LOG.info("event filtered: duplicate event_key=%s", self.policy.event_key(data))
            return

        text = text_only(data.message)
        is_mentioned = mentioned(data)
        if not text and not is_mentioned:
            LOG.info("event filtered: no text and bot not mentioned")
            return

        if data.is_group_message and data.group_id is not None:
            if self.persona_switch.restore_if_quiet(data.group_id):
                await self._sync_persona_avatar(
                    transport,
                    data.group_id,
                    "sakura",
                    reason="黑樱30分钟到期后自动恢复",
                )

        force_target = (
            self.persona_switch.force_target(text)
            if data.is_group_message and is_mentioned
            else None
        )
        if force_target and data.group_id is not None:
            changed = self.persona_switch.force(data.group_id, force_target)
            await self._sync_persona_avatar(
                transport,
                data.group_id,
                force_target,
                reason="群友@强制切换" if changed else "群友@确认当前人格",
            )
            if force_target == "sakura":
                reply = self.lines.pick(
                    "force:sakura", data.group_id, FORCE_SAKURA_LINES
                ).render()
            else:
                state = self.persona_switch.state(data.group_id)
                index = max(0, state.switch_count - 1)
                line = FORCE_BLACK_LINES[index % len(FORCE_BLACK_LINES)]
                image = self.persona_switch.switch_image(data.group_id)
                reply = line.text + (f"[image:{image}]" if image else "")
            await self._send(transport, data, reply)
            return

        insult_term = self.persona_switch.find_insult(text, mentioned=is_mentioned)
        directed_insult = bool(
            data.is_group_message
            and insult_term
            and self.persona_switch.is_directed(text, mentioned=is_mentioned)
        )

        command = self.commands.handle(data, text)
        if command.handled:
            await self._send(transport, data, command.reply)
            return

        if data.user_id is None:
            LOG.info("event filtered: missing user_id after command handling")
            return
        is_private = data.is_private_message
        scope_id = data.group_id if data.group_id is not None else 0
        if not is_private and not self.group_consent_confirmed:
            LOG.info("event filtered: group consent is not confirmed")
            if is_mentioned:
                await self._send(transport, data, "本群尚未完成群级知情同意，暂未开启 AI 群聊功能。")
            return

        # Group-level consent can authorize the whole group. Explicit opt-out
        # always wins; private chats still use individual consent.
        if (
            not is_private
            and self.group_consent_confirmed
            and not self.require_user_consent
        ):
            opted_in = not self.store.has_opted_out(scope_id, data.user_id)
        else:
            opted_in = self.store.has_consent(scope_id, data.user_id)
        if opted_in and text:
            sender = data.raw.get("sender")
            sender_info = sender if isinstance(sender, dict) else None
            if sender_info:
                nickname = str(sender_info.get("nickname") or sender_info.get("card") or "").strip()
                role = str(sender_info.get("role") or "").strip()
                self.store.upsert_user_profile(
                    scope_id,
                    data.user_id,
                    nickname=nickname or None,
                    role=role or None,
                )
            self.store.add_message(
                scope_id,
                data.user_id,
                text,
                message_id=data.message_id,
                sender_info=sender_info,
            )
            for candidate in self.memory_extractor.extract(text, user_id=data.user_id):
                if is_private and candidate.scope == "group":
                    continue
                if candidate.scope == "user":
                    memory_id = self.store.add_user_memory(
                        scope_id,
                        data.user_id,
                        candidate.content,
                        status="pending",
                        source_message_id=data.message_id,
                        source_user_id=data.user_id,
                        source_kind="onebot_candidate",
                    )
                else:
                    memory_id = self.store.add_memory(
                        scope_id,
                        candidate.content,
                        status="pending",
                        source_message_id=data.message_id,
                        source_user_id=data.user_id,
                        source_kind="onebot_candidate",
                    )
                LOG.info(
                    "memory candidate created scope=%s id=%s reason=%s group_id=%s user_id=%s",
                    candidate.scope,
                    memory_id,
                    candidate.reason,
                    data.group_id,
                    data.user_id,
                )
        if directed_insult and data.group_id is not None:
            count, switched = self.persona_switch.insult_level(data.group_id)
            LOG.info(
                "directed insult handled group_id=%s user_id=%s term=%s count=%s switched=%s mode=%s",
                data.group_id,
                data.user_id,
                insult_term,
                count,
                switched,
                self.persona_switch.state(data.group_id).mode,
            )
            if switched:
                await self._sync_persona_avatar(
                    transport,
                    data.group_id,
                    "black",
                    reason=f"定向侮辱达到{count}次",
                )
                answer = await self._generate_black_reply(
                    group_id=data.group_id,
                    user_id=data.user_id,
                    text=text,
                    message_id=data.message_id,
                    switched=True,
                    opted_in=opted_in,
                )
            elif self.persona_switch.state(data.group_id).mode == "black":
                answer = await self._generate_black_reply(
                    group_id=data.group_id,
                    user_id=data.user_id,
                    text=text,
                    message_id=data.message_id,
                    switched=False,
                    opted_in=opted_in,
                )
            elif count == 1:
                answer = self.lines.pick(
                    "first_insult", data.group_id, FIRST_INSULT_LINES
                ).render()
            else:
                answer = self.lines.pick(
                    "second_insult", data.group_id, SECOND_INSULT_LINES
                ).render()
            await self._send(transport, data, answer)
            if opted_in:
                self.store.add_message(
                    scope_id,
                    0,
                    answer,
                    is_bot=True,
                    sender_info={"is_bot": True, "persona": self.persona_switch.persona_for(scope_id)},
                )
            return

        should_answer = is_private or is_mentioned or directed_insult
        if not should_answer:
            LOG.info("message stored/ignored: bot was not mentioned")
            return

        explicit_query = self._explicit_search_query(text)
        if explicit_query == "":
            await self._send(transport, data, "用法：/搜索 关键词")
            return
        deck_command = text.strip().startswith("/卡组")
        question = text
        if deck_command:
            question = text.strip()[3:].strip() or "推荐几套当前标准卡组"
        auto_query = self._auto_search_query(text) if self.search_auto and not deck_command else ""
        search_query = explicit_query or auto_query
        web_results: list[str] = []
        if search_query:
            if explicit_query:
                question = search_query
            try:
                search_response = await self.search.search(search_query)
            except Exception as exc:  # defensive boundary around external services
                LOG.exception("web search adapter failed query=%r", search_query)
                search_response = SearchResponse(
                    "error", self.search.selected_provider(), search_query, error=str(exc)
                )
            LOG.info(
                "web search status=%s provider=%s query=%r results=%s",
                search_response.status,
                search_response.provider,
                search_query,
                len(search_response.results),
            )
            if explicit_query and search_response.status != "ok":
                await self._send(transport, data, search_response.user_message)
                return
            if search_response.status == "ok":
                web_results = SearchClient.format_for_prompt(search_response)
        deck_context: list[str] = []
        if self.deck_advisor is not None:
            try:
                deck_context = self.deck_advisor.context_for(question, scope_id=scope_id)
            except Exception:
                LOG.exception("Hearthstone deck context failed question=%r", question)

        # “给我第一套 / 第一套代码” must not depend on the model remembering
        # to paste a long code.  The advisor owns the previous recommendation
        # list and sends the exact code in one message.
        if self.deck_advisor is not None:
            try:
                selected = self.deck_advisor.followup_code(question, scope_id)
            except Exception:
                LOG.exception("Hearthstone deck code follow-up failed question=%r", question)
                selected = None
            if selected and selected.get("deck_code"):
                label = self.store.user_label(scope_id, data.user_id)
                name = selected.get("name") or selected.get("archetype") or "这套卡组"
                code = str(selected["deck_code"])
                intro = f"好的，{label}。{name}的代码："
                await self._send(transport, data, f"{intro}\n{code}")
                if opted_in:
                    self.store.add_message(
                        scope_id,
                        0,
                        f"{intro}\n{code}",
                        is_bot=True,
                        sender_info={"is_bot": True, "target_user_id": data.user_id},
                    )
                return

        LOG.info(
            "dispatching message to LLM group_id=%s user_id=%s message_id=%s deck_context=%s",
            scope_id,
            data.user_id,
            data.message_id,
            len(deck_context),
        )
        messages = self.prompts.build(
            scope_id,
            data.user_id,
            question,
            include_history=opted_in,
            web_results=web_results,
            deck_context=deck_context,
            message_id=data.message_id,
            persona_id=self.persona_switch.persona_for(scope_id) if not is_private else None,
        )
        mode = self._llm_mode(question)
        try:
            chat_with_mode = getattr(self.llm, "chat_with_mode", None)
            if callable(chat_with_mode):
                answer = await chat_with_mode(messages, mode=mode)
            else:
                # Keep compatibility with test doubles and alternate clients.
                answer = await self.llm.chat(messages)
        except LLMError:
            LOG.exception("LLM response failed")
            answer = "模型暂时不可用，稍后再试。"
        answer = self._sanitize_addressing(answer or "（模型没有返回内容）").strip()[: self.max_reply_chars]
        answer = self._enforce_member_address(answer, scope_id)
        recent_replies = self.recent_reply_texts(scope_id, 3)
        if answer != "模型暂时不可用，稍后再试。" and self.is_duplicate_reply(
            answer, scope_id, recent_replies
        ):
            LOG.info("duplicate reply detected scope=%s; regenerating", scope_id)
            messages[0]["content"] += self.duplicate_reminder(recent_replies)
            try:
                chat_again = getattr(self.llm, "chat_with_mode", None)
                if callable(chat_again):
                    retry = await chat_again(messages, mode=mode)
                else:
                    retry = await self.llm.chat(messages)
                retry = self._sanitize_addressing(retry or "").strip()[: self.max_reply_chars]
                retry = self._enforce_member_address(retry, scope_id)
                if retry:
                    answer = retry
            except LLMError:
                LOG.exception("duplicate reply regeneration failed")
        answer = self._apply_media_policy(answer, question, scope_id)
        persona_for_media = (
            self.persona_switch.persona_for(scope_id)
            if not is_private
            else (self.prompts.active_persona or "sakura_winter")
        )
        answer = self._attach_auto_emotion_media(
            answer, question, scope_id, persona_for_media
        )
        LOG.info("LLM response received chars=%s mode=%s", len(answer), mode)
        await self._send(transport, data, answer)
        if opted_in:
            self.store.add_message(
                scope_id,
                0,
                answer,
                is_bot=True,
                sender_info={"is_bot": True, "target_user_id": data.user_id},
            )

    @staticmethod
    def _explicit_search_query(text: str) -> str | None:
        match = re.match(r"^/(?:搜索|联网搜索|search)(?:\s+(.+))?$", text.strip(), re.IGNORECASE)
        if not match:
            return None
        return (match.group(1) or "").strip()[:240]

    @staticmethod
    def _auto_search_query(text: str) -> str:
        """Use conservative deterministic routing instead of another LLM call."""
        query = " ".join(text.split()).strip()
        if not query or query.startswith("/"):
            return ""
        hints = (
            "最新", "现在", "当前", "今天", "昨日", "刚刚", "新闻", "公告", "发布",
            "版本", "更新", "赛程", "赛果", "比分", "转会", "阵容", "价格", "汇率",
            "天气", "上市", "截止", "截至", "何时", "什么时候",
        )
        return query[:240] if any(token in query for token in hints) else ""

    async def _send(self, transport: OneBot11Client, event: OneBotEvent, text: str) -> None:
        if not text:
            return
        key = self.policy.idempotency_key(event, text)
        if not self.store.claim_outbound(
            key,
            scope_id=event.conversation_id,
            message=text,
            retry_after_seconds=self.outbound_retry_after,
        ):
            LOG.info("outbound suppressed by idempotency key=%s", key)
            return
        try:
            parts = split_reply(text, max_parts=self.max_reply_parts)
            if event.is_group_message and event.group_id is not None:
                for index, part in enumerate(parts):
                    if index and self.reply_split_delay:
                        await asyncio.sleep(self.reply_split_delay)
                    await transport.send_group_message(event.group_id, self.media.render(part))
            elif event.is_private_message and event.user_id is not None:
                for index, part in enumerate(parts):
                    if index and self.reply_split_delay:
                        await asyncio.sleep(self.reply_split_delay)
                    await transport.send_private_message(event.user_id, self.media.render(part))
            else:
                self.store.finish_outbound(key, status="failed", error="unsupported_scope")
                return
        except Exception as exc:
            self.store.finish_outbound(key, status="failed", error=str(exc))
            raise
        self.store.finish_outbound(key, status="sent")
