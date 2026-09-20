"""Small, private, thread-safe SQLite history store.

Automatic desktop screenshots are transient. Images the user explicitly sends
as message context are persisted locally so the conversation can render the
same attachment thumbnail after it is reopened.

Store is the stable persistence facade. Database lifecycle and settings stay
here; conversation/history behavior and token-accounting behavior live in
focused Qt-free modules and are bound below without changing callers.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from . import storage_conversation_ops as _conversation_ops
from . import storage_usage_ops as _usage_ops


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
        self._db = sqlite3.connect(
            self.path, check_same_thread=False, timeout=5.0
        )
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
        columns = {
            row["name"]
            for row in self._db.execute("PRAGMA table_info(conversations)")
        }
        migrated = False
        if "pinned" not in columns:
            self._db.execute(
                "ALTER TABLE conversations "
                "ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )
            migrated = True
        if "endpoint" not in columns:
            self._db.execute(
                "ALTER TABLE conversations "
                "ADD COLUMN endpoint TEXT NOT NULL DEFAULT ''"
            )
            migrated = True
        if migrated:
            self._db.commit()

    # ------------------------------------------------ conversation/history slice
    LIST_SQL = _conversation_ops.LIST_SQL
    _preview = staticmethod(_conversation_ops._preview)
    create_conversation = _conversation_ops.create_conversation
    list_conversations = _conversation_ops.list_conversations
    search = _conversation_ops.search
    get_conversation = _conversation_ops.get_conversation
    rename_conversation = _conversation_ops.rename_conversation
    set_pinned = _conversation_ops.set_pinned
    delete_conversation = _conversation_ops.delete_conversation
    _decode_message_payload = staticmethod(_conversation_ops._decode_message_payload)
    get_messages = _conversation_ops.get_messages
    set_messages = _conversation_ops.set_messages
    set_conversation_runtime = _conversation_ops.set_conversation_runtime

    # ------------------------------------------------ exact usage slice
    record_token_usage = _usage_ops.record_token_usage
    _usage_boundaries = staticmethod(_usage_ops._usage_boundaries)
    token_usage_summary = _usage_ops.token_usage_summary
    token_usage_daily = _usage_ops.token_usage_daily
    token_usage_models = _usage_ops.token_usage_models
    conversation_token_usage = _usage_ops.conversation_token_usage

    # ------------------------------------------------ settings + lifecycle
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
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
            self._db.execute(
                "INSERT INTO settings VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, encoded),
            )

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
