"""Safe rendering of model media markers into OneBot11 message segments."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any


LOG = logging.getLogger("qwbot.media")
MARKER_RE = re.compile(r"\[(sticker|face|image):([^\]\s]{1,120})\]", re.IGNORECASE)
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class MediaRegistry:
    """Resolve operator-approved media names; model output never supplies paths."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        settings = config or {}
        self.root = Path(settings.get("path", "assets")).resolve()
        self.max_file_bytes = max(1024, int(settings.get("max_file_bytes", 8 * 1024 * 1024)))
        self.max_segments = max(1, int(settings.get("max_segments", 8)))
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict[str, dict[str, Any]]:
        path = self.root / "stickers" / "manifest.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            LOG.warning("media manifest could not be loaded: %s", path)
            return {}
        return {
            str(name).casefold(): value
            for name, value in payload.items()
            if isinstance(name, str) and isinstance(value, dict)
        }

    def _safe_file(self, value: Any) -> Path | None:
        candidate = (self.root / "stickers" / str(value)).resolve()
        try:
            candidate.relative_to((self.root / "stickers").resolve())
        except ValueError:
            return None
        if candidate.suffix.casefold() not in ALLOWED_IMAGE_EXTENSIONS:
            return None
        try:
            if not candidate.is_file() or candidate.stat().st_size > self.max_file_bytes:
                return None
        except OSError:
            return None
        return candidate

    def resolve(self, kind: str, name: str) -> dict[str, Any] | None:
        lowered_kind = kind.casefold()
        lowered_name = name.casefold()
        if lowered_kind == "face" and lowered_name.isdigit():
            face_id = int(lowered_name)
            if 0 <= face_id <= 999:
                return {"type": "face", "data": {"id": face_id}}
            return None
        entry = self.manifest.get(lowered_name)
        if not entry:
            return None
        entry_type = str(entry.get("type", "")).casefold()
        if lowered_kind == "sticker" and entry_type == "face":
            try:
                face_id = int(entry["id"])
            except (KeyError, TypeError, ValueError):
                return None
            if 0 <= face_id <= 999:
                return {"type": "face", "data": {"id": face_id}}
        if lowered_kind in {"sticker", "image"} and entry_type == "image":
            file_path = self._safe_file(entry.get("file"))
            if file_path is not None:
                return {"type": "image", "data": {"file": str(file_path)}}
        return None

    def render(self, text: str) -> str | list[dict[str, Any]]:
        """Return a plain string when no marker is present, otherwise segments."""
        raw = str(text or "").strip()
        if not raw or not MARKER_RE.search(raw):
            return raw
        segments: list[dict[str, Any]] = []
        resolved_count = 0
        cursor = 0
        for match in MARKER_RE.finditer(raw):
            before = raw[cursor : match.start()]
            if before:
                segments.append({"type": "text", "data": {"text": before}})
            resolved = self.resolve(match.group(1), match.group(2))
            if resolved is not None:
                segments.append(resolved)
                resolved_count += 1
            else:
                LOG.warning("blocked unknown media marker kind=%s name=%s", match.group(1), match.group(2))
            cursor = match.end()
        tail = raw[cursor:]
        if tail:
            segments.append({"type": "text", "data": {"text": tail}})
        if len(segments) > self.max_segments:
            segments = segments[: self.max_segments]
        if resolved_count == 0:
            return "".join(
                str(segment.get("data", {}).get("text", ""))
                for segment in segments
                if segment.get("type") == "text"
            ).strip()
        if not segments:
            return ""
        return segments
