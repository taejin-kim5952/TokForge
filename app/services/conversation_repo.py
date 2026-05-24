"""대화·메시지 저장소 — 사용자별 격리, 턴 별점."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)

MENU_TOKFORGE = "tokforge"
MENU_OVERVIEW = "overview"
MENU_REQUIREMENTS = "requirements"


def _now() -> str:
    return datetime.utcnow().isoformat()


def init_schema() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id              TEXT PRIMARY KEY,
                owner_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                menu_key        TEXT NOT NULL DEFAULT 'tokforge',
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
            CREATE INDEX IF NOT EXISTS idx_conversations_owner_project_updated
            ON conversations(owner_user_id, project_id, updated_at DESC)
        """)
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "menu_key" not in cols:
            conn.execute(
                "ALTER TABLE conversations ADD COLUMN menu_key TEXT NOT NULL DEFAULT 'tokforge'"
            )
            conn.execute(
                """
                UPDATE conversations SET menu_key = ?
                WHERE EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = conversations.id
                      AND m.meta_json LIKE '%"type": "organize"%'
                )
                """,
                (MENU_OVERVIEW,),
            )
            conn.execute(
                """
                UPDATE conversations SET menu_key = ?
                WHERE project_id IS NOT NULL
                  AND menu_key = ?
                  AND EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = conversations.id
                      AND m.meta_json LIKE '%"type": "chat"%'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = conversations.id
                      AND (m.meta_json LIKE '%"trace"%'
                           OR m.meta_json LIKE '%"usage"%')
                  )
                """,
                (MENU_OVERVIEW, MENU_TOKFORGE),
            )
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_owner_project_menu_updated
            ON conversations(owner_user_id, project_id, menu_key, updated_at DESC)
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
    menu_key: str = MENU_TOKFORGE,
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
            INSERT INTO conversations (
                id, owner_user_id, project_id, menu_key, title, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, owner_user_id, project_id, menu_key, title, now, now),
        )
        conn.commit()
    return get_owned(cid, owner_user_id)  # type: ignore[return-value]


def get_owned(conversation_id: str, owner_user_id: int) -> dict | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, menu_key, title, created_at, updated_at "
            "FROM conversations WHERE id = ? AND owner_user_id = ?",
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


def update_content(
    message_id: str,
    owner_user_id: int,
    content: str,
) -> dict | None:
    """assistant 메시지의 content 를 업데이트 (스트리밍 종료 시점에 호출).

    소유권은 JOIN 으로 검증 — 다른 사용자의 메시지는 절대 갱신 못 함.
    """
    now = _now()
    with db.connection() as conn:
        msg = conn.execute(
            """
            SELECT m.id FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ? AND c.owner_user_id = ?
            """,
            (message_id, owner_user_id),
        ).fetchone()
        if not msg:
            return None
        conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (content, message_id),
        )
        conn.execute(
            """
            UPDATE conversations SET updated_at = ?
            WHERE id = (SELECT conversation_id FROM messages WHERE id = ?)
            """,
            (now, message_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, role, content, reasoning, meta_json, rating, rated_at, created_at, seq "
            "FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return _row_to_message(dict(row)) if row else None


def delete_if_empty_assistant(message_id: str, owner_user_id: int) -> bool:
    """빈 assistant 메시지면 삭제 (스트림 중단 등으로 content 가 비어있는 경우)."""
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT m.id, m.content, m.role FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ? AND c.owner_user_id = ?
            """,
            (message_id, owner_user_id),
        ).fetchone()
        if not row:
            return False
        if row["role"] != "assistant" or (row["content"] or "").strip():
            return False
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        return True


def list_by_project(
    owner_user_id: int,
    project_id: int,
    *,
    menu_key: str,
    limit: int = 50,
) -> list[dict]:
    """프로젝트·메뉴(overview 등)별 대화 목록 + 메시지 수 + has_organize 집계."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id, c.title, c.created_at, c.updated_at,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
                EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.conversation_id = c.id
                      AND m.meta_json LIKE '%"type": "organize"%'
                ) AS has_organize
            FROM conversations c
            WHERE c.owner_user_id = ? AND c.project_id = ? AND c.menu_key = ?
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (owner_user_id, project_id, menu_key, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "message_count": r["message_count"],
                "has_organize": bool(r["has_organize"]),
            }
            for r in rows
        ]


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
