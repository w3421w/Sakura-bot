"""Tests for duplicate-reply detection and one-shot regeneration."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from storage.store import Store


ROOT = Path(__file__).resolve().parents[2]
GROUP = 100


class SequenceLLM:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, str]]] = []

    def _next(self, messages):
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.answers) - 1)
        return self.answers[index]

    async def chat(self, messages):
        return self._next(messages)

    async def chat_with_mode(self, messages, mode="fast"):
        return self._next(messages)


class FakeTransport:
    def __init__(self) -> None:
        self.group: list[tuple[int, object]] = []

    async def send_group_message(self, group_id, message):
        self.group.append((group_id, message))

    async def send_private_message(self, user_id, message):
        pass

    async def set_qq_avatar(self, path):
        pass


def _event(text: str, message_id: int) -> str:
    return json.dumps(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "user_id": 42,
            "group_id": GROUP,
            "message_id": message_id,
            "message": [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": text}},
            ],
            "sender": {"user_id": 42, "nickname": "测试群友", "role": "member"},
        },
        ensure_ascii=False,
    )


def _config() -> dict:
    return {
        "access": {
            "allowed_group_ids": [GROUP],
            "admin_user_ids": [],
            "group_consent_confirmed": True,
            "require_user_consent": False,
            "allow_private_messages": False,
        },
        "storage": {"retention_days": 14},
        "bot": {"max_reply_chars": 600, "max_reply_parts": 4, "reply_split_delay_seconds": 0},
        "knowledge": {},
        "memory": {"candidate_extraction_enabled": False},
        "assets": {"path": str(ROOT / "assets")},
        "search": {"enabled": False},
        "persona": {"directory": str(ROOT / "bot" / "persona"), "active": "sakura_winter"},
        "persona_switch": {"enabled": True, "insult_threshold": 3},
        "media": {"auto_emotion_enabled": False},
    }


class ReplyDedupTests(unittest.TestCase):
    def test_duplicate_detection_ignores_punctuation_and_skips_short_lines(self) -> None:
        store = Store(":memory:")
        store.add_message(GROUP, 0, "今天天气不错，适合出门走走", is_bot=True)
        dispatcher = MessageDispatcher(
            _config(), store, SequenceLLM(["ok"]), str(ROOT / "bot" / "persona" / "system.md")
        )
        self.assertTrue(
            dispatcher.is_duplicate_reply("今天天气不错，适合出门走走！", GROUP)
        )
        self.assertFalse(dispatcher.is_duplicate_reply("嗯", GROUP))

    def test_same_reply_is_regenerated_once(self) -> None:
        store = Store(":memory:")
        llm = SequenceLLM(
            [
                "今天天气不错，适合出门走走。",
                "今天天气不错，适合出门走走。",
                "傍晚可能有雨，记得带伞。",
            ]
        )
        transport = FakeTransport()
        dispatcher = MessageDispatcher(
            _config(), store, llm, str(ROOT / "bot" / "persona" / "system.md")
        )

        async def run() -> None:
            await dispatcher.handle_raw(transport, _event("今天天气怎么样", 1))
            await dispatcher.handle_raw(transport, _event("今天天气如何", 2))

        asyncio.run(run())

        self.assertEqual(3, len(llm.calls))
        first = str(transport.group[0][1])
        second_parts = [str(message) for _, message in transport.group[1:]]
        self.assertNotEqual(first, "".join(second_parts))
        self.assertTrue(any("傍晚可能有雨" in part for part in second_parts))

    def test_duplicate_reminder_contains_recent_reply(self) -> None:
        dispatcher = MessageDispatcher(
            _config(), Store(":memory:"), SequenceLLM(["ok"]),
            str(ROOT / "bot" / "persona" / "system.md"),
        )
        reminder = dispatcher.duplicate_reminder(["上一句已经说过的话"])
        self.assertIn("避免重复", reminder)
        self.assertIn("上一句已经说过的话", reminder)


if __name__ == "__main__":
    unittest.main()
