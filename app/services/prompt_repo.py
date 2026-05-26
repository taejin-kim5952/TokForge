"""프롬프트 저장소 — PostgreSQL 버전 관리.

`app.db` (DATABASE_URL) 와 동일한 Postgres 인스턴스를 사용합니다.

전역(project_id IS NULL): refiner, classifier, compressor, system — /admin
프로젝트(project_id = N): overview_chat, overview_organizer, requirements_chat,
                          requirements_organizer — /projects/{id}/admin
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import db

logger = logging.getLogger(__name__)

GLOBAL_KINDS = (
    "refiner",
    "classifier",
    "compressor",
    "system",
)

PROJECT_KINDS = (
    "overview_chat",
    "overview_organizer",
    "requirements_chat",
    "requirements_organizer",
)

VALID_KINDS = GLOBAL_KINDS + PROJECT_KINDS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_where(project_id: int | None) -> tuple[str, list[Any]]:
    if project_id is None:
        return "project_id IS NULL", []
    return "project_id = ?", [project_id]


def init_schema() -> None:
    """prompts 테이블이 없으면 PostgreSQL DDL로 생성."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompts (
                id          BIGSERIAL PRIMARY KEY,
                project_id  BIGINT REFERENCES projects(id) ON DELETE CASCADE,
                kind        TEXT NOT NULL,
                version     INTEGER NOT NULL,
                body        TEXT NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                note        TEXT,
                UNIQUE (project_id, kind, version)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_prompts_active
            ON prompts (project_id, kind, is_active)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_prompts_project_kind
            ON prompts (project_id, kind)
        """)


def seed_if_empty() -> None:
    """전역 kind 4종만 v1 시드 (project_id IS NULL). 멱등."""
    from app.services.refiner import REFINER_TEMPLATE
    from app.services.router import CLASSIFIER_TEMPLATE
    from app.services.compressor import COMPRESSOR_TEMPLATE
    from app.services.prompt import SYSTEM_TEMPLATE

    seeds = {
        "refiner": REFINER_TEMPLATE,
        "classifier": CLASSIFIER_TEMPLATE,
        "compressor": COMPRESSOR_TEMPLATE,
        "system": SYSTEM_TEMPLATE,
    }
    _seed_kinds(seeds, project_id=None, label="global")


def seed_project_defaults(project_id: int) -> None:
    """프로젝트 생성 시 메뉴별 프롬프트 4종 v1 시드. 멱등."""
    from app.api.project.ai.overview.overview import OVERVIEW_SYSTEM_PROMPT
    from app.api.project.ai.overview.prompts import OVERVIEW_ORGANIZER_PROMPT
    from app.api.project.ai.requirements.requirements import REQUIREMENTS_SYSTEM_PROMPT
    from app.api.project.ai.requirements.prompts import REQUIREMENTS_ORGANIZER_PROMPT

    seeds = {
        "overview_chat": OVERVIEW_SYSTEM_PROMPT,
        "overview_organizer": OVERVIEW_ORGANIZER_PROMPT,
        "requirements_chat": REQUIREMENTS_SYSTEM_PROMPT,
        "requirements_organizer": REQUIREMENTS_ORGANIZER_PROMPT,
    }
    _seed_kinds(seeds, project_id=project_id, label=f"project={project_id}")


def _seed_kinds(
    seeds: dict[str, str],
    *,
    project_id: int | None,
    label: str,
) -> None:
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        now = _now_iso()
        seeded: list[str] = []
        for kind, body in seeds.items():
            _validate_kind(kind)
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM prompts WHERE kind = ? AND {pw}",
                (kind, *pargs),
            ).fetchone()
            if row["c"] > 0:
                continue
            if project_id is None:
                conn.execute(
                    """
                    INSERT INTO prompts (
                        project_id, kind, version, body, is_active, created_at, note
                    ) VALUES (NULL, ?, 1, ?, 1, ?, ?)
                    """,
                    (kind, body, now, "seeded from code constants"),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO prompts (
                        project_id, kind, version, body, is_active, created_at, note
                    ) VALUES (?, ?, 1, ?, 1, ?, ?)
                    """,
                    (project_id, kind, body, now, "seeded from code constants"),
                )
            seeded.append(kind)
        if seeded:
            logger.info("prompts seeded (%s): %s", label, seeded)
        else:
            logger.info("prompts already seeded (%s) — skip", label)


def get_active(kind: str, project_id: int | None = None) -> str | None:
    """활성 프롬프트 본문. project_id=None 이면 전역 행만."""
    _validate_kind(kind)
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        row = conn.execute(
            f"""
            SELECT body FROM prompts
            WHERE kind = ? AND is_active = 1 AND {pw}
            LIMIT 1
            """,
            (kind, *pargs),
        ).fetchone()
        return row["body"] if row else None


def summary(project_id: int | None = None) -> list[dict]:
    """kind별 active_version / total_versions 요약."""
    kinds = PROJECT_KINDS if project_id is not None else GLOBAL_KINDS
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        result = []
        for kind in kinds:
            rows = conn.execute(
                f"SELECT version, is_active FROM prompts WHERE kind = ? AND {pw}",
                (kind, *pargs),
            ).fetchall()
            active_versions = [r["version"] for r in rows if r["is_active"]]
            result.append({
                "kind": kind,
                "active_version": active_versions[0] if active_versions else None,
                "total_versions": len(rows),
            })
        return result


def list_versions(kind: str, project_id: int | None = None) -> list[dict]:
    _validate_kind(kind)
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, version, is_active, created_at, note,
                   char_length(body) AS body_length
            FROM prompts
            WHERE kind = ? AND {pw}
            ORDER BY version DESC
            """,
            (kind, *pargs),
        ).fetchall()
        return [dict(r) for r in rows]


def get_version(
    kind: str,
    version: int,
    project_id: int | None = None,
) -> dict | None:
    _validate_kind(kind)
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        row = conn.execute(
            f"""
            SELECT id, kind, version, body, is_active, created_at, note, project_id
            FROM prompts
            WHERE kind = ? AND version = ? AND {pw}
            """,
            (kind, version, *pargs),
        ).fetchone()
        return dict(row) if row else None


def save_new_version(
    kind: str,
    body: str,
    note: str | None = None,
    *,
    project_id: int | None = None,
) -> dict:
    _validate_kind(kind)
    if not body or not body.strip():
        raise ValueError("body must not be empty")

    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        max_row = conn.execute(
            f"SELECT COALESCE(MAX(version), 0) AS max_v FROM prompts WHERE kind = ? AND {pw}",
            (kind, *pargs),
        ).fetchone()
        new_version = int(max_row["max_v"]) + 1
        now = _now_iso()

        if project_id is None:
            row = conn.execute(
                """
                INSERT INTO prompts (
                    project_id, kind, version, body, is_active, created_at, note
                ) VALUES (NULL, ?, ?, ?, 0, ?, ?)
                RETURNING id
                """,
                (kind, new_version, body, now, note),
            ).fetchone()
        else:
            row = conn.execute(
                """
                INSERT INTO prompts (
                    project_id, kind, version, body, is_active, created_at, note
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                RETURNING id
                """,
                (project_id, kind, new_version, body, now, note),
            ).fetchone()
        new_id = row["id"]
        logger.info(
            "prompt saved: project_id=%r kind=%s version=%d id=%s",
            project_id, kind, new_version, new_id,
        )
        return {"id": new_id, "version": new_version}


def activate(
    kind: str,
    version: int,
    project_id: int | None = None,
) -> None:
    _validate_kind(kind)
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        if not conn.execute(
            f"SELECT id FROM prompts WHERE kind = ? AND version = ? AND {pw}",
            (kind, version, *pargs),
        ).fetchone():
            raise ValueError(f"prompt not found: kind={kind} version={version}")

        conn.execute(
            f"UPDATE prompts SET is_active = 0 WHERE kind = ? AND is_active = 1 AND {pw}",
            (kind, *pargs),
        )
        conn.execute(
            f"""
            UPDATE prompts SET is_active = 1
            WHERE kind = ? AND version = ? AND {pw}
            """,
            (kind, version, *pargs),
        )
        logger.info(
            "prompt activated: project_id=%r kind=%s version=%d",
            project_id, kind, version,
        )


def delete_version(
    kind: str,
    version: int,
    project_id: int | None = None,
) -> None:
    _validate_kind(kind)
    pw, pargs = _project_where(project_id)
    with db.connection() as conn:
        row = conn.execute(
            f"SELECT is_active FROM prompts WHERE kind = ? AND version = ? AND {pw}",
            (kind, version, *pargs),
        ).fetchone()
        if not row:
            raise ValueError(f"prompt not found: kind={kind} version={version}")
        if row["is_active"]:
            raise ValueError(
                f"cannot delete active version (kind={kind} version={version}) — "
                "activate another version first"
            )
        conn.execute(
            f"DELETE FROM prompts WHERE kind = ? AND version = ? AND {pw}",
            (kind, version, *pargs),
        )
        logger.info(
            "prompt deleted: project_id=%r kind=%s version=%d",
            project_id, kind, version,
        )


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r} (allowed: {VALID_KINDS})")
