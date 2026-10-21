"""Local Hearthstone deck retrieval and review context.

The advisor never scrapes at request time.  The daily collector writes a small
structured JSON file under ``knowledge/hearthstone/decks``; this module reads it
and produces bounded context for the LLM.  A user-supplied deck code can also be
decoded locally, without any network request.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from knowledge.deck_code import (
    CLASS_NAMES,
    DeckCodeError,
    decode_deckstring,
    deck_code_in_text,
    load_card_map,
    summarize_deck,
)


DECK_TERMS = (
    "炉石",
    "卡组",
    "套牌",
    "卡组代码",
    "deck",
    "标准模式",
    "狂野模式",
    "上分",
    "冲分",
    "天梯",
    "传说",
    "环境",
)
REVIEW_TERMS = (
    "点评",
    "评价",
    "强度",
    "怎么样",
    "如何",
    "值得",
    "推荐",
    "能玩",
    "上分",
    "优化",
    "改",
    "曲线",
    "胜率",
    "克制",
    "对局",
)
CLASS_TERMS = (
    "死亡骑士", "恶魔猎手", "德鲁伊", "猎人", "法师", "圣骑士", "牧师",
    "潜行者", "盗贼", "萨满", "术士", "战士", "dk", "dh",
)
ARCHETYPE_TERMS = (
    "快攻", "中速", "控制", "OTK", "组合技", "宇宙", "任务", "龙", "法术",
    "海盗", "鱼人", "野兽", "亡语", "铺场", "节奏", "光环", "灌注", "星舰",
    "发现", "污手", "大哥", "奇迹", "超生", "机械",
)


class DeckAdvisor:
    """Load deck records and build bounded context for a Hearthstone question."""

    def __init__(self, config: dict[str, Any], *, base_dir: str | Path | None = None) -> None:
        settings = config.get("hearthstone", {}) if isinstance(config, dict) else {}
        self.enabled = bool(settings.get("enabled", True))
        base = Path(base_dir) if base_dir else Path.cwd()
        self.decks_path = self._resolve(settings.get("decks_path", "../knowledge/hearthstone/decks/latest.json"), base)
        self.cards_path = self._resolve(settings.get("cards_path", "../data/hearthstone_cards.json"), base)
        self.max_decks = max(1, min(5, int(settings.get("max_decks", 3))))
        self._decks: list[dict[str, Any]] = []
        self._deck_mtime: float = -1.0
        self._cards: dict[int, dict[str, Any]] | None = None
        self._last_by_scope: dict[int, list[dict[str, Any]]] = {}
        self._load_decks()

    @staticmethod
    def _resolve(value: Any, base: Path) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else (base / path).resolve()

    def _load_decks(self) -> None:
        if not self.enabled:
            self._decks = []
            return
        try:
            stat = self.decks_path.stat()
        except OSError:
            self._decks = []
            return
        if stat.st_mtime == self._deck_mtime:
            return
        try:
            payload = json.loads(self.decks_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._decks = []
            return
        if isinstance(payload, dict):
            raw_decks = payload.get("decks", [])
        elif isinstance(payload, list):
            raw_decks = payload
        else:
            raw_decks = []
        self._decks = [item for item in raw_decks if isinstance(item, dict)]
        self._deck_mtime = stat.st_mtime

    def _card_map(self) -> dict[int, dict[str, Any]]:
        if self._cards is None:
            self._cards = load_card_map(self.cards_path)
        return self._cards

    def is_deck_query(self, text: str) -> bool:
        if not self.enabled:
            return False
        raw = str(text or "")
        if deck_code_in_text(raw):
            return True
        lowered = raw.casefold()
        has_deck = any(term.casefold() in lowered for term in DECK_TERMS)
        has_review = any(term.casefold() in lowered for term in REVIEW_TERMS)
        has_class = any(term.casefold() in lowered for term in CLASS_TERMS)
        has_class = has_class or bool(
            re.search(
                r"(?:萨|战|贼|猎|法|牧|术|德|骑|瞎)(?:怎么样|强度|卡组|推荐|攻略|能玩|上分|好|吗|呢|？|$)",
                lowered,
            )
        )
        has_archetype = any(term.casefold() in lowered for term in ARCHETYPE_TERMS)
        return has_deck or (has_class and (has_review or has_archetype))

    def _score(self, deck: dict[str, Any], query: str) -> int:
        q = query.casefold()
        score = 0
        fields = (
            ("name", 5),
            ("archetype", 5),
            ("class_zh", 4),
            ("class", 3),
            ("title", 2),
            ("source", 1),
            ("strength_note", 1),
        )
        for field, weight in fields:
            value = str(deck.get(field) or "").casefold()
            if value and value in q:
                score += weight
        for tag in deck.get("tags", []) if isinstance(deck.get("tags"), list) else []:
            if str(tag).casefold() in q:
                score += 2
        for term in CLASS_TERMS + ARCHETYPE_TERMS:
            if term.casefold() in q and term.casefold() in str(deck).casefold():
                score += 1
        return score

    def find_decks(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        self._load_decks()
        if not self._decks:
            return []
        scored = [(self._score(deck, query), index, deck) for index, deck in enumerate(self._decks)]
        scored = [item for item in scored if item[0] > 0]
        if not scored and any(term.casefold() in query.casefold() for term in DECK_TERMS):
            return [dict(deck) for deck in self._decks[: (limit or self.max_decks)]]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [dict(item[2]) for item in scored[: (limit or self.max_decks)]]

    def _format_curve(self, curve: dict[str, Any]) -> str:
        labels = (("0-1", "0-1费"), ("2", "2费"), ("3", "3费"), ("4", "4费"),
                  ("5", "5费"), ("6", "6费"), ("7+", "7+费"))
        parts = [f"{label}:{int(curve.get(key, 0))}" for key, label in labels if int(curve.get(key, 0))]
        return " / ".join(parts) or "未知"

    def _format_code_context(self, code: str) -> list[str]:
        try:
            decoded = decode_deckstring(code)
        except DeckCodeError:
            return []
        summary = summarize_deck(decoded, self._card_map())
        key_cards = "、".join(
            f"{item['count']}x{item['name']}" for item in summary["key_cards"] if item.get("name")
        ) or "本地卡牌库未命中（仅能按代码计数）"
        lines = [
            "【用户提供的炉石卡组代码｜本地解析，不是天梯胜率】",
            f"模式：{'标准' if summary['format'] == 'standard' else '狂野'}；"
            f"职业：{summary['class_zh']}；牌数：{summary['total']}。",
            f"费用曲线：{self._format_curve(summary['curve'])}。",
            f"关键牌/高频牌：{key_cards}。",
            "点评时只给1-2句、40-60字，绝对不超过80字：一句强度/定位，一句关键打法或注意点；"
            "不要贴整副牌表，也不要在没有胜率数据时编造百分比。",
        ]
        return ["\n".join(lines)]

    def _format_deck(self, deck: dict[str, Any], *, include_code: bool = True, detailed: bool = True) -> str:
        fields = [
            f"来源：{deck.get('source') or '旅法师营地'}《{deck.get('title') or '未命名'}》"
            f"{('（' + str(deck.get('published')) + '）') if deck.get('published') else ''}",
            f"职业/流派：{deck.get('class_zh') or '未知'} / {deck.get('archetype') or '未标注'}",
        ]
        if detailed and deck.get("strength_note"):
            fields.append(f"强度：{deck['strength_note']}")
        if deck.get("curve_profile"):
            fields.append(f"曲线定位：{deck['curve_profile']}")
        key_cards = deck.get("key_cards")
        if detailed and isinstance(key_cards, list) and key_cards:
            names = "、".join(
                f"{item.get('count', 1)}x{item.get('name')}" if isinstance(item, dict) else str(item)
                for item in key_cards[:8]
            )
            fields.append(f"关键牌：{names}")
        curve = deck.get("curve")
        if detailed and isinstance(curve, dict):
            fields.append(f"曲线：{self._format_curve(curve)}")
        if include_code and deck.get("deck_code"):
            fields.append(f"卡组代码：{deck['deck_code']}")
        if detailed and deck.get("source_url"):
            fields.append(f"来源链接：{deck['source_url']}")
        return "\n".join(fields)

    def _format_recommendation(self, index: int, deck: dict[str, Any]) -> str:
        return (
            f"{index}. {deck.get('name') or deck.get('archetype') or '未命名'}"
            f"（{deck.get('class_zh') or '未知'}，{deck.get('curve_profile') or '曲线未知'}）"
        )

    def _ordinal_index(self, text: str) -> int | None:
        raw = str(text or "")
        if re.search(r"最后(一)?套|末套", raw):
            return -1
        match = re.search(r"第\s*([一二三四五六七八九十两\d]+)\s*(?:套|个|副)", raw)
        if match:
            token = match.group(1)
            values = {
                "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
                "两": 2,
            }
            try:
                number = int(token)
            except ValueError:
                number = values.get(token, 0)
            return max(0, number - 1) if number else None
        if re.search(r"这(一)?套|那(一)?套|上一套|刚才那套|前面那套", raw):
            return 0
        return None

    def _selected_followup(self, text: str, scope_id: int) -> dict[str, Any] | None:
        decks = self._last_by_scope.get(int(scope_id)) or []
        if not decks:
            return None
        index = self._ordinal_index(text)
        if index is None:
            return None
        if index < 0:
            index = len(decks) - 1
        if 0 <= index < len(decks):
            return dict(decks[index])
        return None

    def followup_code(self, text: str, scope_id: int) -> dict[str, Any] | None:
        """Resolve “第一套/给我代码” to a deck without asking the model."""
        decks = self._last_by_scope.get(int(scope_id)) or []
        if not decks:
            return None
        raw = str(text or "")
        index = self._ordinal_index(raw)
        wants_code = any(term in raw for term in ("代码", "复制", "发我", "给我", "贴一下", "要一下"))
        has_review = any(term in raw for term in REVIEW_TERMS)
        if index is None:
            if wants_code and len(decks) == 1:
                index = 0
            elif wants_code and re.search(r"这套|那套|上一套", raw):
                index = 0
            else:
                return None
        # “第一套” alone, including “？喂 @bot 第一套”, means send the code.
        # “第一套怎么样/强度” is a review, so leave it to the model.
        if has_review and not wants_code:
            return None
        if not wants_code and index is None:
            return None
        if index < 0:
            index = len(decks) - 1
        if 0 <= index < len(decks):
            return dict(decks[index])
        return None

    def short_review(self, text: str, scope_id: int = 0) -> str:
        """Deterministic fallback when the model still writes too much."""
        selected = self._selected_followup(text, scope_id)
        if selected is not None:
            return self._one_line_review(selected)
        decks = self._last_by_scope.get(int(scope_id)) or []
        if decks:
            names = "、".join(
                str(deck.get("name") or deck.get("archetype") or "未命名")[:12]
                for deck in decks[:2]
            )
            return f"今天可看：{names}。想看哪套？"
        return ""

    @staticmethod
    def _one_line_review(deck: dict[str, Any]) -> str:
        name = str(deck.get("name") or deck.get("archetype") or "这套")[:20]
        profile = str(deck.get("curve_profile") or "")
        if "快攻" in profile or "节奏" in profile:
            return f"{name}偏快攻，抢节奏，怕解场。"
        if "控制" in profile or "后期" in profile:
            return f"{name}偏控制，吃资源，怕被抢死。"
        return f"{name}偏中速，靠节奏和关键牌。"

    def context_for(self, text: str, scope_id: int = 0) -> list[str]:
        """Return bounded RAG-like context blocks for a deck-related message."""
        if not self.enabled:
            return []
        code = deck_code_in_text(text)
        if code:
            return self._format_code_context(code)
        selected = self._selected_followup(text, scope_id)
        if selected is not None:
            blocks = [
                "【用户选中的上一轮卡组】",
                self._format_deck(selected, include_code=False, detailed=True),
                "如果用户在问代码，代码由程序单独发送；如果是在问点评，只给1-2句、40-60字，绝对不超过80字，"
                "不要输出卡组代码、不要重复整套牌表。",
            ]
            return blocks
        if not self.is_deck_query(text):
            return []
        decks = self.find_decks(text)
        if not decks:
            return [
                "【炉石卡组资料】本地卡组库暂无命中记录。不要编造具体胜率或排名；"
                "可以给通用的构筑/曲线建议，并提示用户提供卡组代码或最新环境数据。"
            ]
        if scope_id is not None:
            self._last_by_scope[int(scope_id)] = [dict(deck) for deck in decks]
        blocks = ["【炉石卡组资料｜来自本地 RAG，非官方】"]
        for index, deck in enumerate(decks, 1):
            blocks.append(self._format_recommendation(index, deck))
        blocks.append(
            "推荐要求：最多列3套，每套只写“名称（职业，曲线）”；1-2句、40-60字、绝对不超过80字；"
            "不要输出完整卡组代码；用户要具体某套代码时由程序发送。"
            "资料里的胜率只代表来源文章，没有数据时不要编造。"
        )
        return blocks

    @property
    def deck_count(self) -> int:
        self._load_decks()
        return len(self._decks)
