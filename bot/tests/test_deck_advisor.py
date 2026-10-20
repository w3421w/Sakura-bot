"""Tests for the Hearthstone deck advisor used by the dispatcher."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from knowledge.deck_advisor import DeckAdvisor
from storage.store import Store


CODE = (
    "AAEBAePjAwaRvAKR0AP8qAaW0wbr1gey2AcMiA6NEKS2A8TeA//bBL7iBI+VBZWqBbTR"
    "BaL6BbSPB/vgBwAA"
)


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
        return "这套可以"


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


class DeckAdvisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        payload = {
            "decks": [
                {
                    "source": "旅法师营地",
                    "source_url": "https://example.com/post/1",
                    "title": "炉石标准日报",
                    "published": "2026-10-20",
                    "class": "SHAMAN",
                    "class_zh": "萨满",
                    "archetype": "法术萨",
                    "name": "法术萨",
                    "deck_code": CODE,
                    "winrate": 56.6,
                    "strength_note": "来源标注约56.6%胜率，未独立复核。",
                    "key_cards": [{"name": "测试卡", "count": 2}],
                    "curve": {"0-1": 8, "2": 6, "3": 4},
                    "tags": ["炉石传说", "萨满", "法术萨"],
                }
            ]
        }
        (self.root / "latest.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        self.advisor = DeckAdvisor(
            {
                "hearthstone": {
                    "enabled": True,
                    "decks_path": "latest.json",
                    "cards_path": "cards.json",
                    "max_decks": 3,
                }
            },
            base_dir=self.root,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_detects_deck_review_query(self) -> None:
        self.assertTrue(self.advisor.is_deck_query("点评一下这套法术萨"))
        self.assertFalse(self.advisor.is_deck_query("今天天气真好"))

    def test_retrieves_matching_deck(self) -> None:
        decks = self.advisor.find_decks("法术萨 强度")
        self.assertEqual(1, len(decks))
        self.assertEqual("法术萨", decks[0]["archetype"])

    def test_builds_context_with_source_and_winrate(self) -> None:
        context = "\n".join(self.advisor.context_for("法术萨怎么样"))
        self.assertIn("旅法师营地", context)
        self.assertIn("56.6", context)
        self.assertIn("非官方", context)

    def test_user_deck_code_is_decoded_locally(self) -> None:
        context = "\n".join(self.advisor.context_for(f"帮我点评 {CODE}"))
        self.assertIn("用户提供的炉石卡组代码", context)
        self.assertIn("牌数：30", context)

    def test_dispatcher_injects_deck_context_for_slash_command(self) -> None:
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
            "hearthstone": {
                "enabled": True,
                "decks_path": str(self.root / "latest.json"),
                "cards_path": str(self.root / "cards.json"),
            },
        }
        transport = FakeTransport()
        llm = FakeLLM()
        dispatcher = MessageDispatcher(config, store, llm, "missing-persona.md")

        asyncio.run(dispatcher.handle_raw(transport, _private_event("/卡组 海盗战", 7)))

        self.assertTrue(llm.calls)
        content = llm.calls[0][1]["content"]
        self.assertIn("炉石卡组资料", content)
        self.assertIn("海盗战", content)
        self.assertEqual([(42, "这套可以")], transport.private)


if __name__ == "__main__":
    unittest.main()
