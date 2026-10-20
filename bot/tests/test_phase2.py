from __future__ import annotations

import unittest
from pathlib import Path

from llm.prompt_builder import PromptBuilder
from knowledge.retriever import KnowledgeBase
from storage.store import Store


class Phase2Tests(unittest.TestCase):
    def test_message_metadata_and_user_scope(self) -> None:
        store = Store(":memory:")
        store.add_message(
            10,
            20,
            "第一条",
            message_id=101,
            sender_info={"nickname": "小甲", "role": "member"},
        )
        store.add_message(10, 21, "第二条", message_id=102)
        self.assertEqual(store.recent(10, exclude_message_id=102), [(20, "第一条", 0)])
        store.upsert_user_profile(10, 20, nickname="小甲", role="member")
        store.add_user_memory(10, 20, "喜欢简短回答")
        self.assertEqual(store.get_user_profile(10, 20)["nickname"], "小甲")  # type: ignore[index]
        self.assertEqual(store.list_user_memories(10, 20)[0][1], "喜欢简短回答")
        store.forget(10, 20)
        self.assertIsNone(store.get_user_profile(10, 20))
        self.assertEqual(store.list_user_memories(10, 20), [])
        store.close()

    def test_prompt_has_bounded_history_user_memory_and_rag(self) -> None:
        root = Path(__file__).resolve().parent / "_phase3_data"
        root.mkdir(exist_ok=True)
        (root / "fact.md").write_text("小甲喜欢使用简短回答。", encoding="utf-8")
        store = Store(":memory:")
        store.add_message(1, 7, "旧问题", message_id=1)
        store.upsert_user_profile(1, 7, nickname="小甲")
        store.add_user_memory(1, 7, "称呼为小甲")
        builder = PromptBuilder(
            store,
            root / "persona.md",
            {
                "bot": {"max_context_messages": 20, "max_user_history": 5},
                "knowledge": {"path": str(root), "max_results": 2, "max_chars": 500},
            },
        )
        messages = builder.build(1, 7, "小甲喜欢什么？", message_id=2)
        combined = "\n".join(item["content"] for item in messages)
        self.assertIn("旧问题", combined)
        self.assertIn("称呼为小甲", combined)
        self.assertIn("小甲喜欢使用简短回答", combined)
        store.close()

    def test_rag_keeps_json_records_separate_and_refreshes(self) -> None:
        root = Path(__file__).resolve().parent / "_phase3_data"
        root.mkdir(exist_ok=True)
        facts = root / "facts.json"
        facts.write_text(
            '{"entries":[{"term":"alpha","meaning":"only alpha"},'
            '{"term":"beta","meaning":"only beta"}]}',
            encoding="utf-8",
        )
        kb = KnowledgeBase(root, min_score=3)
        alpha = "\n".join(kb.retrieve("alpha", limit=4, max_chars=1000))
        self.assertIn("only alpha", alpha)
        self.assertNotIn("only beta", alpha)
        (root / "new.md").write_text("# gamma\nnew gamma fact", encoding="utf-8")
        gamma = "\n".join(kb.retrieve("gamma", limit=4, max_chars=1000))
        self.assertIn("new gamma fact", gamma)

    def test_prompt_budget_preserves_current_question(self) -> None:
        store = Store(":memory:")
        for index in range(10):
            store.add_memory(1, "群记忆" + ("很长" * 100) + str(index))
            store.add_user_memory(1, 7, "用户记忆" + ("很长" * 100) + str(index))
        builder = PromptBuilder(
            store,
            Path("missing-persona.md"),
            {
                "bot": {
                    "max_prompt_chars": 500,
                    "max_memory_chars": 100,
                    "max_user_memory_chars": 100,
                    "max_context_messages": 20,
                },
                "knowledge": {},
            },
        )
        messages = builder.build(1, 7, "当前问题", include_history=False)
        self.assertIn("本次提问者QQ 7：当前问题", messages[1]["content"])
        self.assertLessEqual(len(messages[1]["content"]), 500)
        store.close()

    def test_prompt_keeps_user_dialogues_separate(self) -> None:
        store = Store(":memory:")
        store.add_message(1, 7, "甲的旧问题", message_id=1)
        store.add_message(
            1,
            0,
            "回答甲",
            is_bot=True,
            sender_info={"is_bot": True, "target_user_id": 7},
        )
        store.add_message(1, 8, "乙的独立话题", message_id=2)
        store.add_message(
            1,
            0,
            "回答乙",
            is_bot=True,
            sender_info={"is_bot": True, "target_user_id": 8},
        )
        builder = PromptBuilder(store, Path("missing-persona.md"), {"bot": {}, "knowledge": {}})
        messages = builder.build(1, 7, "新的问题", message_id=3)
        content = messages[1]["content"]
        self.assertIn("甲的旧问题", content)
        self.assertIn("回答甲", content)
        self.assertNotIn("乙的独立话题", content)
        self.assertNotIn("回答乙", content)
        store.close()

    def test_group_history_only_when_question_references_it(self) -> None:
        store = Store(":memory:")
        store.add_message(1, 8, "乙刚刚提到比赛", message_id=1)
        builder = PromptBuilder(store, Path("missing-persona.md"), {"bot": {}, "knowledge": {}})
        isolated = builder.build(1, 7, "今天天气如何", message_id=2)[1]["content"]
        referenced = builder.build(1, 7, "刚才他说的比赛是什么", message_id=2)[1]["content"]
        self.assertNotIn("乙刚刚提到比赛", isolated)
        self.assertIn("乙刚刚提到比赛", referenced)
        store.close()

    def test_short_banter_gets_short_reply_guidance(self) -> None:
        store = Store(":memory:")
        builder = PromptBuilder(store, Path("missing-persona.md"), {"bot": {}, "knowledge": {}})
        messages = builder.build(1, 7, "想死了", include_history=False)
        self.assertIn("短答优先", messages[0]["content"])
        self.assertFalse(PromptBuilder._prefers_short_reply("请解释这个方案为什么可行？"))
        store.close()


if __name__ == "__main__":
    unittest.main()
