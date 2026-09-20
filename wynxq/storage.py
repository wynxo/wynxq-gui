"""Small, private, thread-safe SQLite history store.

Automatic desktop screenshots are transient. Images the user explicitly sends
as message context are persisted locally so the conversation can render the
same attachment thumbnail after it is reopened.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any


_LOG = logging.getLogger(__name__)


class Store:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            path = root / "wynxq" / "history.sqlite3"
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create with private permissions before SQLite opens the file.
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                endpoint TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (conversation_id, position)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                output_tokens INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                cached_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                duration_ms REAL NOT NULL DEFAULT 0,
                tokens_per_second REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS token_usage_created_at
                ON token_usage(created_at);
            CREATE INDEX IF NOT EXISTS token_usage_conversation
                ON token_usage(conversation_id);
        """)
        self._db.commit()
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(conversations)")}
        migrated = False
        if "pinned" not in columns:
            self._db.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            migrated = True
        if "endpoint" not in columns:
            self._db.execute("ALTER TABLE conversations ADD COLUMN endpoint TEXT NOT NULL DEFAULT ''")
            migrated = True
        if migrated:
            self._db.commit()

    def create_conversation(self, title: str = "New conversation", model: str = "",
                            endpoint: str = "") -> dict:
        now = time.time()
        item = {"id": uuid.uuid4().hex, "title": title.strip()[:200] or "New conversation",
                "model": str(model or ""), "endpoint": str(endpoint or ""),
                "created_at": now, "updated_at": now, "pinned": 0}
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversations (id,title,model,endpoint,created_at,updated_at,pinned) "
                "VALUES (:id,:title,:model,:endpoint,:created_at,:updated_at,:pinned)", item)
        return item

    LIST_SQL = """
        SELECT c.*,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
               (SELECT m.payload FROM messages m WHERE m.conversation_id = c.id
                ORDER BY m.position DESC LIMIT 1) AS last_payload
        FROM conversations c
        ORDER BY c.pinned DESC, c.updated_at DESC, c.id DESC
    """

    @staticmethod
    def _preview(payload: str | None) -> str:
        """A one-line summary of the newest message, for the sidebar."""
        if not payload:
            return ""
        try:
            message = json.loads(payload)
        except (ValueError, TypeError):
            return ""
        if not isinstance(message, dict):
            return ""
        role = message.get("role", "")
        if role == "tool":
            return "Desktop actions"
        text = " ".join(str(message.get("content", "")).split())
        if not text and message.get("thinking"):
            text = " ".join(str(message["thinking"]).split())
        if not text:
            return ""
        prefix = "You: " if role == "user" else ""
        return (prefix + text)[:120]

    def list_conversations(self) -> list[dict]:
        with self._lock:
            rows = [dict(row) for row in self._db.execute(self.LIST_SQL)]
        for row in rows:
            row["preview"] = self._preview(row.pop("last_payload", None))
        return rows

    def search(self, query: str, limit: int = 60) -> list[dict]:
        """Conversations whose title or message text contains ``query``.

        The message scan reads decoded text rather than the stored JSON, so a
        query never matches the encoding itself — "content" and "role" are
        words a person might search for, and `%` is a character they might
        type, not a wildcard.
        """
        limit = max(0, int(limit))
        if not limit:
            return []
        needle = str(query or "").strip().casefold()
        if not needle:
            return self.list_conversations()[:limit]
        results = []
        for conversation in self.list_conversations():
            match = "title" if needle in conversation["title"].casefold() else ""
            if not match:
                for message in self.get_messages(conversation["id"]):
                    if any(needle in str(message.get(field, "")).casefold()
                           for field in ("content", "thinking")):
                        match = "message"
                        break
            if match:
                results.append({**conversation, "match": match})
                if len(results) >= limit:
                    break
        return results

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?",
                             (title.strip()[:200] or "New conversation", time.time(), conversation_id))

    def set_pinned(self, conversation_id: str, pinned: bool) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET pinned=?,updated_at=? WHERE id=?",
                             (1 if pinned else 0, time.time(), conversation_id))

    def delete_conversation(self, conversation_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))

    @staticmethod
    def _decode_message_payload(payload: str, *, conversation_id: str = "") -> dict | None:
        """Decode one persisted message without letting one damaged row brick history."""
        try:
            message = json.loads(payload)
        except (ValueError, TypeError):
            _LOG.warning("Ignoring unreadable message payload in conversation %s", conversation_id)
            return None
        if not isinstance(message, dict):
            _LOG.warning("Ignoring non-object message payload in conversation %s", conversation_id)
            return None
        return message

    def get_messages(self, conversation_id: str) -> list[dict]:
        with self._lock:
            rows = list(self._db.execute(
                "SELECT payload FROM messages WHERE conversation_id=? ORDER BY position",
                (conversation_id,),
            ))
        messages = []
        for row in rows:
            message = self._decode_message_payload(row[0], conversation_id=conversation_id)
            if message is not None:
                messages.append(message)
        return messages

    def set_messages(self, conversation_id: str, messages: list[dict], model: str | None = None,
                     endpoint: str | None = None) -> None:
        # Never mutate the live conversation; it may still contain images for
        # inference. Automatic agent screenshots are always transient. Explicit
        # user attachments carry _wynxq_attachments metadata and are kept
        # locally so their sent-message thumbnails survive a reload.
        saved = copy.deepcopy([message for message in messages
            if not (message.get("images") and message.get("content", "").startswith("Current desktop screenshot ("))])
        for message in saved:
            if message.get("images") and not message.get("_wynxq_attachments"):
                message.pop("images", None)
        encoded = [json.dumps(message, ensure_ascii=False, allow_nan=False) for message in saved]
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone() is None:
                raise KeyError(f"Unknown conversation: {conversation_id}")
            self._db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            self._db.executemany("INSERT INTO messages VALUES (?,?,?)",
                                 [(conversation_id, i, payload) for i, payload in enumerate(encoded)])
            updates = ["updated_at=?"]
            values: list[Any] = [time.time()]
            if model is not None:
                updates.append("model=?")
                values.append(str(model))
            if endpoint is not None:
                updates.append("endpoint=?")
                values.append(str(endpoint))
            values.append(conversation_id)
            self._db.execute(
                "UPDATE conversations SET " + ",".join(updates) + " WHERE id=?", values)

    def set_conversation_runtime(self, conversation_id: str, model: str | None = None,
                                 endpoint: str | None = None) -> None:
        """Persist the inference pair for one chat without rewriting its messages."""
        updates, values = [], []
        if model is not None:
            updates.append("model=?")
            values.append(str(model))
        if endpoint is not None:
            updates.append("endpoint=?")
            values.append(str(endpoint))
        if not updates:
            return
        values.append(str(conversation_id))
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET " + ",".join(updates) + " WHERE id=?", values)

    def record_token_usage(self, conversation_id: str, model: str, metrics: dict,
                           created_at: float | None = None) -> bool:
        """Persist one completed model run's exact Ollama token accounting.

        Usage is intentionally independent from conversation rows. Deleting a
        chat should not rewrite the all-time/month/week counters, just as
        deleting a terminal transcript does not undo work the model performed.
        """
        output = max(0, int(metrics.get("tokens", 0) or 0))
        prompt = max(0, int(metrics.get("prompt_tokens", 0) or 0))
        cached = max(0, int(metrics.get("cached_prompt_tokens", 0) or 0))
        if not output and not prompt:
            return False
        duration = max(0.0, float(metrics.get("total_ms", 0.0) or 0.0))
        rate = max(0.0, float(metrics.get("tokens_per_second", 0.0) or 0.0))
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO token_usage "
                "(created_at,conversation_id,model,output_tokens,prompt_tokens,cached_prompt_tokens,duration_ms,tokens_per_second) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (time.time() if created_at is None else float(created_at),
                 str(conversation_id or ""), str(model or ""), output, prompt,
                 cached, duration, rate),
            )
        return True

    @staticmethod
    def _usage_boundaries(now: float) -> dict[str, float | None]:
        local = datetime.fromtimestamp(float(now))
        today = local.replace(hour=0, minute=0, second=0, microsecond=0)
        week = today - timedelta(days=today.weekday())
        month = today.replace(day=1)
        return {
            "today": today.timestamp(),
            "week": week.timestamp(),
            "month": month.timestamp(),
            "allTime": None,
        }

    def token_usage_summary(self, now: float | None = None) -> dict[str, dict]:
        """Aggregate exact usage in local-day, Monday-week, month and lifetime buckets."""
        now = time.time() if now is None else float(now)
        summary: dict[str, dict] = {}
        with self._lock:
            for key, start in self._usage_boundaries(now).items():
                if start is None:
                    where, params = "WHERE created_at <= ?", (now,)
                else:
                    where, params = "WHERE created_at >= ? AND created_at <= ?", (start, now)
                row = self._db.execute(
                    "SELECT COALESCE(SUM(output_tokens),0) output_tokens, "
                    "COALESCE(SUM(prompt_tokens),0) prompt_tokens, "
                    "COALESCE(SUM(cached_prompt_tokens),0) cached_prompt_tokens, "
                    "COUNT(*) runs, "
                    "COALESCE(SUM(CASE WHEN tokens_per_second > 0 THEN tokens_per_second * output_tokens ELSE 0 END),0) rate_weighted, "
                    "COALESCE(SUM(CASE WHEN tokens_per_second > 0 THEN output_tokens ELSE 0 END),0) rate_tokens "
                    f"FROM token_usage {where}", params,
                ).fetchone()
                output = int(row["output_tokens"] or 0)
                prompt = int(row["prompt_tokens"] or 0)
                rate_tokens = int(row["rate_tokens"] or 0)
                average_rate = (float(row["rate_weighted"] or 0.0) / rate_tokens) if rate_tokens else 0.0
                summary[key] = {
                    "tokens": output + prompt,
                    "outputTokens": output,
                    "promptTokens": prompt,
                    "cachedTokens": int(row["cached_prompt_tokens"] or 0),
                    "runs": int(row["runs"] or 0),
                    "averageRate": round(average_rate, 1),
                }
        return summary

    def token_usage_daily(self, days: int = 7, now: float | None = None) -> list[dict]:
        """Exact local-day usage for a compact trend view, including empty days."""
        days = max(2, min(int(days or 7), 31))
        now = time.time() if now is None else float(now)
        local_now = datetime.fromtimestamp(now)
        today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        starts = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
        first = starts[0].timestamp()
        buckets = {
            start.date(): {
                "date": start.date().isoformat(),
                "label": start.strftime("%a"),
                "tokens": 0,
                "outputTokens": 0,
                "promptTokens": 0,
                "runs": 0,
                "rateWeighted": 0.0,
                "rateTokens": 0,
            }
            for start in starts
        }
        with self._lock:
            rows = self._db.execute(
                "SELECT created_at, output_tokens, prompt_tokens, tokens_per_second "
                "FROM token_usage WHERE created_at >= ? AND created_at <= ? ORDER BY created_at",
                (first, now),
            ).fetchall()
        for row in rows:
            day = datetime.fromtimestamp(float(row["created_at"])).date()
            bucket = buckets.get(day)
            if bucket is None:
                continue
            output = int(row["output_tokens"] or 0)
            prompt = int(row["prompt_tokens"] or 0)
            rate = max(0.0, float(row["tokens_per_second"] or 0.0))
            bucket["outputTokens"] += output
            bucket["promptTokens"] += prompt
            bucket["tokens"] += output + prompt
            bucket["runs"] += 1
            if output and rate:
                bucket["rateWeighted"] += output * rate
                bucket["rateTokens"] += output
        result = []
        for start in starts:
            bucket = buckets[start.date()]
            weighted = float(bucket.pop("rateWeighted"))
            rate_tokens = int(bucket.pop("rateTokens"))
            bucket["averageRate"] = round(weighted / rate_tokens, 1) if rate_tokens else 0.0
            result.append(bucket)
        return result

    def token_usage_models(self, days: int = 30, now: float | None = None,
                           limit: int = 6) -> list[dict]:
        """Top models by exact input + output usage over a recent local window."""
        days = max(1, min(int(days or 30), 3650))
        limit = max(1, min(int(limit or 6), 20))
        now = time.time() if now is None else float(now)
        start = now - days * 86400
        with self._lock:
            rows = self._db.execute(
                "SELECT model, SUM(output_tokens) output_tokens, "
                "SUM(prompt_tokens) prompt_tokens, COUNT(*) runs, "
                "SUM(CASE WHEN tokens_per_second > 0 THEN tokens_per_second * output_tokens ELSE 0 END) rate_weighted, "
                "SUM(CASE WHEN tokens_per_second > 0 THEN output_tokens ELSE 0 END) rate_tokens "
                "FROM token_usage WHERE created_at >= ? AND created_at <= ? "
                "GROUP BY model ORDER BY (SUM(output_tokens) + SUM(prompt_tokens)) DESC LIMIT ?",
                (start, now, limit),
            ).fetchall()
        result = []
        for row in rows:
            output = int(row["output_tokens"] or 0)
            prompt = int(row["prompt_tokens"] or 0)
            rate_tokens = int(row["rate_tokens"] or 0)
            result.append({
                "name": str(row["model"] or "Unknown model"),
                "tokens": output + prompt,
                "outputTokens": output,
                "promptTokens": prompt,
                "runs": int(row["runs"] or 0),
                "averageRate": round(float(row["rate_weighted"] or 0.0) / rate_tokens, 1)
                               if rate_tokens else 0.0,
            })
        return result

    def conversation_token_usage(self, conversation_id: str) -> dict[str, int]:
        """Return exact recorded usage for one conversation without period scans.

        Cached prompt tokens are metadata about the prompt count, not extra
        input, so the total is always prompt + output exactly once.
        """
        conversation_id = str(conversation_id or "")
        if not conversation_id:
            return {"tokens": 0, "outputTokens": 0, "promptTokens": 0,
                    "cachedTokens": 0, "runs": 0}
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(SUM(output_tokens),0) output_tokens, "
                "COALESCE(SUM(prompt_tokens),0) prompt_tokens, "
                "COALESCE(SUM(cached_prompt_tokens),0) cached_prompt_tokens, "
                "COUNT(*) runs FROM token_usage WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
        output = int(row["output_tokens"] or 0)
        prompt = int(row["prompt_tokens"] or 0)
        return {
            "tokens": output + prompt,
            "outputTokens": output,
            "promptTokens": prompt,
            "cachedTokens": int(row["cached_prompt_tokens"] or 0),
            "runs": int(row["runs"] or 0),
        }

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            _LOG.warning("Ignoring unreadable setting %s", key)
            return default

    def set_setting(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self._lock, self._db:
            self._db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encoded))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._db.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
            self._db.close()
