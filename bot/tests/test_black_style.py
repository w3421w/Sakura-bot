"""Tests that the black-Sakura style contract applies to ordinary water chat."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from storage.store import Store


ROOT = Path(__file__).resolve().parents[2]
GROUP = 100


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages):
        self.calls.append(messages)
        return "在听。前辈说。"

    async def chat_with_mode(self, messages, mode="fast"):
        self.calls.append(messages)
        return "在听。前辈说。"


class FakeTransport:
    async def send_group_message(self, group_id, message):
        pass

    async def send_private_message(self, user_id, message):
        pass

    async def set_qq_avatar(self, path):
        pass


def _event(text: str, message_id: int = 1) -> str:
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


class BlackStyleTests(unittest.TestCase):
    def test_ordinary_black_chat_gets_the_style_contract(self) -> None:
        store = Store(":memory:")
        llm = FakeLLM()
        dispatcher = MessageDispatcher(
            _config(), store, llm, str(ROOT / "bot" / "persona" / "system.md")
        )
        dispatcher.persona_switch.force(GROUP, "black")

        asyncio.run(dispatcher.handle_raw(FakeTransport(), _event("今天好累")))

        self.assertEqual(1, len(llm.calls))
        system = llm.calls[0][0]["content"]
        self.assertTrue(system.startswith("# 黑樱 Persona"))
        self.assertIn("黑樱语态契约", system)
        self.assertIn("我妻由乃", system)
        self.assertIn("时崎狂三", system)
        self.assertIn("蛇喰梦子", system)
        self.assertIn("毒蛇感", system)
        self.assertIn("睡吧。别让我等太久", system)
        self.assertIn("玩得开心。……和谁？", system)
        self.assertIn("不要模仿语气", system)

    def test_ordinary_sakura_chat_has_no_black_contract(self) -> None:
        store = Store(":memory:")
        llm = FakeLLM()
        dispatcher = MessageDispatcher(
            _config(), store, llm, str(ROOT / "bot" / "persona" / "system.md")
        )

        asyncio.run(dispatcher.handle_raw(FakeTransport(), _event("今天好累")))

        system = llm.calls[0][0]["content"]
        self.assertNotIn("黑樱语态契约", system)
        self.assertFalse(system.startswith("# 黑樱 Persona"))


if __name__ == "__main__":
    unittest.main()
