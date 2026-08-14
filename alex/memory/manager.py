"""
MemoryManager - the ONLY way the rest of ALEX touches persistent storage.

Design rule (important, do not violate): the LLM and tools never see a SQL
connection. Tools call methods on this class (remember/recall/update/forget,
preferences, facts). This keeps memory access auditable, lets us enforce
limits/validation in one place, and means we can change the storage engine
later without touching tools, plugins or the Core.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from alex.core.errors import MemoryError_
from alex.memory.db import Database
from alex.memory.models import Fact, MemoryItem, Message

log = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, db: Database, *, recent_messages: int = 20, max_facts_in_prompt: int = 12):
        self._db = db
        self._recent_messages = recent_messages
        self._max_facts_in_prompt = max_facts_in_prompt

    # ------------------------------------------------------------------ #
    # Conversations / short-term context
    # ------------------------------------------------------------------ #
    async def start_conversation(self, channel: str = "voice", title: str | None = None) -> str:
        conv_id = str(uuid.uuid4())
        await self._db.conn.execute(
            "INSERT INTO conversations (id, channel, title) VALUES (?, ?, ?)",
            (conv_id, channel, title),
        )
        await self._db.conn.commit()
        return conv_id

    async def add_message(self, conversation_id: str, role: str, content: str) -> None:
        if role not in ("user", "assistant", "system", "tool"):
            raise MemoryError_(f"Invalid message role: {role}")
        await self._db.conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )
        await self._db.conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        await self._db.conn.commit()

    async def get_recent_messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        limit = limit or self._recent_messages
        cursor = await self._db.conn.execute(
            """SELECT role, content, created_at FROM messages
               WHERE conversation_id = ? ORDER BY id DESC LIMIT ?""",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        return [Message(role=r["role"], content=r["content"], created_at=r["created_at"]) for r in reversed(rows)]

    async def latest_conversation_id(self, channel: str = "voice") -> str | None:
        cursor = await self._db.conn.execute(
            "SELECT id FROM conversations WHERE channel = ? ORDER BY updated_at DESC LIMIT 1",
            (channel,),
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------ #
    # Long-term memories (freeform, searchable)
    # ------------------------------------------------------------------ #
    async def remember(
        self,
        content: str,
        *,
        kind: str = "memory",
        tags: list[str] | None = None,
        project: str | None = None,
        importance: float = 0.5,
    ) -> int:
        if not content or not content.strip():
            raise MemoryError_("Cannot store an empty memory")
        tags_str = ",".join(tags or [])
        cursor = await self._db.conn.execute(
            """INSERT INTO memories (kind, content, tags, project, importance)
               VALUES (?, ?, ?, ?, ?)""",
            (kind, content.strip(), tags_str, project, max(0.0, min(1.0, importance))),
        )
        await self._db.conn.commit()
        log.info("Stored memory #%s (kind=%s, project=%s)", cursor.lastrowid, kind, project)
        return cursor.lastrowid

    async def recall(
        self, query: str, *, limit: int = 5, project: str | None = None
    ) -> list[MemoryItem]:
        """Full-text search over long-term memories, most relevant first."""
        if not query or not query.strip():
            return []
        fts_query = _sanitize_fts_query(query)
        if not fts_query:
            return []
        sql = """
            SELECT m.id, m.kind, m.content, m.tags, m.project, m.importance, m.created_at
            FROM memories_fts f
            JOIN memories m ON m.id = f.rowid
            WHERE memories_fts MATCH ?
        """
        params: list = [fts_query]
        if project:
            sql += " AND m.project = ?"
            params.append(project)
        sql += " ORDER BY bm25(memories_fts), m.importance DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.conn.execute(sql, params)
        rows = await cursor.fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            await self._db.conn.execute(
                f"UPDATE memories SET last_accessed_at = datetime('now') "
                f"WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            await self._db.conn.commit()
        return [
            MemoryItem(
                id=r["id"], kind=r["kind"], content=r["content"],
                tags=[t for t in r["tags"].split(",") if t],
                project=r["project"], importance=r["importance"], created_at=r["created_at"],
            )
            for r in rows
        ]

    async def recent_memories(self, limit: int = 5, project: str | None = None) -> list[MemoryItem]:
        sql = "SELECT id, kind, content, tags, project, importance, created_at FROM memories"
        params: list = []
        if project:
            sql += " WHERE project = ?"
            params.append(project)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            MemoryItem(
                id=r["id"], kind=r["kind"], content=r["content"],
                tags=[t for t in r["tags"].split(",") if t],
                project=r["project"], importance=r["importance"], created_at=r["created_at"],
            )
            for r in rows
        ]

    async def update_memory(self, memory_id: int, content: str) -> bool:
        cursor = await self._db.conn.execute(
            "UPDATE memories SET content = ?, updated_at = datetime('now') WHERE id = ?",
            (content, memory_id),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def forget(self, memory_id: int) -> bool:
        cursor = await self._db.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await self._db.conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log.info("Forgot memory #%s", memory_id)
        return deleted

    # ------------------------------------------------------------------ #
    # Facts (structured key/value)
    # ------------------------------------------------------------------ #
    async def set_fact(self, key: str, value: str, *, category: str = "general",
                        confidence: float = 1.0, source: str = "user") -> None:
        await self._db.conn.execute(
            """INSERT INTO facts (key, value, category, confidence, source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value=excluded.value, category=excluded.category,
                 confidence=excluded.confidence, source=excluded.source,
                 updated_at=datetime('now')""",
            (key, value, category, confidence, source),
        )
        await self._db.conn.commit()

    async def get_fact(self, key: str) -> Fact | None:
        cursor = await self._db.conn.execute(
            "SELECT key, value, category, confidence, source FROM facts WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return Fact(**dict(row)) if row else None

    async def list_facts(self, category: str | None = None, limit: int | None = None) -> list[Fact]:
        sql = "SELECT key, value, category, confidence, source FROM facts"
        params: list = []
        if category:
            sql += " WHERE category = ?"
            params.append(category)
        sql += " ORDER BY updated_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self._db.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Fact(**dict(r)) for r in rows]

    async def forget_fact(self, key: str) -> bool:
        cursor = await self._db.conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        await self._db.conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ #
    # Preferences
    # ------------------------------------------------------------------ #
    async def set_preference(self, key: str, value: str) -> None:
        await self._db.conn.execute(
            """INSERT INTO preferences (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')""",
            (key, value),
        )
        await self._db.conn.commit()

    async def get_preference(self, key: str, default: str | None = None) -> str | None:
        cursor = await self._db.conn.execute("SELECT value FROM preferences WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

    async def get_all_preferences(self) -> dict[str, str]:
        cursor = await self._db.conn.execute("SELECT key, value FROM preferences")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ------------------------------------------------------------------ #
    # Reminders (used by the reminders plugin)
    # ------------------------------------------------------------------ #
    async def add_reminder(self, text: str, due_at: str) -> str:
        reminder_id = str(uuid.uuid4())
        await self._db.conn.execute(
            "INSERT INTO reminders (id, text, due_at) VALUES (?, ?, ?)",
            (reminder_id, text, due_at),
        )
        await self._db.conn.commit()
        return reminder_id

    async def list_due_reminders(self, now_iso: str) -> list[dict]:
        cursor = await self._db.conn.execute(
            "SELECT id, text, due_at FROM reminders WHERE status = 'pending' AND due_at <= ?",
            (now_iso,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_reminder_fired(self, reminder_id: str) -> None:
        await self._db.conn.execute(
            "UPDATE reminders SET status = 'fired' WHERE id = ?", (reminder_id,)
        )
        await self._db.conn.commit()

    async def cancel_reminder(self, reminder_id: str) -> bool:
        cursor = await self._db.conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def list_pending_reminders(self) -> list[dict]:
        cursor = await self._db.conn.execute(
            "SELECT id, text, due_at FROM reminders WHERE status = 'pending' ORDER BY due_at"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Prompt context building
    # ------------------------------------------------------------------ #
    async def build_context_bundle(self, conversation_id: str, user_query: str) -> dict:
        """
        Assemble everything the AI layer needs to answer with continuity:
        recent turns, relevant long-term memories (via FTS on the query) and
        the most important facts/preferences. Kept small on purpose to
        respect context-window / latency budgets on a Pi.
        """
        recent = await self.get_recent_messages(conversation_id)
        relevant_memories = await self.recall(user_query, limit=5)
        facts = await self.list_facts(limit=self._max_facts_in_prompt)
        prefs = await self.get_all_preferences()
        return {
            "recent_messages": recent,
            "relevant_memories": relevant_memories,
            "facts": facts,
            "preferences": prefs,
        }


def _sanitize_fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH query (AND of tokens, no operator injection)."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if len(t) > 1]
    if not tokens:
        return ""
    return " AND ".join(f'"{t}"*' for t in tokens[:12])


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
