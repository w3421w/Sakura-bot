"""Privacy and administration commands."""

from __future__ import annotations

from dataclasses import dataclass

from storage.store import Store
from transport.events import OneBotEvent
from persona.catalog import PersonaCatalog


@dataclass(frozen=True)
class CommandResult:
    handled: bool
    reply: str = ""


class CommandRouter:
    def __init__(
        self,
        store: Store,
        config: dict,
        *,
        persona_catalog: PersonaCatalog | None = None,
    ) -> None:
        self.store = store
        self.persona_catalog = persona_catalog
        access = config.get("access", {})
        self.admin_user_ids: set[int] = set(access.get("admin_user_ids", set()))
        self.group_consent_confirmed = bool(access.get("group_consent_confirmed", False))
        self.retention_days = int(config.get("storage", {}).get("retention_days", 14))
        self.llm_privacy_text = "消息会发送到 DeepSeek API；请仅在群成员知情同意后使用。"

    def handle(self, event: OneBotEvent, text: str) -> CommandResult:
        if not (event.is_group_message or event.is_private_message) or event.user_id is None:
            return CommandResult(False)
        is_private = event.is_private_message
        group_id = event.group_id if event.group_id is not None else 0
        user_id = event.user_id
        command = text.strip()
        if command == "/隐私说明":
            scope = "本次私聊" if is_private else "本群"
            return CommandResult(
                True,
                f"{scope}启用授权后，未退出成员的纯文本消息可用于上下文和记忆。"
                f"原始消息本地保留{self.retention_days}天；发送 /忘记我 可删除并退出，"
                "发送 /同意记录 可重新加入。" + self.llm_privacy_text,
            )
        if command in {"/人格", "/人格列表", "/personas"}:
            if self.persona_catalog is None:
                return CommandResult(True, "当前未配置人格目录。")
            personas = self.persona_catalog.list()
            if not personas:
                return CommandResult(True, "当前没有可用人格。")
            names = "、".join(f"{item.id}（{item.name}）" for item in personas[:12])
            suffix = "" if len(personas) <= 12 else f"……共{len(personas)}个"
            return CommandResult(True, "可用人格：" + names + suffix)
        if command == "/同意记录":
            if not is_private and not self.group_consent_confirmed:
                return CommandResult(True, "本群尚未完成群级知情同意，暂不能开启记录。")
            self.store.agree(group_id, user_id)
            reply = "已开启你的私聊上下文记录。" if is_private else "已恢复你的群聊上下文记录。"
            return CommandResult(True, reply + "发送 /忘记我 可随时退出并删除原始消息。")
        if command in {"/忘记我", "/不记录我"}:
            self.store.forget(group_id, user_id)
            return CommandResult(
                True,
                ("已删除你在本次私聊中的原始消息，并停止后续记录。"
                 if is_private else "已删除你在本群的原始消息，并停止后续记录。")
                + "如需重新参加，请发送 /同意记录。",
            )
        if command == "/机器人状态" and user_id in self.admin_user_ids:
            status = self.store.status(group_id)
            return CommandResult(
                True,
                "QWbot 在线。"
                f"群级授权={self.group_consent_confirmed}，"
                f"消息数={status['messages']}，退出记录人数={status['opt_out']}，"
                f"已批准记忆={status['approved_memories']}。",
            )
        return CommandResult(False)
