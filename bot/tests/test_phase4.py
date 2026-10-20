from __future__ import annotations

import unittest

from memory.extractor import MemoryExtractor
from storage.store import Store


class Phase4Tests(unittest.TestCase):
    def test_extractor_only_accepts_explicit_statements(self) -> None:
        extractor = MemoryExtractor(
            {"memory": {"candidate_extraction_enabled": True, "max_candidates_per_message": 2}}
        )
        user = extractor.extract("我喜欢吃火锅", user_id=42)
        self.assertEqual(len(user), 1)
        self.assertEqual(user[0].scope, "user")
        self.assertIn("火锅", user[0].content)
        group = extractor.extract("本群主要聊无畏契约", user_id=42)
        self.assertEqual(group[0].scope, "group")
        self.assertEqual(extractor.extract("今天下雨了", user_id=42), [])

    def test_candidates_require_review_before_prompt_visibility(self) -> None:
        store = Store(":memory:")
        user_id = store.add_user_memory(1, 42, "用户42偏好自述：火锅", status="pending")
        group_id = store.add_memory(1, "群聊候选：主要聊无畏契约", status="pending")
        self.assertEqual(store.list_user_memories(1, 42, status="approved"), [])
        self.assertEqual(store.approved_memories(1), [])
        store.set_user_memory_status(user_id, "approved")
        store.set_memory_status(group_id, "approved")
        self.assertEqual(len(store.list_user_memories(1, 42)), 1)
        self.assertEqual(store.approved_memories(1), ["群聊候选：主要聊无畏契约"])
        store.close()


if __name__ == "__main__":
    unittest.main()
