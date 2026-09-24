"""Conversation persistence behavior for wynxq.storage.

Functions operate on the stable Store facade through its private SQLite
connection/lock. Keeping SQL behavior here separates history persistence from
database lifecycle and usage accounting without changing the public API.
"""
from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from typing import Any


_LOG = logging.getLogger(__name__)


LIST_SQL = """
    SELECT c.*,
           (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
           (SELECT m.payload FROM messages m WHERE m.conversation_id = c.id
            ORDER BY m.position DESC LIMIT 1) AS last_payload
    FROM conversations c
    ORDER BY c.pinned DESC, c.updated_at DESC, c.id DESC
"""


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


def create_conversation(self, title: str = "New conversation", model: str = "",
                        endpoint: str = "") -> dict:
    now = time.time()
    item = {
        "id": uuid.uuid4().hex,
        "title": title.strip()[:200] or "New conversation",
        "model": str(model or ""),
        "endpoint": str(endpoint or ""),
        "created_at": now,
        "updated_at": now,
        "pinned": 0,
    }
    with self._lock, self._db:
        self._db.execute(
            "INSERT INTO conversations (id,title,model,endpoint,created_at,updated_at,pinned) "
            "VALUES (:id,:title,:model,:endpoint,:created_at,:updated_at,:pinned)",
            item,
        )
    return item


def list_conversations(self) -> list[dict]:
    with self._lock:
        rows = [dict(row) for row in self._db.execute(self.LIST_SQL)]
    for row in rows:
        row["preview"] = self._preview(row.pop("last_payload", None))
    return rows


def search(self, query: str, limit: int = 60) -> list[dict]:
    """Conversations whose title or message text contains query."""
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
                if any(
                    needle in str(message.get(field, "")).casefold()
                    for field in ("content", "thinking")
                ):
                    match = "message"
                    break
        if match:
            results.append({**conversation, "match": match})
            if len(results) >= limit:
                break
    return results


def get_conversation(self, conversation_id: str) -> dict | None:
    with self._lock:
        row = self._db.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
    return dict(row) if row else None


def rename_conversation(self, conversation_id: str, title: str) -> None:
    with self._lock, self._db:
        self._db.execute(
            "UPDATE conversations SET title=?,updated_at=? WHERE id=?",
            (title.strip()[:200] or "New conversation", time.time(), conversation_id),
        )


def set_pinned(self, conversation_id: str, pinned: bool) -> None:
    with self._lock, self._db:
        self._db.execute(
            "UPDATE conversations SET pinned=?,updated_at=? WHERE id=?",
            (1 if pinned else 0, time.time(), conversation_id),
        )


def delete_conversation(self, conversation_id: str) -> None:
    with self._lock, self._db:
        self._db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


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
        rows = list(
            self._db.execute(
                "SELECT payload FROM messages WHERE conversation_id=? ORDER BY position",
                (conversation_id,),
            )
        )
    messages = []
    for row in rows:
        message = self._decode_message_payload(row[0], conversation_id=conversation_id)
        if message is not None:
            messages.append(message)
    return messages


def set_messages(self, conversation_id: str, messages: list[dict],
                 model: str | None = None, endpoint: str | None = None) -> None:
    # Never mutate the live conversation; it may still contain images for inference.
    # Automatic agent screenshots are transient. Explicit user attachments carry
    # _wynxq_attachments metadata and remain local so thumbnails survive reload.
    saved = copy.deepcopy([
        message
        for message in messages
        if not (
            message.get("images")
            and message.get("content", "").startswith("Current desktop screenshot (")
        )
    ])
    for message in saved:
        if message.get("images") and not message.get("_wynxq_attachments"):
            message.pop("images", None)
    encoded = [
        json.dumps(message, ensure_ascii=False, allow_nan=False)
        for message in saved
    ]
    with self._lock, self._db:
        if self._db.execute(
            "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone() is None:
            raise KeyError(f"Unknown conversation: {conversation_id}")
        self._db.execute(
            "DELETE FROM messages WHERE conversation_id=?", (conversation_id,)
        )
        self._db.executemany(
            "INSERT INTO messages VALUES (?,?,?)",
            [
                (conversation_id, i, payload)
                for i, payload in enumerate(encoded)
            ],
        )
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
            "UPDATE conversations SET " + ",".join(updates) + " WHERE id=?",
            values,
        )


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
        self._db.execute(
            "UPDATE conversations SET " + ",".join(updates) + " WHERE id=?",
            values,
        )


__all__ = ['create_conversation', 'list_conversations', 'search', 'get_conversation', 'rename_conversation', 'set_pinned', 'delete_conversation', 'get_messages', 'set_messages', 'set_conversation_runtime', 'LIST_SQL']
