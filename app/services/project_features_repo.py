"""기능정의서 저장소 — 메타 1 row + 행 N rows.

project_requirements_repo 와 동일한 트랜잭션 full-replace 전략.
- PUT 호출 시 메타 UPSERT + 행 전체 삭제·재삽입.
"""

import logging
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """앱 기동 시 1회. project_features + project_feature_rows 생성."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_features (
                project_id     BIGINT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                business_name  TEXT NOT NULL DEFAULT '',
                system_name    TEXT NOT NULL DEFAULT '',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_feature_rows (
                id              BIGSERIAL PRIMARY KEY,
                project_id      BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                row_order       INTEGER NOT NULL,
                feature_id      TEXT NOT NULL DEFAULT '',
                name            TEXT NOT NULL DEFAULT '',
                requirement_id  TEXT NOT NULL DEFAULT '',
                description     TEXT NOT NULL DEFAULT '',
                flow            TEXT NOT NULL DEFAULT '',
                exception       TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_project_feature_rows_project_order
            ON project_feature_rows(project_id, row_order)
        """)


def get(project_id: int) -> dict:
    """반환: {business_name, system_name, rows: [{id, row_order, …}, ...]}.

    데이터 없어도 빈 메타·빈 rows 반환 (404 X — 폼은 항상 존재).
    """
    with db.connection() as conn:
        meta = conn.execute(
            "SELECT business_name, system_name FROM project_features "
            "WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT id, row_order, feature_id, name, requirement_id,
                   description, flow, exception
            FROM project_feature_rows
            WHERE project_id = ?
            ORDER BY row_order ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return {
            "business_name": (meta["business_name"] if meta else "") or "",
            "system_name":   (meta["system_name"]   if meta else "") or "",
            "rows":          [dict(r) for r in rows],
        }


def save(
    project_id: int,
    business_name: str,
    system_name: str,
    rows: list[dict],
) -> dict:
    """트랜잭션 full replace. 반환: 저장 후 get() 결과 (id 재발급된 rows 포함)."""
    now = datetime.utcnow().isoformat()
    safe_rows = rows or []
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO project_features
            (project_id, business_name, system_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (project_id) DO UPDATE SET
                business_name = EXCLUDED.business_name,
                system_name   = EXCLUDED.system_name,
                updated_at    = EXCLUDED.updated_at
            """,
            (project_id, business_name or "", system_name or "", now, now),
        )
        conn.execute(
            "DELETE FROM project_feature_rows WHERE project_id = ?",
            (project_id,),
        )
        for idx, row in enumerate(safe_rows):
            conn.execute(
                """
                INSERT INTO project_feature_rows
                (project_id, row_order, feature_id, name, requirement_id,
                 description, flow, exception, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, idx,
                    (row.get("feature_id") or ""),
                    (row.get("name") or ""),
                    (row.get("requirement_id") or ""),
                    (row.get("description") or ""),
                    (row.get("flow") or ""),
                    (row.get("exception") or ""),
                    now, now,
                ),
            )
    logger.info("features saved: project=%d rows=%d", project_id, len(safe_rows))
    return get(project_id)
