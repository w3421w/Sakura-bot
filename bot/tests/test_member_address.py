"""Tests for the group-wide “短称+前辈” address rule."""

from __future__ import annotations

import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from llm.prompt_builder import PromptBuilder
from storage.store import Store


ROOT = Path(__file__).resolve().parents[2]
GROUP = 100


class FakeLLM:
    async def chat(self, messages):
        return "好的"

    async def chat_with_mode(self, messages, mode="fast"):
        return "好的"


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
        "bot": {"max_reply_chars": 600, "max_reply_parts": 4},
        "knowledge": {},
        "memory": {"candidate_extraction_enabled": False},
        "assets": {"path": str(ROOT / "assets")},
        "search": {"enabled": False},
        "persona": {"directory": str(ROOT / "bot" / "persona"), "active": "sakura_winter"},
        "persona_switch": {"enabled": True, "insult_threshold": 3},
    }


class MemberAddressTests(unittest.TestCase):
    def test_legacy_honorifics_become_short_name_plus_senpai(self) -> None:
        store = Store(":memory:")
        store.upsert_user_profile(GROUP, 1001, preferred_name="甲前辈")
        store.upsert_user_profile(GROUP, 1002, preferred_name="乙前辈")
        store.upsert_user_profile(GROUP, 1003, preferred_name="丙前辈")
        store.upsert_user_profile(GROUP, 1004, preferred_name="丁前辈")
        dispatcher = MessageDispatcher(
            _config(), store, FakeLLM(), str(ROOT / "bot" / "persona" / "system.md")
        )
        result = dispatcher._enforce_member_address(
            "甲哥，乙哥，丙哥，丁哥，甲前辈前辈", GROUP
        )
        self.assertEqual(
            "甲前辈，乙前辈，丙前辈，丁前辈，甲前辈",
            result,
        )

    def test_configured_alias_is_applied(self) -> None:
        config = _config()
        config["persona_switch"]["address_aliases"] = {"群友强哥": "群友强前辈"}
        dispatcher = MessageDispatcher(
            config, Store(":memory:"), FakeLLM(),
            str(ROOT / "bot" / "persona" / "system.md"),
        )
        self.assertEqual(
            "群友强前辈", dispatcher._enforce_member_address("群友强哥", GROUP)
        )

    def test_unknown_names_are_not_rewritten(self) -> None:
        store = Store(":memory:")
        dispatcher = MessageDispatcher(
            _config(), store, FakeLLM(), str(ROOT / "bot" / "persona" / "system.md")
        )
        self.assertEqual("群友前辈", dispatcher._enforce_member_address("群友前辈", GROUP))
        self.assertEqual("阳光很好", dispatcher._enforce_member_address("阳光很好", GROUP))

    def test_user_label_normalises_member_honorifics(self) -> None:
        store = Store(":memory:")
        store.upsert_user_profile(GROUP, 1001, preferred_name="甲哥")
        self.assertEqual("甲前辈", store.user_label(GROUP, 1001))
        self.assertEqual(
            "张前辈",
            store.user_label(GROUP, 999, {"card": "张哥", "nickname": "张"}),
        )
        self.assertEqual(
            "王前辈",
            store.user_label(GROUP, 998, {"card": "王姐", "nickname": "王"}),
        )

    def test_prompt_has_final_address_rule_for_both_personas(self) -> None:
        store = Store(":memory:")
        for persona_id in ("sakura_winter", "sakura_black"):
            builder = PromptBuilder(
                store,
                ROOT / "bot" / "persona" / "system.md",
                {
                    "knowledge": {},
                    "persona": {"directory": str(ROOT / "bot" / "persona")},
                    "bot": {},
                },
            )
            messages = builder.build(
                GROUP, 42, "你好", include_history=False, persona_id=persona_id
            )
            system = messages[0]["content"]
            self.assertIn("群内称呼铁律", system)
            self.assertIn("禁止使用“哥/姐", system)
            self.assertIn("甲哥”→“甲前辈", system)
            self.assertTrue(system.startswith("# 黑樱 Persona") if persona_id == "sakura_black" else True)


if __name__ == "__main__":
    unittest.main()
