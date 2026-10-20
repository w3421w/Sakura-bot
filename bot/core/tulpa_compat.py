"""Small QWbot-native subset of Tulpa's safety and session conventions.

This module deliberately has no dependency on Tulpa's runtime.  It gives the
existing bot stable conversation IDs and idempotency keys while keeping the
current OneBot transport as the only event consumer.
"""

from __future__ import annotations

from dataclasses import dataclass

from transport.events import OneBotEvent


@dataclass(frozen=True)
class Conversation:
    account_id: int | None
    kind: str
    peer_id: int

    @property
    def id(self) -> str:
        account = str(self.account_id or "unknown")
        return f"{account}:{self.kind}:{self.peer_id}"


class TulpaPolicy:
    """Conversation and send policy adapted to QWbot's existing config."""

    def __init__(self, config: dict) -> None:
        access = config.get("access", {})
        self.allowed_groups = {int(value) for value in access.get("allowed_group_ids", [])}
        self.allowed_private_users = {
            int(value) for value in access.get("allowed_private_user_ids", [])
        }
        self.require_group_whitelist = bool(access.get("require_group_whitelist", True))

    def conversation(self, event: OneBotEvent) -> Conversation:
        if event.is_group_message and event.group_id is not None:
            return Conversation(event.self_id, "group", event.group_id)
        return Conversation(event.self_id, "direct", int(event.user_id or 0))

    def scope_allowed(self, event: OneBotEvent) -> bool:
        if event.is_group_message:
            return not self.require_group_whitelist or event.group_id in self.allowed_groups
        if event.is_private_message and self.allowed_private_users:
            return event.user_id in self.allowed_private_users
        return event.is_private_message

    @staticmethod
    def event_key(event: OneBotEvent) -> str:
        scope = str(event.group_id if event.group_id is not None else event.user_id or "unknown")
        message_id = str(event.message_id or "no-message-id")
        return f"onebot:{event.post_type or 'unknown'}:{event.message_type or 'unknown'}:{scope}:{message_id}"

    @staticmethod
    def idempotency_key(event: OneBotEvent, text: str, purpose: str = "reply") -> str:
        # One inbound event should produce at most one outbound operation of a
        # given purpose, even if its generated wording changes after a restart.
        return f"{purpose}:{TulpaPolicy.event_key(event)}"

