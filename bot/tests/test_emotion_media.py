"""Tests for automatic emotion-matched Sakura media."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from core.emotion_media import EmotionMediaSelector
from storage.store import Store
from transport.media import MediaRegistry


ROOT = Path(__file__).resolve().parents[2]
GROUP = 100
MEDIA_ROOT = ROOT / "assets" / "stickers"
HAS_MEDIA = any(
    path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    for path in MEDIA_ROOT.rglob("*")
    if path.is_file()
)


class FakeLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    async def chat(self, messages):
        return self.answer

    async def chat_with_mode(self, messages, mode="fast"):
        return self.answer


class FakeTransport:
    def __init__(self) -> None:
        self.group: list[tuple[int, object]] = []

    async def send_group_message(self, group_id, message):
        self.group.append((group_id, message))

    async def send_private_message(self, user_id, message):
        pass

    async def set_qq_avatar(self, path):
        pass


def _event(text: str, message_id: int) -> str:
    return json.dumps(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "user_id": 42,
            "group_id": GROUP,
            "message_id": message_id,
            "message": [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": text}},
            ],
            "sender": {"user_id": 42, "nickname": "测试群友", "role": "member"},
        },
        ensure_ascii=False,
    )


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
        "bot": {"max_reply_chars": 600, "max_reply_parts": 4, "reply_split_delay_seconds": 0},
        "knowledge": {},
        "memory": {"candidate_extraction_enabled": False},
        "assets": {"path": str(ROOT / "assets")},
        "search": {"enabled": False},
        "persona": {"directory": str(ROOT / "bot" / "persona"), "active": "sakura_winter"},
        "persona_switch": {"enabled": True, "insult_threshold": 3},
        "media": {
            "auto_emotion_enabled": True,
            "auto_media_cooldown_seconds": 600,
            "auto_emotion_probability": 1.0,
        },
    }


@unittest.skipUnless(HAS_MEDIA, "local media assets are not included in this repository")
class EmotionMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.media = MediaRegistry({"path": str(ROOT / "assets")})
        self.selector = EmotionMediaSelector(
            self.media, {"auto_emotion_probability": 1.0}
        )

    def test_daily_sad_selects_a_local_sad_image(self) -> None:
        picked = self.selector.pick("今天好累，不想动了", "sakura_winter", 1)
        self.assertIn(
            picked,
            {"sakura_user_sleepy", "sakura_user_rainy_phone", "sakura_user_flower_calm"},
        )
        self.assertIsNotNone(self.media.resolve("image", picked))

    def test_daily_happy_selects_a_local_happy_image(self) -> None:
        picked = self.selector.pick("今天赢了，好开心哈哈哈", "sakura_winter", 2)
        self.assertIn(
            picked,
            {
                "sakura_user_happy_laugh",
                "sakura_user_smile_closed",
                "sakura_user_spring_smile",
                "sakura_user_white_dress_smile",
                "sakura_user_gentle_smile",
                "sakura_user_soft_gaze",
                "sakura_user_warm_greeting",
            },
        )

    def test_new_daily_gifs_are_registered_and_resolvable(self) -> None:
        for name in ("sakura_user_soft_gaze", "sakura_user_warm_greeting"):
            resolved = self.media.resolve("image", name)
            self.assertIsNotNone(resolved)
            self.assertTrue(str(resolved["data"]["file"]).lower().endswith(".gif"))

    def test_black_possessive_selects_black_media(self) -> None:
        picked = self.selector.pick("前辈今天和别人出去玩", "sakura_black", 3)
        self.assertIn(
            picked,
            {"black_sakura_dark_smile", "black_sakura_provoking", "black_sakura_calm_closed_eye"},
        )
        self.assertTrue(str(picked).startswith("black_sakura_"))

    def test_serious_technical_message_does_not_add_media(self) -> None:
        self.assertIsNone(self.selector.pick("帮我看看代码报错", "sakura_winter", 4))

    def test_recent_images_are_not_repeated_immediately(self) -> None:
        picks = [
            self.selector.pick("今天好累", "sakura_winter", 5) for _ in range(3)
        ]
        for previous, current in zip(picks, picks[1:]):
            self.assertNotEqual(previous, current)

    def test_dispatcher_appends_daily_emotion_image(self) -> None:
        transport = FakeTransport()
        dispatcher = MessageDispatcher(
            _config(),
            Store(":memory:"),
            FakeLLM("前辈先休息一下吧。"),
            str(ROOT / "bot" / "persona" / "system.md"),
        )

        asyncio.run(dispatcher.handle_raw(transport, _event("今天好累", 1)))

        messages = [message for _, message in transport.group]
        self.assertTrue(
            any(
                isinstance(message, list)
                and any(
                    isinstance(segment, dict) and segment.get("type") == "image"
                    for segment in message
                )
                for message in messages
            )
        )


if __name__ == "__main__":
    unittest.main()
