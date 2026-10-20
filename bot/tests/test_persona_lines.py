"""Regression tests for rotating persona lines and black-Sakura image choices."""

from __future__ import annotations

import asyncio
import json
import random
import unittest
from pathlib import Path

from core.dispatcher import MessageDispatcher
from core.persona_lines import (
    BLACK_INSULT_LINES,
    BLACK_SWITCH_LINES,
    FORCE_BLACK_LINES,
    LineRotator,
    PersonaLine,
)
from storage.store import Store


ROOT = Path(__file__).resolve().parents[2]
MEDIA_ROOT = ROOT / "assets" / "stickers"
HAS_MEDIA = any(
    path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    for path in MEDIA_ROOT.rglob("*")
    if path.is_file()
)


class FakeTransport:
    def __init__(self) -> None:
        self.group: list[tuple[int, object]] = []

    async def send_group_message(self, group_id: int, message: object) -> None:
        self.group.append((group_id, message))

    async def send_private_message(self, user_id: int, message: object) -> None:
        pass

    async def set_qq_avatar(self, path: str) -> None:
        pass


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages):
        self.calls.append(messages)
        return f"黑樱生成回复{len(self.calls)}"

    async def chat_with_mode(self, messages, mode="fast"):
        self.calls.append(messages)
        return f"黑樱生成回复{len(self.calls)}"


class FailingLLM:
    async def chat(self, messages):
        raise RuntimeError("api down")

    async def chat_with_mode(self, messages, mode="fast"):
        raise RuntimeError("api down")


def _group_event(text: str, message_id: int) -> str:
    return json.dumps(
        {
            "post_type": "message",
            "message_type": "group",
            "self_id": 999,
            "user_id": 42,
            "group_id": 100,
            "message_id": message_id,
            "message": [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": text}},
            ],
            "sender": {"user_id": 42, "nickname": "测试群友", "role": "member"},
        },
        ensure_ascii=False,
    )


class PersonaLineTests(unittest.TestCase):
    @unittest.skipUnless(HAS_MEDIA, "local media assets are not included in this repository")
    def test_switch_and_force_images_exist_in_manifest(self) -> None:
        manifest = json.loads(
            (ROOT / "assets" / "stickers" / "manifest.json").read_text(encoding="utf-8")
        )
        for line in BLACK_SWITCH_LINES + FORCE_BLACK_LINES:
            if line.image is None:
                continue
            self.assertIn(line.image, manifest)
            self.assertTrue((ROOT / "assets" / "stickers" / manifest[line.image]["file"]).is_file())

    def test_render_appends_image_marker(self) -> None:
        self.assertEqual("测试", PersonaLine("测试").render())
        self.assertEqual("测试[image:black_sakura_warning]", PersonaLine("测试", "black_sakura_warning").render())

    def test_rotator_never_repeats_consecutively(self) -> None:
        rotator = LineRotator(random.Random(7))
        picks = [
            rotator.pick("black_insult", 1, BLACK_INSULT_LINES).text
            for _ in range(30)
        ]
        for previous, current in zip(picks, picks[1:]):
            self.assertNotEqual(previous, current)

    def test_rotator_is_isolated_per_group(self) -> None:
        rotator = LineRotator(random.Random(1))
        first = [rotator.pick("p", 1, BLACK_INSULT_LINES).text for _ in range(2)]
        second = [rotator.pick("p", 2, BLACK_INSULT_LINES).text for _ in range(2)]
        self.assertNotEqual(first[0], first[1])
        self.assertNotEqual(second[0], second[1])

    def test_black_switch_pool_has_distinct_images(self) -> None:
        images = {line.image for line in BLACK_SWITCH_LINES if line.image}
        self.assertGreaterEqual(len(images), 3)

    @unittest.skipUnless(HAS_MEDIA, "local media assets are not included in this repository")
    def test_consecutive_black_insults_use_deepseek_and_differ(self) -> None:
        store = Store(":memory:")
        config = {
            "access": {
                "allowed_group_ids": [100],
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
            "media": {"auto_emotion_enabled": False},
        }
        llm = FakeLLM()
        transport = FakeTransport()
        dispatcher = MessageDispatcher(
            config, store, llm, str(ROOT / "bot" / "persona" / "system.md")
        )

        async def run() -> list[str]:
            replies: list[str] = []
            for message_id in range(1, 6):
                before = len(transport.group)
                await dispatcher.handle_raw(transport, _group_event("fw", message_id))
                parts = [str(message) for _, message in transport.group[before:]]
                replies.append("".join(parts))
            return replies

        replies = asyncio.run(run())

        # 1st/2nd are Sakura warnings, 3rd is the black switch, 4th/5th are black replies.
        self.assertNotEqual(replies[3], replies[4])
        switch_messages = [message for _, message in transport.group if isinstance(message, list)]
        self.assertTrue(
            any(
                any(isinstance(segment, dict) and segment.get("type") == "image" for segment in message)
                for message in switch_messages
            )
        )
        self.assertGreaterEqual(len(llm.calls), 3)
        for messages in llm.calls:
            system = messages[0]["content"]
            self.assertTrue(system.startswith("# 黑樱 Persona"))
            self.assertIn("【本轮任务】", system)
            self.assertIn("你不是原版樱", system)

    def test_opted_out_user_does_not_upload_insult_to_api(self) -> None:
        store = Store(":memory:")
        store.forget(100, 42)
        config = {
            "access": {
                "allowed_group_ids": [100],
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
            "media": {"auto_emotion_enabled": False},
        }
        llm = FakeLLM()
        transport = FakeTransport()
        dispatcher = MessageDispatcher(
            config, store, llm, str(ROOT / "bot" / "persona" / "system.md")
        )

        async def run() -> None:
            for message_id in range(1, 5):
                await dispatcher.handle_raw(transport, _group_event("fw", message_id))

        asyncio.run(run())
        self.assertEqual([], llm.calls)
        self.assertGreaterEqual(len(transport.group), 1)

    def test_black_reply_falls_back_when_api_fails(self) -> None:
        store = Store(":memory:")
        config = {
            "access": {
                "allowed_group_ids": [100],
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
            "media": {"auto_emotion_enabled": False},
        }
        transport = FakeTransport()
        dispatcher = MessageDispatcher(
            config, store, FailingLLM(), str(ROOT / "bot" / "persona" / "system.md")
        )

        async def run() -> None:
            for message_id in range(1, 5):
                await dispatcher.handle_raw(transport, _group_event("fw", message_id))

        asyncio.run(run())

        self.assertGreaterEqual(len(transport.group), 1)
        last_message = transport.group[-1][1]
        self.assertTrue(str(last_message).strip())


if __name__ == "__main__":
    unittest.main()
