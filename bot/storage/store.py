"""Thread-safe SQLite store adapted from the legacy QWbot Store."""

from __future__ import annotations

import sqlite3
import threading
import time
import json
import re
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, db_path: str | Path, retention_days: int = 14) -> None:
        self._in_memory = str(db_path) == ":memory:"
        self.db_path = Path(":memory:") if self._in_memory else Path(db_path)
        if not self._in_memory:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = max(1, int(retention_days))
        self._lock = threading.RLock()
        target = ":memory:" if self._in_memory else self.db_path
        self.db = sqlite3.connect(target, check_same_thread=False, timeout=15)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=15000")
        self._initialize()

    def _initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._lock:
            self.db.executescript(schema)
            columns = {
                str(row[1])
                for row in self.db.execute("PRAGMA table_info(messages)").fetchall()
            }
            for column, definition in {
                "message": "TEXT",
                "timestamp": "REAL",
                "message_id": "TEXT",
                "sender_info": "TEXT",
            }.items():
                if column not in columns:
                    self.db.execute(f"ALTER TABLE messages ADD COLUMN {column} {definition}")
            self.db.execute("UPDATE messages SET message=text WHERE message IS NULL")
            self.db.execute("UPDATE messages SET timestamp=ts WHERE timestamp IS NULL")
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_group_message_id "
                "ON messages(group_id, message_id)"
            )
            for table in ("memory", "user_memory"):
                columns = {
                    str(row[1]) for row in self.db.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for column, definition in {
                    "source_message_id": "TEXT",
                    "source_user_id": "INTEGER",
                    "source_kind": "TEXT NOT NULL DEFAULT 'manual'",
                }.items():
                    if column not in columns:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            persona_columns = {
                str(row[1])
                for row in self.db.execute("PRAGMA table_info(persona_state)").fetchall()
            }
            if persona_columns and "switch_count" not in persona_columns:
                self.db.execute(
                    "ALTER TABLE persona_state ADD COLUMN switch_count INTEGER NOT NULL DEFAULT 0"
                )
            self.db.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '5')"
            )
            self.db.commit()

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def has_consent(self, group_id: int, user_id: int) -> bool:
        with self._lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM consent WHERE group_id=? AND user_id=?",
                    (group_id, user_id),
                ).fetchone()
                is not None
                and self.db.execute(
                    "SELECT 1 FROM opt_out WHERE group_id=? AND user_id=?",
                    (group_id, user_id),
                ).fetchone()
                is None
            )

    def has_opted_out(self, group_id: int, user_id: int) -> bool:
        """Return whether a user explicitly disabled storage in this scope."""
        with self._lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM opt_out WHERE group_id=? AND user_id=?",
                    (group_id, user_id),
                ).fetchone()
                is not None
            )

    def agree(self, group_id: int, user_id: int) -> None:
        with self._lock:
            self.db.execute(
                "DELETE FROM opt_out WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO consent(group_id,user_id,agreed_at) VALUES (?,?,?)",
                (group_id, user_id, time.time()),
            )
            self.db.commit()

    def forget(self, group_id: int, user_id: int) -> None:
        with self._lock:
            self.db.execute(
                "DELETE FROM consent WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO opt_out(group_id,user_id,opted_out_at) VALUES (?,?,?)",
                (group_id, user_id, time.time()),
            )
            self.db.execute(
                "DELETE FROM messages WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.execute(
                "DELETE FROM user_profiles WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.execute(
                "DELETE FROM user_memory WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.commit()

    def add_message(
        self,
        group_id: int,
        user_id: int,
        text: str,
        is_bot: bool = False,
        *,
        message_id: int | str | None = None,
        sender_info: dict[str, Any] | str | None = None,
    ) -> None:
        sender_json = (
            sender_info
            if isinstance(sender_info, str)
            else json.dumps(sender_info or {}, ensure_ascii=False, sort_keys=True)
        )
        now = time.time()
        with self._lock:
            self.db.execute(
                "INSERT INTO messages(group_id,user_id,text,ts,is_bot,message,timestamp,message_id,sender_info) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    group_id,
                    user_id,
                    text[:900],
                    now,
                    int(is_bot),
                    text[:900],
                    now,
                    None if message_id is None else str(message_id),
                    sender_json,
                ),
            )
            self.db.commit()

    def claim_event(
        self,
        event_key: str,
        *,
        event_type: str = "message",
        scope_id: str = "",
        message_id: int | str | None = None,
        ttl_seconds: int = 7 * 86400,
    ) -> bool:
        """Atomically claim an event so reconnect/replay cannot process it twice.

        A durable claim survives a process restart. Expired claims are removed
        opportunistically, keeping the table bounded without a separate worker.
        """
        key = str(event_key).strip()
        if not key:
            return False
        now = time.time()
        expires = now + max(60, int(ttl_seconds))
        with self._lock:
            self.db.execute("DELETE FROM event_receipts WHERE expires_at<?", (now,))
            try:
                self.db.execute(
                    "INSERT INTO event_receipts(event_key,event_type,scope_id,message_id,received_at,expires_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (key, str(event_type), str(scope_id), None if message_id is None else str(message_id), now, expires),
                )
            except sqlite3.IntegrityError:
                return False
            self.db.commit()
            return True

    def claim_outbound(
        self,
        idempotency_key: str,
        *,
        scope_id: str,
        message: str,
        retry_after_seconds: int = 30,
    ) -> bool:
        """Reserve a send operation; return False for a known sent/in-flight send."""
        key = str(idempotency_key).strip()
        if not key:
            return False
        now = time.time()
        with self._lock:
            row = self.db.execute(
                "SELECT status,updated_at FROM outbound_receipts WHERE idempotency_key=?",
                (key,),
            ).fetchone()
            if row is not None:
                status, updated_at = str(row[0]), float(row[1])
                if status == "sent":
                    return False
                if status == "pending" and now - updated_at < max(1, int(retry_after_seconds)):
                    return False
                self.db.execute(
                    "UPDATE outbound_receipts SET scope_id=?,message=?,status='pending',updated_at=?,error='' "
                    "WHERE idempotency_key=?",
                    (str(scope_id), str(message)[:900], now, key),
                )
            else:
                self.db.execute(
                    "INSERT INTO outbound_receipts(idempotency_key,scope_id,message,status,created_at,updated_at,error) "
                    "VALUES (?,?,?,'pending',?,?, '')",
                    (key, str(scope_id), str(message)[:900], now, now),
                )
            self.db.commit()
            return True

    def finish_outbound(self, idempotency_key: str, *, status: str, error: str = "") -> None:
        if status not in {"sent", "failed", "unknown"}:
            raise ValueError("invalid outbound status")
        with self._lock:
            self.db.execute(
                "UPDATE outbound_receipts SET status=?,updated_at=?,error=? WHERE idempotency_key=?",
                (status, time.time(), str(error)[:500], str(idempotency_key)),
            )
            self.db.commit()

    def outbound_status(self, idempotency_key: str) -> str | None:
        with self._lock:
            row = self.db.execute(
                "SELECT status FROM outbound_receipts WHERE idempotency_key=?",
                (str(idempotency_key),),
            ).fetchone()
        return None if row is None else str(row[0])

    def recent(
        self,
        group_id: int,
        limit: int = 20,
        *,
        exclude_message_id: int | str | None = None,
    ) -> list[tuple[int, str, int]]:
        with self._lock:
            query = (
                "SELECT user_id,COALESCE(message,text),is_bot FROM messages "
                "WHERE group_id=?"
            )
            params: list[Any] = [group_id]
            if exclude_message_id is not None:
                query += " AND (message_id IS NULL OR message_id<>?)"
                params.append(str(exclude_message_id))
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = self.db.execute(query, params).fetchall()
        return list(reversed(rows))

    def recent_bot_texts(self, group_id: int, limit: int = 3) -> list[str]:
        """Return the latest bot replies for duplicate detection (newest first)."""
        with self._lock:
            rows = self.db.execute(
                "SELECT COALESCE(message,text) FROM messages "
                "WHERE group_id=? AND is_bot=1 AND COALESCE(message,text)<>'' "
                "ORDER BY id DESC LIMIT ?",
                (group_id, max(1, int(limit))),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def recent_detailed(
        self,
        group_id: int,
        limit: int = 20,
        *,
        exclude_message_id: int | str | None = None,
    ) -> list[tuple[int, str, int, dict[str, Any]]]:
        """Return recent messages with the sender metadata captured by OneBot."""
        with self._lock:
            query = (
                "SELECT user_id,COALESCE(message,text),is_bot,sender_info "
                "FROM messages WHERE group_id=?"
            )
            params: list[Any] = [group_id]
            if exclude_message_id is not None:
                query += " AND (message_id IS NULL OR message_id<>?)"
                params.append(str(exclude_message_id))
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = self.db.execute(query, params).fetchall()
        detailed: list[tuple[int, str, int, dict[str, Any]]] = []
        for user_id, text, is_bot, sender_info in reversed(rows):
            metadata: dict[str, Any] = {}
            if sender_info:
                try:
                    decoded = json.loads(str(sender_info))
                    if isinstance(decoded, dict):
                        metadata = decoded
                except (TypeError, ValueError, json.JSONDecodeError):
                    metadata = {}
            detailed.append((int(user_id), str(text), int(is_bot), metadata))
        return detailed

    @staticmethod
    def _as_group_address(name: Any) -> str:
        """Normalise a member label to “short name + 前辈” for group prompts."""
        text = str(name or "").strip()
        if not text:
            return "前辈"
        text = re.split(r"[/、,，]", text)[0].strip()
        if not text:
            return "前辈"
        if text.endswith("前辈"):
            return text
        for suffix in (
            "老师", "学长", "学姐", "师兄", "师姐", "先生", "小姐", "老板",
            "哥", "姐", "叔", "姨",
        ):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                break
        return f"{text}前辈" if text else "前辈"

    def user_label(
        self,
        group_id: int,
        user_id: int,
        sender_info: dict[str, Any] | None = None,
    ) -> str:
        """Resolve a stable, human-readable label while retaining the QQ id."""
        if int(user_id) == 0:
            return "pop子"
        profile = self.get_user_profile(group_id, int(user_id)) or {}
        sender = sender_info or {}
        preferred = str(profile.get("preferred_name") or "").strip()
        nickname = str(profile.get("nickname") or "").strip()
        card = str(sender.get("card") or "").strip()
        live_nickname = str(sender.get("nickname") or "").strip()
        name = preferred or card or nickname or live_nickname or f"QQ{user_id}"
        return self._as_group_address(name) if int(group_id) != 0 else name

    def recent_activity(
        self, group_id: int, limit: int = 20
    ) -> list[tuple[int, int, str, int, float, str | None]]:
        """Return recent stored messages with durable row/timestamp metadata.

        Proactive chat only sees messages that already passed the normal privacy
        and consent pipeline; it never reads the OneBot socket directly.
        """
        with self._lock:
            rows = self.db.execute(
                "SELECT id,user_id,COALESCE(message,text),is_bot,ts,message_id "
                "FROM messages WHERE group_id=? ORDER BY id DESC LIMIT ?",
                (group_id, max(1, int(limit))),
            ).fetchall()
        return [
            (int(row[0]), int(row[1]), str(row[2]), int(row[3]), float(row[4]), row[5])
            for row in reversed(rows)
        ]

    def recent_user(
        self,
        group_id: int,
        user_id: int,
        limit: int = 5,
        *,
        exclude_message_id: int | str | None = None,
    ) -> list[str]:
        with self._lock:
            query = (
                "SELECT COALESCE(message,text) FROM messages "
                "WHERE group_id=? AND user_id=? AND is_bot=0"
            )
            params: list[Any] = [group_id, user_id]
            if exclude_message_id is not None:
                query += " AND (message_id IS NULL OR message_id<>?)"
                params.append(str(exclude_message_id))
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = self.db.execute(query, params).fetchall()
        return [str(row[0]) for row in reversed(rows)]

    def recent_user_dialogue(
        self,
        group_id: int,
        user_id: int,
        limit: int = 8,
        *,
        exclude_message_id: int | str | None = None,
    ) -> list[tuple[str, str]]:
        """Return messages belonging to one user's bot conversation.

        User messages are selected by ``user_id``. Bot messages are included
        only when their metadata explicitly records that user as the target,
        so replies to other group members cannot leak into this dialogue.
        Legacy bot rows without ``target_user_id`` are intentionally ignored.
        """
        scan_limit = max(40, max(1, int(limit)) * 10)
        with self._lock:
            query = (
                "SELECT user_id,COALESCE(message,text),is_bot,sender_info "
                "FROM messages WHERE group_id=?"
            )
            params: list[Any] = [group_id]
            if exclude_message_id is not None:
                query += " AND (message_id IS NULL OR message_id<>?)"
                params.append(str(exclude_message_id))
            query += " ORDER BY id DESC LIMIT ?"
            params.append(scan_limit)
            rows = self.db.execute(query, params).fetchall()

        selected: list[tuple[str, str]] = []
        for row_user_id, text, is_bot, sender_info in rows:
            if not int(is_bot) and int(row_user_id) == int(user_id):
                selected.append(("user", str(text)))
            elif int(is_bot):
                metadata: dict[str, Any] = {}
                if sender_info:
                    try:
                        decoded = json.loads(str(sender_info))
                        if isinstance(decoded, dict):
                            metadata = decoded
                    except (TypeError, ValueError, json.JSONDecodeError):
                        metadata = {}
                try:
                    target_user_id = int(metadata.get("target_user_id"))
                except (TypeError, ValueError):
                    target_user_id = -1
                if target_user_id == int(user_id):
                    selected.append(("assistant", str(text)))
            if len(selected) >= max(1, int(limit)):
                break
        return list(reversed(selected))

    def upsert_user_profile(
        self,
        group_id: int,
        user_id: int,
        *,
        nickname: str | None = None,
        preferred_name: str | None = None,
        role: str | None = None,
        notes: str | None = None,
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO user_profiles(group_id,user_id,nickname,preferred_name,role,notes,updated_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET "
                "nickname=COALESCE(excluded.nickname,user_profiles.nickname), "
                "preferred_name=COALESCE(excluded.preferred_name,user_profiles.preferred_name), "
                "role=COALESCE(excluded.role,user_profiles.role), "
                "notes=COALESCE(excluded.notes,user_profiles.notes), updated_at=excluded.updated_at",
                (group_id, user_id, nickname, preferred_name, role, notes, time.time()),
            )
            self.db.commit()

    def get_user_profile(self, group_id: int, user_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self.db.execute(
                "SELECT nickname,preferred_name,role,notes,updated_at FROM user_profiles "
                "WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "nickname": row[0],
            "preferred_name": row[1],
            "role": row[2],
            "notes": row[3],
            "updated_at": float(row[4]),
        }

    def list_user_profiles(self, group_id: int) -> list[dict[str, Any]]:
        """Return all profiles for a group, used to normalise member address."""
        with self._lock:
            rows = self.db.execute(
                "SELECT user_id,nickname,preferred_name,role,notes,updated_at "
                "FROM user_profiles WHERE group_id=? ORDER BY user_id",
                (group_id,),
            ).fetchall()
        return [
            {
                "user_id": int(row[0]),
                "nickname": row[1],
                "preferred_name": row[2],
                "role": row[3],
                "notes": row[4],
                "updated_at": float(row[5]),
            }
            for row in rows
        ]

    def clear_user_profile(self, group_id: int, user_id: int) -> None:
        with self._lock:
            self.db.execute(
                "DELETE FROM user_profiles WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            )
            self.db.commit()

    def list_user_memories(
        self, group_id: int, user_id: int, status: str | None = "approved", limit: int = 20
    ) -> list[tuple[int, str, str, float]]:
        with self._lock:
            query = "SELECT id,content,status,created_at FROM user_memory WHERE group_id=? AND user_id=?"
            params: list[Any] = [group_id, user_id]
            if status is not None:
                query += " AND status=?"
                params.append(status)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = self.db.execute(query, params).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), float(r[3])) for r in rows]

    def add_user_memory(
        self,
        group_id: int,
        user_id: int,
        content: str,
        status: str = "approved",
        *,
        source_message_id: int | str | None = None,
        source_user_id: int | None = None,
        source_kind: str = "manual",
    ) -> int:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid memory status")
        with self._lock:
            existing = self.db.execute(
                "SELECT id FROM user_memory WHERE group_id=? AND user_id=? AND content=? "
                "AND status IN ('pending','approved') LIMIT 1",
                (group_id, user_id, content[:500]),
            ).fetchone()
            if existing is not None:
                return int(existing[0])
            cursor = self.db.execute(
                "INSERT INTO user_memory(group_id,user_id,content,status,created_at,source_message_id,source_user_id,source_kind) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (group_id, user_id, content[:500], status, time.time(),
                 None if source_message_id is None else str(source_message_id),
                 source_user_id, str(source_kind)[:40]),
            )
            self.db.commit()
            return int(cursor.lastrowid)

    def set_user_memory_status(self, memory_id: int, status: str) -> None:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid memory status")
        with self._lock:
            self.db.execute("UPDATE user_memory SET status=? WHERE id=?", (status, memory_id))
            self.db.commit()

    def delete_user_memory(self, memory_id: int) -> None:
        with self._lock:
            self.db.execute("DELETE FROM user_memory WHERE id=?", (memory_id,))
            self.db.commit()

    def count_humans(self, group_id: int) -> int:
        with self._lock:
            return int(
                self.db.execute(
                    "SELECT COUNT(DISTINCT user_id) FROM "
                    "(SELECT user_id FROM messages WHERE group_id=? AND is_bot=0 "
                    "ORDER BY id DESC LIMIT 25)",
                    (group_id,),
                ).fetchone()[0]
            )

    def opt_out_count(self, group_id: int) -> int:
        with self._lock:
            return int(
                self.db.execute(
                    "SELECT COUNT(*) FROM opt_out WHERE group_id=?", (group_id,)
                ).fetchone()[0]
            )

    def approved_memories(self, group_id: int, limit: int = 10) -> list[str]:
        with self._lock:
            return [
                row[0]
                for row in self.db.execute(
                    "SELECT content FROM memory WHERE group_id=? AND status='approved' "
                    "ORDER BY id DESC LIMIT ?",
                    (group_id, limit),
                ).fetchall()
            ]

    def list_memories(self, group_id: int, status: str | None = None) -> list[tuple[int, str, str, float]]:
        with self._lock:
            if status:
                rows = self.db.execute(
                    "SELECT id,content,status,created_at FROM memory "
                    "WHERE group_id=? AND status=? ORDER BY id DESC",
                    (group_id, status),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT id,content,status,created_at FROM memory "
                    "WHERE group_id=? ORDER BY id DESC",
                    (group_id,),
                ).fetchall()
        return [(int(row[0]), str(row[1]), str(row[2]), float(row[3])) for row in rows]

    def add_memory(
        self,
        group_id: int,
        content: str,
        status: str = "approved",
        *,
        source_message_id: int | str | None = None,
        source_user_id: int | None = None,
        source_kind: str = "manual",
    ) -> int:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid memory status")
        with self._lock:
            existing = self.db.execute(
                "SELECT id FROM memory WHERE group_id=? AND content=? "
                "AND status IN ('pending','approved') LIMIT 1",
                (group_id, content[:500]),
            ).fetchone()
            if existing is not None:
                return int(existing[0])
            cursor = self.db.execute(
                "INSERT INTO memory(group_id,content,status,created_at,source_message_id,source_user_id,source_kind) "
                "VALUES (?,?,?,?,?,?,?)",
                (group_id, content[:500], status, time.time(),
                 None if source_message_id is None else str(source_message_id),
                 source_user_id, str(source_kind)[:40]),
            )
            self.db.commit()
            return int(cursor.lastrowid)

    def set_memory_status(self, memory_id: int, status: str) -> None:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid memory status")
        with self._lock:
            self.db.execute("UPDATE memory SET status=? WHERE id=?", (status, memory_id))
            self.db.commit()

    def clear_memories(self, group_id: int) -> None:
        with self._lock:
            self.db.execute("DELETE FROM memory WHERE group_id=?", (group_id,))
            self.db.commit()

    def cleanup(self) -> int:
        cutoff = time.time() - self.retention_days * 86400
        with self._lock:
            cursor = self.db.execute("DELETE FROM messages WHERE ts<?", (cutoff,))
            self.db.execute("DELETE FROM proactive WHERE ts<?", (time.time() - 86400,))
            now = time.time()
            self.db.execute("DELETE FROM event_receipts WHERE expires_at<?", (now,))
            self.db.execute(
                "DELETE FROM outbound_receipts WHERE status!='pending' AND updated_at<?",
                (now - max(86400, self.retention_days * 86400),),
            )
            self.db.commit()
            return int(cursor.rowcount)

    def status(self, group_id: int) -> dict[str, Any]:
        with self._lock:
            return {
                "messages": int(
                    self.db.execute(
                        "SELECT COUNT(*) FROM messages WHERE group_id=?", (group_id,)
                    ).fetchone()[0]
                ),
                "opt_out": self.opt_out_count(group_id),
                "approved_memories": int(
                    self.db.execute(
                        "SELECT COUNT(*) FROM memory WHERE group_id=? AND status='approved'",
                        (group_id,),
                    ).fetchone()[0]
                ),
            }

    def load_persona_states(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT group_id,mode,insult_count,last_insult_at,auto_black,changed_at,switch_count "
                "FROM persona_state"
            ).fetchall()
        return {
            int(row[0]): {
                "mode": str(row[1]),
                "insult_count": int(row[2]),
                "last_insult_at": None if row[3] is None else float(row[3]),
                "auto_black": bool(row[4]),
                "changed_at": float(row[5]),
                "switch_count": int(row[6]),
            }
            for row in rows
        }

    def save_persona_state(
        self,
        group_id: int,
        *,
        mode: str,
        insult_count: int,
        last_insult_at: float | None,
        auto_black: bool,
        changed_at: float,
        switch_count: int = 0,
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO persona_state("
                "group_id,mode,insult_count,last_insult_at,auto_black,changed_at,switch_count,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET "
                "mode=excluded.mode,insult_count=excluded.insult_count,"
                "last_insult_at=excluded.last_insult_at,auto_black=excluded.auto_black,"
                "changed_at=excluded.changed_at,switch_count=excluded.switch_count,"
                "updated_at=excluded.updated_at",
                (
                    int(group_id),
                    str(mode),
                    int(insult_count),
                    None if last_insult_at is None else float(last_insult_at),
                    int(bool(auto_black)),
                    float(changed_at),
                    int(switch_count),
                    time.time(),
                ),
            )
            self.db.commit()
