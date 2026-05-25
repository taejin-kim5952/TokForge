"""프로젝트 문서 저장소 — 메뉴별 산출물 문서 CRUD.

각 프로젝트의 메뉴(overview, requirements, features, wbs, ...)별로
JSON 형태의 문서를 저장한다.

(project_id, doc_type) 쌍이 UNIQUE — 메뉴당 문서는 1개.
"""

import json
import logging
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


def init_schema() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_documents (
                id          BIGSERIAL PRIMARY KEY,
                project_id  BIGINT NOT NULL,
                doc_type    TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                UNIQUE (project_id, doc_type),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_documents_project "
            "ON project_documents(project_id)"
        )


def get(project_id: int, doc_type: str) -> dict:
    """문서 조회. 없으면 빈 dict 반환."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT content FROM project_documents "
            "WHERE project_id = ? AND doc_type = ?",
            (project_id, doc_type),
        ).fetchone()
        if not row:
            return {}
        return json.loads(row["content"])


def save(project_id: int, doc_type: str, content: dict) -> dict:
    """문서 저장 (없으면 INSERT, 있으면 UPDATE)."""
    now = datetime.utcnow().isoformat()
    content_json = json.dumps(content, ensure_ascii=False)
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO project_documents (project_id, doc_type, content, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (project_id, doc_type)
            DO UPDATE SET content = EXCLUDED.content, updated_at = EXCLUDED.updated_at
            """,
            (project_id, doc_type, content_json, now),
        )
    logger.info("document saved: project=%d type=%s", project_id, doc_type)
    return {
        "project_id": project_id,
        "doc_type": doc_type,
        "content": content,
        "updated_at": now,
    }
