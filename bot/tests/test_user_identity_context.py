import tempfile
import unittest
from pathlib import Path

from llm.prompt_builder import PromptBuilder
from storage.store import Store


class UserIdentityContextTests(unittest.TestCase):
    def test_history_contains_stable_user_label_and_qq(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(":memory:")
            store.upsert_user_profile(100, 1001, preferred_name="乙哥", role="admin")
            store.add_message(
                100,
                1001,
                "今天打不打游戏",
                sender_info={"nickname": "TestUser", "card": "乙哥", "role": "admin"},
            )
            builder = PromptBuilder(
                store,
                Path(tmp) / "persona.md",
                {"knowledge": {}, "persona": {}, "bot": {"max_context_messages": 5}},
            )
            messages = builder.build(100, 1001, "你们说啥", include_history=True)
            content = messages[1]["content"]
            self.assertIn("乙前辈｜QQ:1001", content)
            self.assertIn("本次提问者QQ 1001：你们说啥", content)
            self.assertIn("提问者身份：乙前辈", content)


if __name__ == "__main__":
    unittest.main()
