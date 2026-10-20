"""Automatic emotion-matched Sakura image selection for casual chat.

The LLM may already choose a whitelisted ``[image:name]`` marker.  When it does
not, this selector adds at most one local image whose catalog emotion matches
the current message and reply.  It never emits remote URLs and never touches
files outside the sticker manifest.
"""

from __future__ import annotations

import json
import logging
import random
import re
from collections import deque
from pathlib import Path
from typing import Any

from transport.media import MediaRegistry


LOG = logging.getLogger("qwbot.emotion_media")


class EmotionMediaSelector:
    def __init__(self, media: MediaRegistry, config: dict[str, Any] | None = None) -> None:
        self.media = media
        self.config = config or {}
        self.map = self._load_map()
        self.probability = max(0.0, min(1.0, float(self.config.get("auto_emotion_probability", 0.7))))
        self._rng = random.Random()
        self._recent: dict[int, deque[str]] = {}

    def _load_map(self) -> dict[str, Any]:
        path = Path(self.media.root) / "stickers" / "emotion_map.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            LOG.warning("emotion map unavailable: %s", path)
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _normalise(text: str) -> str:
        return " ".join(str(text or "").split()).casefold()

    def _available(self, names: Any) -> list[str]:
        if not isinstance(names, list):
            return []
        result: list[str] = []
        for name in names:
            candidate = str(name).strip()
            if not candidate or candidate in result:
                continue
            if candidate not in self.media.manifest:
                continue
            if self.media.resolve("image", candidate) is None:
                continue
            result.append(candidate)
        return result

    def _matches(self, text: str, keywords: Any) -> bool:
        return isinstance(keywords, list) and any(
            str(keyword).casefold() in text for keyword in keywords if str(keyword).strip()
        )

    def _choose(self, group_id: int, names: list[str]) -> str | None:
        if not names:
            return None
        recent = self._recent.setdefault(int(group_id), deque(maxlen=4))
        candidates = [name for name in names if name not in recent] or names
        if not candidates:
            return None
        picked = self._rng.choice(candidates)
        recent.append(picked)
        return picked

    def pick(self, text: str, persona: str, group_id: int) -> str | None:
        if not self.map:
            return None
        normalised = self._normalise(text)
        if len(normalised) < 3:
            return None
        serious = self.map.get("serious_markers", [])
        if isinstance(serious, list) and any(str(item).casefold() in normalised for item in serious):
            return None
        if self._rng.random() > self.probability:
            return None

        black = "black" in str(persona).casefold()
        if black:
            emotions = self.map.get("black_emotions", {})
            for emotion in self.map.get("black_priority", []):
                if not self._matches(normalised, emotions.get(emotion)):
                    continue
                names = self._available(
                    self.map.get("black", {}).get(
                        {"possessive": "dark_smile", "playful": "provoking"}.get(emotion, emotion)
                    )
                )
                picked = self._choose(group_id, names)
                if picked:
                    return picked
            return None

        for emotion in self.map.get("daily_priority", []):
            if not self._matches(normalised, self.map.get("keywords", {}).get(emotion)):
                continue
            names = self._available(self.map.get("daily", {}).get(emotion))
            picked = self._choose(group_id, names)
            if picked:
                return picked
        return None
