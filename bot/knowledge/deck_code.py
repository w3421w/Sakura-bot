"""Hearthstone deckstring decoding and small local summaries.

The decoder is dependency-free and only needs the standard library.  It is used
both by the daily iyingdi collector and by the live deck-review context builder.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


class DeckCodeError(ValueError):
    """Raised when a string is not a valid Hearthstone deckstring."""


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise DeckCodeError("truncated deckstring")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise DeckCodeError("deckstring varint too large")


def decode_deckstring(code: str) -> dict[str, Any]:
    """Decode a Hearthstone deck code into hero and card DBF ids."""
    compact = "".join(str(code).split())
    if not compact:
        raise DeckCodeError("empty deck code")
    if len(compact) < 20:
        raise DeckCodeError("deck code too short")
    padded = compact + "=" * ((4 - len(compact) % 4) % 4)
    try:
        data = base64.b64decode(padded, validate=False)
    except (ValueError, TypeError) as exc:
        raise DeckCodeError("invalid base64 deck code") from exc
    if not data:
        raise DeckCodeError("empty decoded deckstring")

    offset = 0
    if data[offset] != 0:
        raise DeckCodeError("invalid reserved byte")
    offset += 1
    version, offset = _read_varint(data, offset)
    if version != 1:
        raise DeckCodeError(f"unsupported deckstring version: {version}")
    fmt, offset = _read_varint(data, offset)
    if fmt not in (1, 2, 3, 4):
        raise DeckCodeError(f"unsupported deck format: {fmt}")

    hero_count, offset = _read_varint(data, offset)
    if hero_count < 1 or hero_count > 3:
        raise DeckCodeError("invalid hero count")
    heroes: list[int] = []
    for _ in range(hero_count):
        hero, offset = _read_varint(data, offset)
        heroes.append(hero)

    cards: list[dict[str, int]] = []

    def read_section(copies: int) -> None:
        nonlocal offset
        count, offset = _read_varint(data, offset)
        if count < 0 or count > 60:
            raise DeckCodeError("invalid card section length")
        for _ in range(count):
            dbf_id, offset = _read_varint(data, offset)
            cards.append({"dbf_id": dbf_id, "count": copies})

    read_section(1)
    read_section(2)

    multi_count, offset = _read_varint(data, offset)
    if multi_count < 0 or multi_count > 60:
        raise DeckCodeError("invalid multi-card section length")
    for _ in range(multi_count):
        dbf_id, offset = _read_varint(data, offset)
        count, offset = _read_varint(data, offset)
        if count < 1 or count > 30:
            raise DeckCodeError("invalid card count")
        cards.append({"dbf_id": dbf_id, "count": count})

    total = sum(item["count"] for item in cards)
    if total < 1 or total > 60:
        raise DeckCodeError("invalid total card count")
    return {
        "format": "standard" if fmt in (1, 3) else "wild",
        "format_id": fmt,
        "heroes": heroes,
        "cards": cards,
        "total": total,
    }


def load_card_map(path: str | Path) -> dict[int, dict[str, Any]]:
    """Load a compact dbf-id map or a raw HearthstoneJSON card list."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("cards"), dict):
        result: dict[int, dict[str, Any]] = {}
        for key, value in payload["cards"].items():
            try:
                result[int(key)] = value if isinstance(value, dict) else {"name": str(value)}
            except (TypeError, ValueError):
                continue
        return result
    if isinstance(payload, list):
        result = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                result[int(item["dbfId"])] = item
            except (KeyError, TypeError, ValueError):
                continue
        return result
    return {}


def compact_card(card: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields needed for a local deck review."""
    return {
        "name": str(card.get("name") or ""),
        "cost": card.get("cost"),
        "type": str(card.get("type") or ""),
        "class": str(card.get("cardClass") or ""),
        "rarity": str(card.get("rarity") or ""),
        "set": str(card.get("set") or ""),
        "text": str(card.get("text") or "")[:300],
    }


CLASS_NAMES = {
    "DEATHKNIGHT": "死亡骑士",
    "DEMONHUNTER": "恶魔猎手",
    "DRUID": "德鲁伊",
    "HUNTER": "猎人",
    "MAGE": "法师",
    "PALADIN": "圣骑士",
    "PRIEST": "牧师",
    "ROGUE": "潜行者",
    "SHAMAN": "萨满",
    "WARLOCK": "术士",
    "WARRIOR": "战士",
    "NEUTRAL": "中立",
}


def summarize_deck(
    decoded: dict[str, Any],
    card_map: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, compact summary from a decoded deckstring."""
    cards = decoded.get("cards") or []
    by_id = card_map or {}
    curve: dict[str, int] = {"0-1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7+": 0}
    types: dict[str, int] = {}
    resolved: list[dict[str, Any]] = []
    unknown = 0
    for item in cards:
        dbf_id = int(item.get("dbf_id") or 0)
        count = int(item.get("count") or 0)
        card = by_id.get(dbf_id) or {}
        cost = card.get("cost")
        if isinstance(cost, int):
            key = "0-1" if cost <= 1 else "7+" if cost >= 7 else str(cost)
            curve[key] = curve.get(key, 0) + count
        else:
            unknown += count
        card_type = str(card.get("type") or "")
        if card_type:
            types[card_type] = types.get(card_type, 0) + count
        resolved.append(
            {
                "dbf_id": dbf_id,
                "count": count,
                "name": str(card.get("name") or ""),
                "cost": cost,
                "type": card_type,
                "rarity": str(card.get("rarity") or ""),
                "text": str(card.get("text") or ""),
            }
        )

    hero_class = ""
    for hero_id in decoded.get("heroes") or []:
        hero = by_id.get(int(hero_id)) or {}
        hero_class = str(hero.get("cardClass") or hero_class)
    if not hero_class:
        for item in resolved:
            card = by_id.get(item["dbf_id"]) or {}
            if card.get("cardClass") and card.get("cardClass") != "NEUTRAL":
                hero_class = str(card["cardClass"])
                break

    key_cards = sorted(
        (item for item in resolved if item["name"]),
        key=lambda item: (
            0 if str(item["rarity"]).upper() == "LEGENDARY" else 1,
            -(int(item["cost"]) if isinstance(item["cost"], int) else 0),
            -int(item["count"]),
            item["name"],
        ),
    )[:8]
    return {
        "format": decoded.get("format"),
        "class": hero_class,
        "class_zh": CLASS_NAMES.get(hero_class, hero_class or "未知"),
        "total": decoded.get("total", 0),
        "curve": curve,
        "types": types,
        "unknown_cards": unknown,
        "key_cards": key_cards,
    }


def deck_code_in_text(text: str) -> str:
    """Return the first plausible Hearthstone deck code in a message."""
    import re

    for match in re.finditer(r"(?<![A-Za-z0-9+/=])(AAE[A-Za-z0-9+/]{20,}={0,2})(?![A-Za-z0-9+/=])", text):
        candidate = match.group(1)
        try:
            decode_deckstring(candidate)
        except DeckCodeError:
            continue
        return candidate
    return ""
