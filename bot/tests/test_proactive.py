from __future__ import annotations

import unittest

from core.proactive import ProactiveChatManager
from storage.store import Store


class ProactiveTests(unittest.TestCase):
    def test_silent_marker_is_not_a_reply(self) -> None:
        manager = ProactiveChatManager(
            {"proactive": {"enabled": True, "group_ids": [1]}},
            Store(":memory:"),
            object(),
            object(),
        )
        self.assertEqual(manager._clean_answer("SILENT"), "")
        self.assertEqual(manager._clean_answer("回复：草，这波有点东西"), "草，这波有点东西")

    def test_recent_activity_exposes_row_order_and_bot_flag(self) -> None:
        store = Store(":memory:")
        store.add_message(1, 42, "第一句", message_id=1)
        store.add_message(1, 0, "机器人一句", is_bot=True)
        activity = store.recent_activity(1)
        self.assertEqual([row[2] for row in activity], ["第一句", "机器人一句"])
        self.assertEqual(activity[-1][3], 1)
        store.close()


if __name__ == "__main__":
    unittest.main()
