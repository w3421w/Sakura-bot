"""Regression tests for private-message replies and privacy scope isolation."""

from __future__ import annotations

import asyncio
import json
import unittest

from core.commands import CommandRouter
from core.dispatcher import MessageDispatcher
from storage.store import Store
from transport.events import parse_event


class FakeTransport:
    def __init__(self) -> None:
        self.private: list[tuple[int, str]] = []
        self.group: list[tuple[int, str]] = []

    async def send_private_message(self, user_id: int, message: str) -> None:
        self.private.append((user_id, message))

    async def send_group_message(self, group_id: int, message: str) -> None:
        self.group.append((group_id, message))


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return "私聊测试回复"


def _private_event(message: str, message_id: int = 1) -> str:
    return json.dumps(
        {
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "self_id": 999,
            "user_id": 42,
            "message_id": message_id,
            "message": message,
            "raw_message": message,
            "sender": {"user_id": 42, "nickname": "测试用户"},
        },
        ensure_ascii=False,
    )


class PrivateMessageTests(unittest.TestCase):
    def test_private_commands_use_private_scope_without_group_consent(self) -> None:
        store = Store(":memory:")
        config = {
            "access": {"group_consent_confirmed": False, "admin_user_ids": []},
            "storage": {"retention_days": 14},
        }
        router = CommandRouter(store, config)
        event = parse_event(_private_event("/同意记录"))
        assert event is not None

        result = router.handle(event, "/同意记录")
        self.assertTrue(result.handled)
        self.assertTrue(store.has_consent(0, 42))

        forget = router.handle(event, "/忘记我")
        self.assertTrue(forget.handled)
        self.assertFalse(store.has_consent(0, 42))

    def test_private_text_calls_llm_and_sends_private_reply_without_consent(self) -> None:
        store = Store(":memory:")
        config = {
            "access": {
                "allowed_group_ids": [],
                "admin_user_ids": [],
                "group_consent_confirmed": False,
                "allow_private_messages": True,
            },
            "storage": {"retention_days": 14},
            "bot": {"max_reply_chars": 600},
            "knowledge": {},
            "memory": {"candidate_extraction_enabled": False},
        }
        transport = FakeTransport()
        llm = FakeLLM()
        dispatcher = MessageDispatcher(config, store, llm, "missing-persona.md")

        asyncio.run(dispatcher.handle_raw(transport, _private_event("你好", message_id=2)))

        self.assertEqual(1, len(llm.calls))
        self.assertEqual([(42, "私聊测试回复")], transport.private)
        self.assertEqual([], transport.group)
        self.assertFalse(store.has_consent(0, 42))
        self.assertEqual([], store.recent(0))


if __name__ == "__main__":
    unittest.main()
