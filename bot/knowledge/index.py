"""Persistent, dependency-free RAG index for local JSON and Markdown knowledge."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from knowledge.retriever import _json_records, _markdown_sections, _query_tokens


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE TABLE IF NOT EXISTS terms (
    term TEXT NOT NULL,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    frequency INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(term, document_id)
);
CREATE INDEX IF NOT EXISTS idx_terms_term ON terms(term);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class KnowledgeIndex:
    """Build and query a persistent lexical index with Chinese bigram support.

    The index is intentionally separate from the chat-memory database. It can be
    rebuilt at any time without touching source knowledge files or user messages.
    """

    def __init__(
        self,
        db_path: str | Path,
        root: str | Path,
        *,
        chunk_chars: int = 1800,
        min_score: int = 6,
    ) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.chunk_chars = max(300, int(chunk_chars))
        self.min_score = max(1, int(min_score))

    def _signature(self) -> str:
        entries: list[tuple[str, int, int]] = []
        if self.root.exists():
            for path in sorted(self.root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".json", ".md"}:
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    entries.append(
                        (path.relative_to(self.root).as_posix(), stat.st_mtime_ns, stat.st_size)
                    )
        payload = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _open(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def is_fresh(self) -> bool:
        if not self.db_path.exists():
            return False
        try:
            with self._open() as connection:
                rows = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
            return (
                rows.get("root_signature") == self._signature()
                and rows.get("chunk_chars") == str(self.chunk_chars)
            )
        except sqlite3.Error:
            return False

    def _records(self, path: Path) -> list[str]:
        try:
            if path.suffix.lower() == ".json":
                return [str(item).strip() for item in _json_records(json.loads(path.read_text(encoding="utf-8")))]
            return [str(item).strip() for item in _markdown_sections(path.read_text(encoding="utf-8"))]
        except (OSError, UnicodeError, ValueError, TypeError):
            return []

    def build(self) -> dict[str, Any]:
        files = 0
        documents = 0
        terms = 0
        signature = self._signature()
        with self._open() as connection:
            connection.executescript(SCHEMA)
            connection.execute("DELETE FROM terms")
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM metadata")
            if self.root.exists():
                for path in sorted(self.root.rglob("*")):
                    if not path.is_file() or path.suffix.lower() not in {".json", ".md"}:
                        continue
                    records = self._records(path)
                    if not records:
                        continue
                    files += 1
                    source = path.relative_to(self.root).as_posix()
                    chunk_index = 0
                    for record in records:
                        if not record:
                            continue
                        for start in range(0, len(record), self.chunk_chars):
                            chunk = record[start : start + self.chunk_chars].strip()
                            if not chunk:
                                continue
                            digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                            cursor = connection.execute(
                                "INSERT INTO documents(source,chunk_index,content,content_hash) VALUES (?,?,?,?)",
                                (source, chunk_index, chunk, digest),
                            )
                            document_id = int(cursor.lastrowid)
                            chunk_index += 1
                            counts = Counter(_query_tokens(chunk))
                            connection.executemany(
                                "INSERT INTO terms(term,document_id,frequency) VALUES (?,?,?)",
                                [(term, document_id, count) for term, count in counts.items()],
                            )
                            documents += 1
                            terms += len(counts)
            metadata = {
                "root": str(self.root.resolve()),
                "root_signature": signature,
                "chunk_chars": str(self.chunk_chars),
                "built_at": str(time.time()),
                "files": str(files),
                "documents": str(documents),
                "terms": str(terms),
            }
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)", metadata.items()
            )
            connection.commit()
        return {"root": str(self.root), "files": files, "documents": documents, "terms": terms}

    def stats(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"db_path": str(self.db_path), "files": 0, "documents": 0, "terms": 0, "fresh": False}
        try:
            with self._open() as connection:
                metadata = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
            return {
                "db_path": str(self.db_path),
                "files": int(metadata.get("files", 0)),
                "documents": int(metadata.get("documents", 0)),
                "terms": int(metadata.get("terms", 0)),
                "fresh": self.is_fresh(),
                "built_at": metadata.get("built_at", ""),
            }
        except (sqlite3.Error, ValueError):
            return {"db_path": str(self.db_path), "files": 0, "documents": 0, "terms": 0, "fresh": False}

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 4,
        max_chars: int = 2600,
        min_score: int | None = None,
    ) -> list[str]:
        if not self.is_fresh():
            return []
        query_text = " ".join(str(query or "").split())[:1000]
        tokens = _query_tokens(query_text)
        if not tokens:
            return []
        threshold = self.min_score if min_score is None else max(1, int(min_score))
        placeholders = ",".join("?" for _ in tokens)
        sql = (
            "SELECT d.source,d.content,COUNT(*) AS matched "
            "FROM terms t JOIN documents d ON d.id=t.document_id "
            f"WHERE t.term IN ({placeholders}) GROUP BY d.id"
        )
        try:
            with self._open() as connection:
                rows = connection.execute(sql, tuple(tokens)).fetchall()
        except sqlite3.Error:
            return []
        query_lower = query_text.casefold()
        ranked: list[tuple[int, str, str]] = []
        for source, content, matched in rows:
            score = int(matched) * 3
            if query_lower and query_lower in str(content).casefold():
                score += 8
            if score >= threshold:
                ranked.append((score, str(source), str(content)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        result: list[str] = []
        used = 0
        for _score, source, content in ranked[: max(0, int(limit))]:
            line = f"来源：{source}\n{content}"
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
