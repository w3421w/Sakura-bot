"""Dependency-free local JSON/Markdown retrieval for the QWbot RAG layer."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}|\d{3,}")


@dataclass(frozen=True)
class KnowledgeHit:
    score: int
    source: str
    text: str


def _flatten(value: Any, prefix: str = "") -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            label = f"{prefix}{key}" if prefix else str(key)
            parts.append(_flatten(item, label + ": "))
        return "；".join(parts)
    if isinstance(value, list):
        return "；".join(_flatten(item, prefix) for item in value)
    return prefix + str(value)


def _query_tokens(query: str) -> set[str]:
    tokens: set[str] = set()
    for token in TOKEN_RE.findall(query):
        folded = token.casefold()
        tokens.add(folded)
        # Chinese queries have no spaces; bigrams make “小甲喜欢什么” match
        # records containing “小甲喜欢简短回答” without a third-party tokenizer.
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            tokens.update(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _json_records(payload: Any) -> Iterable[str]:
    """Yield bounded semantic records instead of flattening one huge JSON file."""
    if isinstance(payload, list):
        for item in payload:
            yield _flatten(item).strip()
        return
    if isinstance(payload, dict):
        list_fields = [
            (str(key), value)
            for key, value in payload.items()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        if list_fields:
            for key, values in list_fields:
                for index, item in enumerate(values):
                    yield _flatten(item, f"{key}[{index}] ").strip()
            return
    yield _flatten(payload).strip()


def _markdown_sections(text: str) -> Iterable[str]:
    heading = ""
    buffer: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            if buffer:
                yield (heading + "\n" + "\n".join(buffer)).strip()
                buffer = []
            heading = line.strip()
        elif line.strip():
            buffer.append(line.rstrip())
        elif buffer:
            yield (heading + "\n" + "\n".join(buffer)).strip()
            buffer = []
    if buffer:
        yield (heading + "\n" + "\n".join(buffer)).strip()


class KnowledgeBase:
    """Load local facts and return bounded keyword-matched snippets.

    Files are indexed in memory. A lightweight signature check allows operators to
    edit JSON/Markdown while the bot is running; the next query refreshes the index.
    Retrieved text is reference data, never executable instructions.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        chunk_chars: int = 1800,
        min_score: int = 6,
    ) -> None:
        self.root = Path(root)
        self.chunk_chars = max(300, int(chunk_chars))
        self.min_score = max(1, int(min_score))
        self._documents: list[tuple[str, str]] = []
        self._signature: tuple[tuple[str, int, int], ...] = ()
        self._load()

    def _file_signature(self) -> tuple[tuple[str, int, int], ...]:
        if not self.root.exists():
            return ()
        items: list[tuple[str, int, int]] = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".json", ".md"}:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                items.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(items)

    def _load(self) -> None:
        documents: list[tuple[str, str]] = []
        if self.root.exists():
            for path in sorted(self.root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".json", ".md"}:
                    continue
                try:
                    if path.suffix.lower() == ".json":
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        records = _json_records(payload)
                    else:
                        records = _markdown_sections(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError):
                    continue
                relative = str(path.relative_to(self.root))
                for index, record in enumerate(records):
                    record = record.strip()
                    if not record:
                        continue
                    for start in range(0, len(record), self.chunk_chars):
                        chunk = record[start : start + self.chunk_chars].strip()
                        if chunk:
                            suffix = f"#{index + 1}" if len(record) > self.chunk_chars else ""
                            documents.append((relative + suffix, chunk))
        self._documents = documents
        self._signature = self._file_signature()

    def maybe_refresh(self) -> bool:
        signature = self._file_signature()
        if signature == self._signature:
            return False
        self._load()
        return True

    def stats(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": len({source.split("#", 1)[0] for source, _ in self._documents}),
            "documents": len(self._documents),
        }

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 4,
        max_chars: int = 2600,
        min_score: int | None = None,
    ) -> list[str]:
        self.maybe_refresh()
        q = (query or "").strip()[:1000]
        if not q or not self._documents:
            return []
        query_lower = q.casefold()
        tokens = _query_tokens(q)
        threshold = self.min_score if min_score is None else max(1, int(min_score))
        hits: list[KnowledgeHit] = []
        for source, text in self._documents:
            lower = text.casefold()
            score = sum(3 if token in lower else 0 for token in tokens)
            if query_lower and query_lower in lower:
                score += 8
            if score >= threshold:
                hits.append(KnowledgeHit(score, source, text))
        hits.sort(key=lambda hit: (-hit.score, hit.source))
        result: list[str] = []
        used = 0
        for hit in hits[: max(0, int(limit))]:
            line = f"来源：{hit.source}\n{hit.text}"
            if used + len(line) > max_chars:
                remaining = max_chars - used
                if remaining <= 80:
                    break
                line = line[:remaining].rstrip()
            result.append(line)
            used += len(line) + 2
            if used >= max_chars:
                break
        return result
