"""Tests for local Hearthstone deckstring decoding."""

from __future__ import annotations

import unittest

from knowledge.deck_code import (
    DeckCodeError,
    decode_deckstring,
    deck_code_in_text,
    summarize_deck,
)


CODE = (
    "AAEBAePjAwaRvAKR0AP8qAaW0wbr1gey2AcMiA6NEKS2A8TeA//bBL7iBI+VBZWqBbTR"
    "BaL6BbSPB/vgBwAA"
)


class DeckCodeTests(unittest.TestCase):
    def test_decodes_standard_deckstring(self) -> None:
        decoded = decode_deckstring(CODE)
        self.assertEqual("standard", decoded["format"])
        self.assertEqual(30, decoded["total"])
        self.assertEqual([61923], decoded["heroes"])
        self.assertTrue(decoded["cards"])

    def test_rejects_invalid_code(self) -> None:
        with self.assertRaises(DeckCodeError):
            decode_deckstring("not-a-deck-code")

    def test_finds_code_inside_message(self) -> None:
        self.assertEqual(CODE, deck_code_in_text(f"帮我看看这套 {CODE} 怎么样"))

    def test_summary_uses_card_map_and_curve(self) -> None:
        decoded = decode_deckstring(CODE)
        first = decoded["cards"][0]
        summary = summarize_deck(
            decoded,
            {
                first["dbf_id"]: {
                    "name": "测试卡",
                    "cost": 2,
                    "type": "MINION",
                    "rarity": "COMMON",
                    "cardClass": "WARRIOR",
                }
            },
        )
        self.assertEqual(30, summary["total"])
        self.assertTrue(summary["key_cards"])
        self.assertIn("2", summary["curve"])


if __name__ == "__main__":
    unittest.main()
