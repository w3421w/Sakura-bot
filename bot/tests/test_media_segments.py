from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from transport.media import MediaRegistry


class MediaSegmentTests(unittest.TestCase):
    def test_plain_reply_remains_compatible_string(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = MediaRegistry({"path": directory})
            self.assertEqual("好的前辈", registry.render("好的前辈"))

    def test_named_face_marker_becomes_onebot_segment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stickers").mkdir()
            (root / "stickers" / "manifest.json").write_text(
                json.dumps({"shy": {"type": "face", "id": 6}}), encoding="utf-8"
            )
            registry = MediaRegistry({"path": directory})
            self.assertEqual(
                [
                    {"type": "text", "data": {"text": "好的前辈 "}},
                    {"type": "face", "data": {"id": 6}},
                ],
                registry.render("好的前辈 [sticker:shy]"),
            )

    def test_image_marker_is_confined_to_sticker_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stickers = root / "stickers"
            stickers.mkdir()
            (stickers / "sakura.png").write_bytes(b"not a real image")
            (stickers / "manifest.json").write_text(
                json.dumps({"sakura": {"type": "image", "file": "sakura.png"}}),
                encoding="utf-8",
            )
            registry = MediaRegistry({"path": directory})
            result = registry.render("[image:sakura]")
            self.assertIsInstance(result, list)
            assert isinstance(result, list)
            self.assertEqual("image", result[0]["type"])
            self.assertTrue(str(result[0]["data"]["file"]).endswith("sakura.png"))

    def test_unknown_marker_is_not_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = MediaRegistry({"path": directory})
            self.assertEqual("前辈", registry.render("前辈 [sticker:unknown]"))


if __name__ == "__main__":
    unittest.main()
