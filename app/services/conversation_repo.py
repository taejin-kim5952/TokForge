"""대화·메시지 저장소 — 사용자별 격리, 턴 별점."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.utcnow().isoformat()


def init_schema() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id              TEXT PRIMARY KEY,
                owner_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                title           TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated
            ON conversations(owner_user_id, updated_at DESC)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id               TEXT PRIMARY KEY,
                conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role             TEXT NOT NULL,
                content          TEXT NOT NULL,
                reasoning        TEXT,
                meta_json        TEXT,
                rating           INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
                rated_at         TEXT,
                created_at       TEXT NOT NULL,
                seq              INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_seq
            ON messages(conversation_id, seq)
        """)
        conn.commit()


def _row_to_message(row: dict) -> dict:
    out = dict(row)
    meta_raw = out.pop("meta_json", None)
    if meta_raw:
        try:
            out["meta"] = json.loads(meta_raw)
        except json.JSONDecodeError:
            out["meta"] = None
    else:
        out["meta"] = None
    return out


def create(
    owner_user_id: int,
    title: str,
    *,
    conversation_id: str | None = None,
    project_id: int | None = None,
) -> dict:
    cid = conversation_id or str(uuid.uuid4())
    title = title.strip() or "New chat"
    now = _now()
    with db.connection() as conn:
        if conn.execute("SELECT id FROM conversations WHERE id = ?", (cid,)).fetchone():
            raise ValueError(f"conversation id already exists: {cid}")
        if project_id is not None:
            proj = conn.execute(
                "SELECT id FROM projects WHERE id = ? AND owner_user_id = ?",
                (project_id, owner_user_id),
            ).fetchone()
            if not proj:
                raise ValueError("project not found")
        conn.execute(
            """
            INSERT INTO conversations (id, owner_user_id, project_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cid, owner_user_id, project_id, title, now, now),
        )
        conn.commit()
    return get_owned(cid, owner_user_id)  # type: ignore[return-value]


def get_owned(conversation_id: str, owner_user_id: int) -> dict | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, title, created_at, updated_at FROM conversations "
            "WHERE id = ? AND owner_user_id = ?",
            (conversation_id, owner_user_id),
        ).fetchone()
        if not row:
            return None
        conv = dict(row)
        msg_rows = conn.execute(
            """
            SELECT id, role, content, reasoning, meta_json, rating, rated_at, created_at, seq
            FROM messages WHERE conversation_id = ? ORDER BY seq ASC
            """,
            (conversation_id,),
        ).fetchall()
        conv["messages"] = [_row_to_message(dict(m)) for m in msg_rows]
        return conv


def append_message(
    conversation_id: str,
    owner_user_id: int,
    *,
    role: str,
    content: str,
    message_id: str | None = None,
    reasoning: str | None = None,
    meta: dict | None = None,
) -> dict | None:
    if role not in ("user", "assistant"):
        raise ValueError("role must be user or assistant")
    mid = message_id or str(uuid.uuid4())
    now = _now()
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    with db.connection() as conn:
        if not conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND owner_user_id = ?",
            (conversation_id, owner_user_id),
        ).fetchone():
            return None
        if conn.execute("SELECT id FROM messages WHERE id = ?", (mid,)).fetchone():
            row = conn.execute(
                "SELECT id, role, content, reasoning, meta_json, rating, rated_at, created_at, seq "
                "FROM messages WHERE id = ?",
                (mid,),
            ).fetchone()
            return _row_to_message(dict(row)) if row else None
        seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO messages (
                id, conversation_id, role, content, reasoning, meta_json,
                rating, rated_at, created_at, seq
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (mid, conversation_id, role, content, reasoning, meta_json, now, seq),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
        row = conn.execute(
            "SELECT id, role, content, reasoning, meta_json, rating, rated_at, created_at, seq "
            "FROM messages WHERE id = ?",
            (mid,),
        ).fetchone()
        return _row_to_message(dict(row))


def set_rating(
    conversation_id: str,
    message_id: str,
    owner_user_id: int,
    rating: int | None,
) -> dict | None:
    if rating is not None and not (1 <= rating <= 5):
        raise ValueError("rating must be 1..5 or null")
    now = _now()
    with db.connection() as conn:
        msg = conn.execute(
            """
            SELECT m.id, m.role FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ? AND m.conversation_id = ? AND c.owner_user_id = ?
            """,
            (message_id, conversation_id, owner_user_id),
        ).fetchone()
        if not msg:
            return None
        if msg["role"] != "assistant":
            raise ValueError("only assistant messages can be rated")
        conn.execute(
            "UPDATE messages SET rating = ?, rated_at = ? WHERE id = ?",
            (rating, now if rating is not None else None, message_id),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
        row = conn.execute(
            "SELECT id, role, content, reasoning, meta_json, rating, rated_at, created_at, seq "
            "FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return _row_to_message(dict(row))


def export_training_pairs(
    *,
    min_rating: int = 4,
    project_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    if not (1 <= min_rating <= 5):
        raise ValueError("min_rating must be 1..5")
    with db.connection() as conn:
        query = """
            SELECT c.id AS conversation_id, c.project_id, m.id AS message_id,
                   m.content AS assistant_content, m.rating, m.seq
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.role = 'assistant' AND m.rating IS NOT NULL AND m.rating >= ?
              AND TRIM(m.content) != ''
        """
        params: list[object] = [min_rating]
        if project_id is not None:
            query += " AND c.project_id = ?"
            params.append(project_id)
        query += " ORDER BY c.updated_at DESC, m.seq ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        out: list[dict] = []
        for ar in rows:
            user_row = conn.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' "
                "AND seq < ? ORDER BY seq DESC LIMIT 1",
                (ar["conversation_id"], ar["seq"]),
            ).fetchone()
            if not user_row or not str(user_row["content"]).strip():
                continue
            out.append({
                "messages": [
                    {"role": "user", "content": user_row["content"]},
                    {"role": "assistant", "content": ar["assistant_content"]},
                ],
                "rating": ar["rating"],
                "project_id": ar["project_id"],
                "conversation_id": ar["conversation_id"],
                "message_id": ar["message_id"],
            })
        return out
