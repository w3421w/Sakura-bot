from __future__ import annotations

import unittest

from core.proactive import ProactiveChatManager
from storage.store import Store


class EnhancedProactiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.manager = ProactiveChatManager(
            {"proactive": {"enabled": True, "group_ids": [1]}},
            self.store,
            object(),
            object(),
        )

    def tearDown(self) -> None:
        self.store.close()

    def test_clear_opening_detection(self) -> None:
        self.assertTrue(self.manager._is_clear_opening("你们觉得樱木和流川谁更强？"))
        self.assertTrue(self.manager._is_clear_opening("有没有人看最新比赛"))
        self.assertFalse(self.manager._is_clear_opening("今天群里挺安静"))

    def test_meta_proactive_output_is_suppressed(self) -> None:
        self.assertEqual(self.manager._clean_answer("当前问题简单，直接回答即可。"), "")
        self.assertEqual(self.manager._clean_answer("现在在聊哪部动漫？快说快说！"), "现在在聊哪部动漫？快说快说！")


if __name__ == "__main__":
    unittest.main()
