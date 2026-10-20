"""Reply shaping helpers shared by normal and proactive messages."""

from __future__ import annotations

import re


def _strip_chat_punctuation(text: str) -> str:
    """Keep casual chat bubbles clean by removing comma/period marks."""
    return re.sub(r"[，,。\.]+", "", str(text).strip()).strip()


def split_reply(text: str, *, max_parts: int = 3) -> list[str]:
    """Split a natural-language reply into a few chat-sized messages.

    Newlines and sentence-ending punctuation are preferred boundaries. Short
    replies stay intact, and excessive fragmentation is folded back into the
    final part so one answer cannot become a message burst.
    """
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    max_parts = max(1, int(max_parts))
    paragraphs = [part.strip() for part in re.split(r"\n+", normalized) if part.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        # Keep punctuation with the sentence that precedes it.
        comma_count = paragraph.count("，") + paragraph.count(",")
        separator = (
            r"(?<=[。！？!?；;，,])\s*"
            if len(paragraph) >= 12 and comma_count >= 1
            else r"(?<=[。！？!?；;])\s*"
        )
        sentences = [
            part.strip()
            for part in re.split(separator, paragraph)
            if part.strip()
        ]
        pieces.extend(sentences or [paragraph])
    if len(pieces) > max_parts:
        pieces = pieces[: max_parts - 1] + [" ".join(pieces[max_parts - 1 :])]
    # Keep punctuation in a long single factual answer, but make casual
    # short replies and multi-bubble output look like natural chat bubbles.
    should_clean = len(pieces) > 1 or len(normalized) <= 12
    if not should_clean:
        return pieces
    cleaned = [_strip_chat_punctuation(piece) for piece in pieces]
    return [piece for piece in cleaned if piece]
