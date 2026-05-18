"""프로젝트 저장소 — 사용자별 프로젝트 CRUD.

격리 보장: 모든 read/write SQL이 `owner_user_id = ?` 를 강제. API 표면에서
owner 지정 불가 — 항상 `get_current_user()` 결과로부터 흘러옴.
"""

import logging
import sqlite3
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


class DuplicateProjectName(ValueError):
    """같은 user의 같은 name으로 이미 프로젝트가 존재."""


def init_schema() -> None:
    """앱 기동 시 1회."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name           TEXT    NOT NULL,
                description    TEXT,
                created_at     TEXT    NOT NULL,
                updated_at     TEXT    NOT NULL,
                UNIQUE (owner_user_id, name)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id)")
        conn.commit()


def list_for_owner(owner_user_id: int) -> list[dict]:
    """특정 사용자가 소유한 프로젝트 전체 (최신순)."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, created_at, updated_at "
            "FROM projects WHERE owner_user_id = ? "
            "ORDER BY created_at DESC",
            (owner_user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_owned(project_id: int, owner_user_id: int) -> dict | None:
    """소유자 확인하며 단건 조회. 남의 거면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at "
            "FROM projects WHERE id = ? AND owner_user_id = ?",
            (project_id, owner_user_id),
        ).fetchone()
        return dict(row) if row else None


def create(owner_user_id: int, name: str, description: str | None = None) -> dict:
    """프로젝트 생성. 같은 user에 같은 name 존재 시 DuplicateProjectName."""
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")

    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO projects (owner_user_id, name, description, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (owner_user_id, name, description, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise DuplicateProjectName(f"project '{name}' already exists")
            raise

        project_id = cursor.lastrowid
        logger.info("project created: id=%d owner=%d name=%s", project_id, owner_user_id, name)
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at "
            "FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return dict(row)


def delete_owned(project_id: int, owner_user_id: int) -> bool:
    """소유자 확인하며 삭제. 성공 시 True, 존재 안 함/남의 것이면 False."""
    with db.connection() as conn:
        cursor = conn.execute(
            "DELETE FROM projects WHERE id = ? AND owner_user_id = ?",
            (project_id, owner_user_id),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("project deleted: id=%d owner=%d", project_id, owner_user_id)
        return deleted
