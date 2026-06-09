"""프로젝트 PPT 템플릿 저장소 — 레이아웃 블록 템플릿 CRUD + 활성 관리.

(project_id, name) UNIQUE. content 는 TemplateContent JSON 을 TEXT 로 저장.
프로젝트당 활성 템플릿은 최대 1개 — create(set_active)/set_active 가 나머지를 해제한다.
"""

import json
import logging
from datetime import datetime, timezone

import psycopg2

from app import db

logger = logging.getLogger(__name__)


class DuplicateTemplateName(ValueError):
    """같은 프로젝트에 같은 name 의 템플릿이 이미 존재."""


def init_schema() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ppt_templates (
                id          BIGSERIAL PRIMARY KEY,
                project_id  BIGINT  NOT NULL,
                name        TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                content     TEXT    NOT NULL,
                is_active   BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                UNIQUE (project_id, name),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ppt_templates_project "
            "ON ppt_templates(project_id)"
        )


def _meta(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "description": row["description"] or "",
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_for_project(project_id: int) -> list[dict]:
    """메타 목록 (content 제외). 활성 먼저, 최신순."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, project_id, name, description, is_active, created_at, updated_at "
            "FROM ppt_templates WHERE project_id = ? "
            "ORDER BY is_active DESC, updated_at DESC, id DESC",
            (project_id,),
        ).fetchall()
    return [_meta(r) for r in rows]


def get(project_id: int, template_id: int) -> dict | None:
    """단건 (content 포함). 없거나 다른 프로젝트면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM ppt_templates WHERE id = ? AND project_id = ?",
            (template_id, project_id),
        ).fetchone()
    if not row:
        return None
    out = _meta(row)
    out["content"] = json.loads(row["content"])
    return out


def get_active(project_id: int) -> dict | None:
    """활성 템플릿 (content 포함). 없으면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM ppt_templates "
            "WHERE project_id = ? AND is_active = TRUE "
            "ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if not row:
        return None
    out = _meta(row)
    out["content"] = json.loads(row["content"])
    return out


def create(
    project_id: int,
    name: str,
    description: str,
    content: dict,
    *,
    set_active: bool = False,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name must not be empty")
    now = datetime.now(timezone.utc).isoformat()
    content_json = json.dumps(content, ensure_ascii=False)
    with db.connection() as conn:
        if set_active:
            conn.execute(
                "UPDATE ppt_templates SET is_active = FALSE WHERE project_id = ?",
                (project_id,),
            )
        try:
            row = conn.execute(
                "INSERT INTO ppt_templates "
                "(project_id, name, description, content, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (project_id, name, description or "", content_json,
                 bool(set_active), now, now),
            ).fetchone()
        except psycopg2.IntegrityError as e:
            if getattr(e, "pgcode", None) == "23505" or "unique" in str(e).lower():
                raise DuplicateTemplateName(f"template '{name}' already exists") from e
            raise
    logger.info("ppt_template created: project=%d id=%d name=%s",
                project_id, row["id"], name)
    return get(project_id, row["id"])


def update(
    project_id: int,
    template_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    content: dict | None = None,
) -> dict | None:
    sets, params = [], []
    if name is not None:
        sets.append("name = ?")
        params.append(name.strip())
    if description is not None:
        sets.append("description = ?")
        params.append(description)
    if content is not None:
        sets.append("content = ?")
        params.append(json.dumps(content, ensure_ascii=False))
    if not sets:
        return get(project_id, template_id)
    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.extend([template_id, project_id])
    with db.connection() as conn:
        try:
            row = conn.execute(
                f"UPDATE ppt_templates SET {', '.join(sets)} "
                "WHERE id = ? AND project_id = ? RETURNING id",
                tuple(params),
            ).fetchone()
        except psycopg2.IntegrityError as e:
            if getattr(e, "pgcode", None) == "23505" or "unique" in str(e).lower():
                raise DuplicateTemplateName("template name already exists") from e
            raise
    if not row:
        return None
    return get(project_id, template_id)


def set_active(project_id: int, template_id: int) -> bool:
    """대상만 활성, 나머지 해제 — 한 트랜잭션. 대상 없으면 False."""
    now = datetime.now(timezone.utc).isoformat()
    with db.connection() as conn:
        exists = conn.execute(
            "SELECT id FROM ppt_templates WHERE id = ? AND project_id = ?",
            (template_id, project_id),
        ).fetchone()
        if not exists:
            return False
        conn.execute(
            "UPDATE ppt_templates SET is_active = FALSE WHERE project_id = ?",
            (project_id,),
        )
        conn.execute(
            "UPDATE ppt_templates SET is_active = TRUE, updated_at = ? "
            "WHERE id = ? AND project_id = ?",
            (now, template_id, project_id),
        )
    return True


def delete(project_id: int, template_id: int) -> bool:
    with db.connection() as conn:
        cur = conn.execute(
            "DELETE FROM ppt_templates WHERE id = ? AND project_id = ?",
            (template_id, project_id),
        )
        return cur.rowcount > 0
