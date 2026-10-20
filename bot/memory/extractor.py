"""Extract explicit memory candidates without making automatic factual claims."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryCandidate:
    scope: str  # "user" or "group"
    content: str
    reason: str


_USER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|[，,。！!；;\s])我喜欢(?:吃|玩|看|用)?(.{1,80})$"), "explicit preference"),
    (re.compile(r"(?:^|[，,。！!；;\s])我爱(.{1,80})$"), "explicit preference"),
    (re.compile(r"(?:^|[，,。！!；;\s])我叫(.{1,40})$"), "self-introduction"),
    (re.compile(r"(?:^|[，,。！!；;\s])我是(.{1,60})$"), "self-introduction"),
    (re.compile(r"(?:^|[，,。！!；;\s])我的(?:职业|工作|身份)是(.{1,60})$"), "self-description"),
)
_GROUP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:^|[，,。！!；;\s])本群(?:里)?(?:喜欢|常聊|主要聊|主题是)(.{1,100})$"), "explicit group topic"),
    (re.compile(r"(?:^|[，,。！!；;\s])群规(?:是|：|:)(.{1,100})$"), "explicit group rule"),
    (re.compile(r"(?:^|[，,。！!；;\s])我们群(?:里)?(?:约定|一般)(.{1,100})$"), "explicit group convention"),
)


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ，,。！？!；;:：")
    return value[:limit].strip()


class MemoryExtractor:
    """Conservative extractor intended to create review candidates only.

    It deliberately recognizes explicit first-person/group declarations and does not
    infer traits from sentiment, jokes, usernames, or a single casual mention.
    """

    def __init__(self, config: dict) -> None:
        settings = config.get("memory", {})
        self.enabled = bool(settings.get("candidate_extraction_enabled", True))
        self.max_candidates = max(0, int(settings.get("max_candidates_per_message", 2)))

    def extract(self, text: str, *, user_id: int) -> list[MemoryCandidate]:
        if not self.enabled or not text.strip() or self.max_candidates == 0:
            return []
        candidates: list[MemoryCandidate] = []
        for pattern, reason in _USER_PATTERNS:
            match = pattern.search(text.strip())
            if match:
                value = _clean(match.group(1), 120)
                if value:
                    candidates.append(
                        MemoryCandidate("user", f"用户{user_id}{self._label(reason)}：{value}", reason)
                    )
                    break
        for pattern, reason in _GROUP_PATTERNS:
            match = pattern.search(text.strip())
            if match:
                value = _clean(match.group(1), 150)
                if value:
                    candidates.append(MemoryCandidate("group", f"群聊候选：{value}", reason))
                    break
        return candidates[: self.max_candidates]

    @staticmethod
    def _label(reason: str) -> str:
        if reason == "self-introduction":
            return "自述"
        if reason == "self-description":
            return "身份自述"
        return "偏好自述"
