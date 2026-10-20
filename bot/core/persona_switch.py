"""Per-group persona escalation and QQ avatar switching."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.persona_lines import BLACK_SWITCH_IMAGE_LINES


LOG = logging.getLogger("qwbot.persona")


@dataclass
class PersonaState:
    mode: str = "sakura"
    insult_count: int = 0
    last_insult_at: float | None = None
    auto_black: bool = False
    changed_at: float = 0.0
    switch_count: int = 0


class PersonaSwitchManager:
    """Keep Sakura/Black Sakura state isolated per group.

    The insult counter is deliberately deterministic: the first two directed
    insults stay in the Sakura persona, while the third enters Black Sakura.
    Black Sakura lasts ``quiet_seconds`` from the switch, for both automatic
    escalation and an explicit @ switch; later insults do not extend it.
    State is persisted when a store is supplied, so a restart neither loses
    Black Sakura nor resets its timer.
    """

    DEFAULT_INSULTS = (
        "婊子",
        "鸡",
        "烧鸡",
        "燒貨",
        "烧货",
        "骚货",
        "賤人",
        "贱人",
        "臭婊",
        "傻逼",
        "傻比",
        "煞笔",
        "沙币",
        "杀币",
        "傻吊",
        "傻屌",
        "傻卵",
        "脑残",
        "脑瘫",
        "智障",
        "弱智",
        "废物",
        "蠢货",
        "垃圾",
        "狗东西",
        "狗逼",
        "畜生",
        "出生",
        "孤儿",
        "小丑",
        "沙雕",
        "下头",
        "神经病",
        "有病",
        "草泥马",
        "cnm",
        "nmsl",
        "wdnmd",
        "mdzz",
        "sb",
        "ntm",
        "fw",
    )

    def __init__(self, config: dict[str, Any], store: Any = None) -> None:
        settings = config.get("persona_switch", {})
        self.enabled = bool(settings.get("enabled", True))
        self.sakura_persona = str(settings.get("sakura_persona", "sakura_winter"))
        self.black_persona = str(settings.get("black_persona", "sakura_black"))
        self.insult_threshold = max(3, int(settings.get("insult_threshold", 3)))
        self.quiet_seconds = max(60, int(settings.get("quiet_seconds", 1800)))
        self.black_avatar = self._path(settings.get("black_avatar", ""))
        self.sakura_avatar = self._path(settings.get("sakura_avatar", ""))
        configured = settings.get("insult_keywords") or self.DEFAULT_INSULTS
        self.insult_keywords = tuple(
            sorted({str(item).strip() for item in configured if str(item).strip()}, key=len, reverse=True)
        )
        configured_names = settings.get("directed_names") or ("樱", "间桐樱", "黑樱", "桜", "sakura")
        self.directed_names = tuple(str(item).casefold() for item in configured_names if str(item).strip())
        self.store = store
        self._states: dict[int, PersonaState] = {}
        if store is not None:
            try:
                for group_id, row in store.load_persona_states().items():
                    self._states[int(group_id)] = PersonaState(**row)
            except Exception:
                LOG.exception("persona state load failed")

    @staticmethod
    def _path(value: Any) -> Path | None:
        text = str(value or "").strip()
        return Path(text).resolve() if text else None

    def state(self, group_id: int) -> PersonaState:
        return self._states.setdefault(int(group_id), PersonaState())

    def states(self) -> dict[int, PersonaState]:
        return dict(self._states)

    def _persist(self, group_id: int) -> None:
        if self.store is None:
            return
        current = self.state(group_id)
        try:
            self.store.save_persona_state(
                group_id,
                mode=current.mode,
                insult_count=current.insult_count,
                last_insult_at=current.last_insult_at,
                auto_black=current.auto_black,
                changed_at=current.changed_at,
                switch_count=current.switch_count,
            )
        except Exception:
            LOG.exception("persona state persist failed group_id=%s", group_id)

    def persona_for(self, group_id: int) -> str:
        return self.black_persona if self.state(group_id).mode == "black" else self.sakura_persona

    def avatar_for(self, mode: str) -> Path | None:
        return self.black_avatar if mode == "black" else self.sakura_avatar

    def switch_image(self, group_id: int) -> str | None:
        """Cycle switch images deterministically, persisted across restarts."""
        if not BLACK_SWITCH_IMAGE_LINES:
            return None
        index = max(0, self.state(group_id).switch_count - 1)
        return BLACK_SWITCH_IMAGE_LINES[index % len(BLACK_SWITCH_IMAGE_LINES)].image

    def restore_if_quiet(self, group_id: int, now: float | None = None) -> bool:
        if not self.enabled:
            return False
        current = self.state(group_id)
        moment = time.time() if now is None else float(now)
        started = current.changed_at if current.changed_at > 0 else current.last_insult_at
        if (
            current.mode == "black"
            and current.auto_black
            and started is not None
            and moment - started >= self.quiet_seconds
        ):
            current.mode = "sakura"
            current.insult_count = 0
            current.last_insult_at = None
            current.auto_black = False
            current.changed_at = moment
            self._persist(group_id)
            return True
        return False

    def restore_expired(self, now: float | None = None) -> list[int]:
        """Restore every black group whose quiet period elapsed."""
        moment = time.time() if now is None else float(now)
        return [
            group_id
            for group_id in tuple(self._states)
            if self.restore_if_quiet(group_id, moment)
        ]

    def force(self, group_id: int, mode: str, now: float | None = None) -> bool:
        if mode not in {"sakura", "black"}:
            return False
        moment = time.time() if now is None else float(now)
        current = self.state(group_id)
        changed = current.mode != mode or current.auto_black
        current.mode = mode
        # An explicit @ switch is still a temporary Black Sakura state; it
        # expires after the same quiet period.  Only another insult or another
        # @ switch restarts the timer.
        current.auto_black = mode == "black"
        current.last_insult_at = moment if mode == "black" else None
        current.insult_count = 0
        current.changed_at = moment
        if mode == "black":
            current.switch_count += 1
        self._persist(group_id)
        return changed

    def insult_level(self, group_id: int, now: float | None = None) -> tuple[int, bool]:
        """Return (count, switched_to_black) for a directed insult."""
        if not self.enabled:
            return 0, False
        moment = time.time() if now is None else float(now)
        self.restore_if_quiet(group_id, moment)
        current = self.state(group_id)
        current.last_insult_at = moment
        if current.mode == "black":
            self._persist(group_id)
            return current.insult_count, False
        current.insult_count += 1
        if current.insult_count >= self.insult_threshold:
            current.mode = "black"
            current.auto_black = True
            current.changed_at = moment
            current.switch_count += 1
            self._persist(group_id)
            return current.insult_count, True
        self._persist(group_id)
        return current.insult_count, False

    def find_insult(self, text: str, *, mentioned: bool = False) -> str | None:
        normalized = re.sub(r"\s+", "", str(text or "")).casefold()
        benign_compounds = {
            "垃圾": ("垃圾分类", "垃圾桶", "垃圾袋", "垃圾车", "垃圾处理", "垃圾回收"),
            "废物": ("废物利用", "废物处理", "废物回收"),
            "出生": ("出生日期", "出生证明", "出生地", "出生率"),
            "小丑": ("小丑鱼",),
        }
        for term in self.insult_keywords:
            folded = term.casefold()
            if folded not in normalized:
                continue
            if any(context in normalized for context in benign_compounds.get(folded, ())):
                continue
            # Avoid treating ordinary food/game words such as “鸡汤” or
            # “鸡排” as an insult when the bot is mentioned.
            if folded == "鸡" and normalized not in {"鸡", "你是鸡", "你这个鸡", "臭鸡"}:
                if not re.search(r"(?:你|这个|真是|就是|臭|骚).{0,2}鸡|鸡.{0,2}(你|吧|货)", normalized):
                    # A direct @ mention makes a bare “鸡” an insult, while
                    # compound forms such as “烧鸡” are covered explicitly
                    # by the keyword above. This keeps ordinary food talk
                    # uncounted unless it is aimed at the bot.
                    if not (mentioned and normalized.endswith("鸡")):
                        continue
            return term
        return None

    def is_directed(self, text: str, *, mentioned: bool) -> bool:
        if mentioned:
            return True
        normalized = str(text or "").casefold()
        return any(name and name in normalized for name in self.directed_names)

    @staticmethod
    def force_target(text: str) -> str | None:
        normalized = re.sub(r"\s+", "", str(text or "")).casefold()
        if any(token in normalized for token in ("切换黑樱", "黑樱人格", "进入黑樱", "黑樱模式", "/黑樱")):
            return "black"
        if any(
            token in normalized
            for token in (
                "切换原版樱",
                "原版樱人格",
                "原版樱",
                "恢复原版樱",
                "切回原版樱",
                "切回樱",
                "回到原版樱",
                "樱人格",
                "/原版樱",
            )
        ):
            return "sakura"
        return None
