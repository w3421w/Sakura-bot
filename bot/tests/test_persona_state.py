"""Tests for durable persona mode and the 30-minute quiet timer."""

from __future__ import annotations

import unittest

from core.persona_switch import PersonaSwitchManager
from storage.store import Store


CONFIG = {
    "persona_switch": {
        "enabled": True,
        "sakura_persona": "sakura_winter",
        "black_persona": "sakura_black",
        "insult_threshold": 3,
        "quiet_seconds": 1800,
        "directed_names": ["樱"],
    }
}


class PersonaStateTests(unittest.TestCase):
    def test_auto_switch_expires_after_quiet_period(self) -> None:
        manager = PersonaSwitchManager(CONFIG)
        for moment in (0, 1, 2):
            manager.insult_level(1, now=moment)
        self.assertEqual("black", manager.state(1).mode)
        self.assertFalse(manager.restore_if_quiet(1, now=1801))
        self.assertTrue(manager.restore_if_quiet(1, now=1803))
        self.assertEqual("sakura", manager.state(1).mode)

    def test_forced_black_also_expires(self) -> None:
        manager = PersonaSwitchManager(CONFIG)
        manager.force(1, "black", now=1000)
        self.assertEqual("black", manager.state(1).mode)
        self.assertTrue(manager.state(1).auto_black)
        self.assertEqual(1000, manager.state(1).last_insult_at)
        self.assertFalse(manager.restore_if_quiet(1, now=2799))
        self.assertTrue(manager.restore_if_quiet(1, now=2800))
        self.assertEqual("sakura", manager.state(1).mode)

    def test_another_insult_does_not_extend_the_fixed_window(self) -> None:
        manager = PersonaSwitchManager(CONFIG)
        manager.force(1, "black", now=1000)
        manager.insult_level(1, now=2000)
        # The window starts at the switch (1000), not at the later insult.
        self.assertFalse(manager.restore_if_quiet(1, now=2799))
        self.assertTrue(manager.restore_if_quiet(1, now=2800))

    def test_mode_and_timer_survive_restart(self) -> None:
        store = Store(":memory:")
        first = PersonaSwitchManager(CONFIG, store)
        first.force(1, "black", now=1000)

        second = PersonaSwitchManager(CONFIG, store)
        self.assertEqual("black", second.state(1).mode)
        self.assertEqual(1000, second.state(1).last_insult_at)
        self.assertTrue(second.state(1).auto_black)

        self.assertTrue(second.restore_if_quiet(1, now=2800))
        third = PersonaSwitchManager(CONFIG, store)
        self.assertEqual("sakura", third.state(1).mode)
        self.assertIsNone(third.state(1).last_insult_at)

    def test_avatar_paths_selected_by_mode(self) -> None:
        manager = PersonaSwitchManager(
            {
                "persona_switch": {
                    "sakura_avatar": "assets/stickers/sakura_official_thumb.png",
                    "black_avatar": "assets/avatars/black_sakura_qq_v2.png",
                }
            }
        )
        self.assertTrue(str(manager.avatar_for("sakura")).endswith("sakura_official_thumb.png"))
        self.assertTrue(str(manager.avatar_for("black")).endswith("black_sakura_qq_v2.png"))

    def test_switch_images_cycle_and_survive_restart(self) -> None:
        store = Store(":memory:")
        first = PersonaSwitchManager(CONFIG, store)
        names = []
        for moment in range(4):
            first.force(1, "black", now=moment)
            names.append(first.switch_image(1))
        self.assertEqual(4, len(set(names)))
        self.assertEqual(4, first.state(1).switch_count)

        second = PersonaSwitchManager(CONFIG, store)
        second.force(1, "black", now=10)
        self.assertEqual(names[0], second.switch_image(1))


if __name__ == "__main__":
    unittest.main()
