from __future__ import annotations

import json
import unittest

from core.commands import CommandRouter
from storage.store import Store
from transport.events import mentioned, parse_event, text_only


class Stage1Tests(unittest.TestCase):
    def test_onebot_message_parsing(self) -> None:
        raw = json.dumps(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 123,
                "user_id": 456,
                "self_id": 789,
                "message_id": 1,
                "message": [
                    {"type": "at", "data": {"qq": "789"}},
                    {"type": "text", "data": {"text": "  你好  "}},
                ],
            },
            ensure_ascii=False,
        )
        event = parse_event(raw)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertTrue(event.is_group_message)
        self.assertTrue(mentioned(event))
        self.assertEqual(text_only(event.message), "你好")

    def test_store_and_privacy_commands(self) -> None:
        store = Store(":memory:")
        config = {
            "access": {
                "admin_user_ids": {456},
                "group_consent_confirmed": True,
            },
            "storage": {"retention_days": 14},
        }
        router = CommandRouter(store, config)
        event = parse_event(
            {
                "post_type": "message",
                "message_type": "group",
                "group_id": 123,
                "user_id": 456,
                "self_id": 789,
                "message": "/同意记录",
            }
        )
        assert event is not None
        self.assertTrue(router.handle(event, "/同意记录").handled)
        self.assertTrue(store.has_consent(123, 456))
        store.add_message(123, 456, "测试消息")
        self.assertEqual(len(store.recent(123)), 1)
        router.handle(event, "/忘记我")
        self.assertFalse(store.has_consent(123, 456))
        self.assertEqual(store.recent(123), [])
        store.close()


if __name__ == "__main__":
    unittest.main()
