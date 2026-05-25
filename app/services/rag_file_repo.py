"""프로젝트 RAG 원본 파일 메타데이터 — PostgreSQL."""

import logging
from datetime import datetime

import psycopg2

from app import db

logger = logging.getLogger(__name__)


class DuplicateRagFilename(ValueError):
    """같은 프로젝트에 동일 파일명이 이미 존재."""


def init_schema() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_rag_files (
                id              BIGSERIAL PRIMARY KEY,
                project_id      BIGINT NOT NULL,
                filename        TEXT    NOT NULL,
                storage_path    TEXT    NOT NULL,
                size_bytes      BIGINT NOT NULL,
                chunk_count     INTEGER NOT NULL DEFAULT 0,
                created_by      BIGINT,
                created_at      TEXT    NOT NULL,
                UNIQUE (project_id, filename),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_files_project "
            "ON project_rag_files(project_id)"
        )


def list_for_project(project_id: int) -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, project_id, filename, storage_path, size_bytes, "
            "chunk_count, created_by, created_at "
            "FROM project_rag_files WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_for_project(project_id: int) -> int:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM project_rag_files WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["c"]) if row else 0


def get_owned(file_id: int, project_id: int) -> dict | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, filename, storage_path, size_bytes, "
            "chunk_count, created_by, created_at "
            "FROM project_rag_files WHERE id = ? AND project_id = ?",
            (file_id, project_id),
        ).fetchone()
        return dict(row) if row else None


def create(
    project_id: int,
    filename: str,
    storage_path: str,
    size_bytes: int,
    created_by: int | None,
) -> dict:
    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        try:
            row = conn.execute(
                "INSERT INTO project_rag_files "
                "(project_id, filename, storage_path, size_bytes, chunk_count, "
                "created_by, created_at) VALUES (?, ?, ?, ?, 0, ?, ?) RETURNING id",
                (project_id, filename, storage_path, size_bytes, created_by, now),
            ).fetchone()
        except psycopg2.IntegrityError as e:
            if getattr(e, "pgcode", None) == "23505" or "unique" in str(e).lower():
                raise DuplicateRagFilename(f"file '{filename}' already exists") from e
            raise

        file_id = row["id"]
        out = conn.execute(
            "SELECT id, project_id, filename, storage_path, size_bytes, "
            "chunk_count, created_by, created_at "
            "FROM project_rag_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return dict(out)


def update_chunk_count(file_id: int, project_id: int, chunk_count: int) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE project_rag_files SET chunk_count = ? "
            "WHERE id = ? AND project_id = ?",
            (chunk_count, file_id, project_id),
        )


def delete_owned(file_id: int, project_id: int) -> dict | None:
    """삭제 전 행 반환. 없으면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, filename, storage_path, size_bytes, "
            "chunk_count, created_by, created_at "
            "FROM project_rag_files WHERE id = ? AND project_id = ?",
            (file_id, project_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "DELETE FROM project_rag_files WHERE id = ? AND project_id = ?",
            (file_id, project_id),
        )
        return dict(row)
