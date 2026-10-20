from __future__ import annotations

import unittest
from pathlib import Path

from core.tulpa_compat import TulpaPolicy
from persona.catalog import PersonaCatalog
from storage.store import Store
from transport.events import parse_event


class TulpaIntegrationTests(unittest.TestCase):
    def test_event_and_outbound_idempotency_survive_retries(self) -> None:
        store = Store(":memory:")
        self.assertTrue(store.claim_event("onebot:message:group:1:9", scope_id="1:group:1"))
        self.assertFalse(store.claim_event("onebot:message:group:1:9", scope_id="1:group:1"))
        key = "reply:onebot:message:group:1:9"
        self.assertTrue(store.claim_outbound(key, scope_id="1:group:1", message="你好"))
        self.assertFalse(store.claim_outbound(key, scope_id="1:group:1", message="你好"))
        store.finish_outbound(key, status="sent")
        self.assertFalse(store.claim_outbound(key, scope_id="1:group:1", message="你好"))
        memory_id = store.add_memory(
            1,
            "候选",
            status="pending",
            source_message_id=9,
            source_user_id=3,
            source_kind="onebot_candidate",
        )
        self.assertEqual(store.list_memories(1)[0][0], memory_id)
        store.close()

    def test_policy_scopes_and_stable_keys(self) -> None:
        event = parse_event(
            {
                "post_type": "message",
                "message_type": "group",
                "self_id": 100,
                "group_id": 200,
                "user_id": 300,
                "message_id": 9,
                "message": "hi",
            }
        )
        assert event is not None
        policy = TulpaPolicy({"access": {"allowed_group_ids": [200]}})
        self.assertTrue(policy.scope_allowed(event))
        self.assertEqual(policy.conversation(event).id, "100:group:200")
        self.assertEqual(policy.idempotency_key(event, "a"), policy.idempotency_key(event, "b"))

    def test_persona_catalog_discovers_markdown_without_restart(self) -> None:
        root = Path(__file__).resolve().parent / "_tulpa_persona_data"
        root.mkdir(exist_ok=True)
        (root / "alpha.md").write_text("# Alpha\n简短回答。", encoding="utf-8")
        catalog = PersonaCatalog(root)
        self.assertEqual(catalog.list()[0].name, "Alpha")
        (root / "beta.md").write_text("# Beta\n更活泼。", encoding="utf-8")
        self.assertEqual({item.id for item in catalog.list()}, {"alpha", "beta"})


if __name__ == "__main__":
    unittest.main()
