"""Pure OneBot11 event parsing helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


CQ_RE = re.compile(r"\[CQ:[^\]]+\]")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def text_only(message: Any, limit: int = 900) -> str:
    """Extract text segments and remove CQ markup from string messages."""
    if isinstance(message, str):
        return CQ_RE.sub("", message).strip()[:limit]
    if isinstance(message, list):
        text = "".join(
            str(segment.get("data", {}).get("text", ""))
            for segment in message
            if isinstance(segment, dict) and segment.get("type") == "text"
        )
        return text.strip()[:limit]
    return ""


def mentioned(event: "OneBotEvent") -> bool:
    """Return whether this event contains an @ mention of the bot itself."""
    bot_id = str(event.self_id or "")
    if not bot_id:
        return False
    message = event.raw.get("message", [])
    if isinstance(message, list):
        return any(
            isinstance(segment, dict)
            and segment.get("type") == "at"
            and str(segment.get("data", {}).get("qq", "")) == bot_id
            for segment in message
        )
    return bool(re.search(r"\[CQ:at,qq=" + re.escape(bot_id) + r"(?:,|\])", str(message)))


@dataclass(frozen=True)
class OneBotEvent:
    raw: dict[str, Any]
    post_type: str | None
    message_type: str | None
    group_id: int | None
    user_id: int | None
    self_id: int | None
    message_id: int | str | None

    @property
    def is_group_message(self) -> bool:
        return self.post_type == "message" and self.message_type == "group" and self.group_id is not None

    @property
    def is_private_message(self) -> bool:
        return self.post_type == "message" and self.message_type == "private" and self.user_id is not None

    @property
    def message(self) -> Any:
        return self.raw.get("message", self.raw.get("raw_message", ""))

    @property
    def dedup_key(self) -> tuple[str, str]:
        message_id = self.message_id if self.message_id is not None else id(self.raw)
        scope = str(self.group_id if self.group_id is not None else self.user_id)
        return scope, str(message_id)

    @property
    def conversation_id(self) -> str:
        """Stable account-scoped conversation identifier."""
        account = str(self.self_id or "unknown")
        if self.is_group_message and self.group_id is not None:
            return f"{account}:group:{self.group_id}"
        return f"{account}:direct:{self.user_id or 0}"

    @property
    def sender_info(self) -> dict[str, Any]:
        sender = self.raw.get("sender")
        return dict(sender) if isinstance(sender, dict) else {}


def parse_event(raw: str | bytes | dict[str, Any]) -> OneBotEvent | None:
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    else:
        data = raw
    if not isinstance(data, dict):
        return None
    return OneBotEvent(
        raw=data,
        post_type=data.get("post_type"),
        message_type=data.get("message_type"),
        group_id=_int_or_none(data.get("group_id")),
        user_id=_int_or_none(data.get("user_id")),
        self_id=_int_or_none(data.get("self_id")),
        message_id=data.get("message_id"),
    )
