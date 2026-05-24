"""프롬프트 저장소 — SQLite 기반 버전 관리.

각 단계(refiner/classifier/compressor/system)별로 여러 버전을 저장하고,
활성화된 한 버전만 실행 중 LLM 호출에 사용. 코드 수정/재기동 없이 교체 가능.
"""

import logging
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)

VALID_KINDS = (
    "refiner",
    "classifier",
    "compressor",
    "system",
    "overview_organizer",
    "requirements_organizer",
)


def init_schema() -> None:
    """앱 기동 시 1회. 테이블 없으면 생성."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prompts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kind        TEXT NOT NULL,
                version     INTEGER NOT NULL,
                body        TEXT NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                note        TEXT,
                UNIQUE(kind, version)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prompts_active ON prompts(kind, is_active)"
        )
        conn.commit()


def seed_if_empty() -> None:
    """비어있는 kind를 v1으로 시드. 기존 kind는 건드리지 않음 (멱등)."""
    from app.services.refiner import REFINER_TEMPLATE
    from app.services.router import CLASSIFIER_TEMPLATE
    from app.services.compressor import COMPRESSOR_TEMPLATE
    from app.services.prompt import SYSTEM_TEMPLATE
    from app.api.project_ai.overview.prompts import OVERVIEW_ORGANIZER_PROMPT
    from app.api.project_ai.requirements.prompts import REQUIREMENTS_ORGANIZER_PROMPT

    seeds = {
        "refiner":                REFINER_TEMPLATE,
        "classifier":             CLASSIFIER_TEMPLATE,
        "compressor":             COMPRESSOR_TEMPLATE,
        "system":                 SYSTEM_TEMPLATE,
        "overview_organizer":     OVERVIEW_ORGANIZER_PROMPT,
        "requirements_organizer": REQUIREMENTS_ORGANIZER_PROMPT,
    }

    with db.connection() as conn:
        now = datetime.utcnow().isoformat()
        seeded: list[str] = []
        for kind, body in seeds.items():
            existing = conn.execute(
                "SELECT COUNT(*) FROM prompts WHERE kind = ?", (kind,),
            ).fetchone()
            if existing[0] > 0:
                continue
            conn.execute(
                "INSERT INTO prompts (kind, version, body, is_active, created_at, note) "
                "VALUES (?, 1, ?, 1, ?, ?)",
                (kind, body, now, "seeded from code constants"),
            )
            seeded.append(kind)
        conn.commit()
        if seeded:
            logger.info("prompts seeded: %s", seeded)
        else:
            logger.info("prompts already seeded for all kinds — skip")


def get_active(kind: str) -> str | None:
    """현재 활성 프롬프트 본문 반환. 없으면 None."""
    _validate_kind(kind)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT body FROM prompts WHERE kind = ? AND is_active = 1 LIMIT 1",
            (kind,),
        ).fetchone()
        return row["body"] if row else None


def summary() -> list[dict]:
    """전체 kind 요약 — Admin 대시보드용.

    반환 예: [{"kind": "refiner", "active_version": 2, "total_versions": 3}, ...]
    """
    with db.connection() as conn:
        result = []
        for kind in VALID_KINDS:
            rows = conn.execute(
                "SELECT version, is_active FROM prompts WHERE kind = ?",
                (kind,),
            ).fetchall()
            active_versions = [r["version"] for r in rows if r["is_active"]]
            result.append({
                "kind": kind,
                "active_version": active_versions[0] if active_versions else None,
                "total_versions": len(rows),
            })
        return result


def list_versions(kind: str) -> list[dict]:
    """특정 kind의 모든 버전 메타데이터 반환 (body는 길이만, 본문 제외).

    버전 최신순 정렬.
    """
    _validate_kind(kind)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, version, is_active, created_at, note, length(body) AS body_length "
            "FROM prompts WHERE kind = ? ORDER BY version DESC",
            (kind,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_version(kind: str, version: int) -> dict | None:
    """특정 버전의 전체 데이터 (본문 포함) 반환."""
    _validate_kind(kind)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, kind, version, body, is_active, created_at, note "
            "FROM prompts WHERE kind = ? AND version = ?",
            (kind, version),
        ).fetchone()
        return dict(row) if row else None


def save_new_version(kind: str, body: str, note: str | None = None) -> dict:
    """새 버전 생성. version은 max+1 자동 할당. is_active=0 (활성화는 별도 호출).

    반환: 신규 row의 {id, version}.
    """
    _validate_kind(kind)
    if not body or not body.strip():
        raise ValueError("body must not be empty")

    with db.connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_v FROM prompts WHERE kind = ?",
            (kind,),
        ).fetchone()
        new_version = row["max_v"] + 1
        now = datetime.utcnow().isoformat()

        cursor = conn.execute(
            "INSERT INTO prompts (kind, version, body, is_active, created_at, note) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (kind, new_version, body, now, note),
        )
        conn.commit()
        logger.info("prompt saved: kind=%s version=%d id=%d", kind, new_version, cursor.lastrowid)
        return {"id": cursor.lastrowid, "version": new_version}


def activate(kind: str, version: int) -> None:
    """지정 버전을 활성으로 전환. 같은 kind의 다른 버전들은 자동 비활성.

    트랜잭션으로 atomic 보장.
    """
    _validate_kind(kind)
    with db.connection() as conn:
        target = conn.execute(
            "SELECT id FROM prompts WHERE kind = ? AND version = ?",
            (kind, version),
        ).fetchone()
        if not target:
            raise ValueError(f"prompt not found: kind={kind} version={version}")

        try:
            conn.execute("BEGIN")
            conn.execute(
                "UPDATE prompts SET is_active = 0 WHERE kind = ? AND is_active = 1",
                (kind,),
            )
            conn.execute(
                "UPDATE prompts SET is_active = 1 WHERE kind = ? AND version = ?",
                (kind, version),
            )
            conn.commit()
            logger.info("prompt activated: kind=%s version=%d", kind, version)
        except Exception:
            conn.rollback()
            raise


def delete_version(kind: str, version: int) -> None:
    """버전 삭제. 활성 버전은 삭제 거부 (먼저 다른 버전 활성화 필요)."""
    _validate_kind(kind)
    with db.connection() as conn:
        row = conn.execute(
            "SELECT is_active FROM prompts WHERE kind = ? AND version = ?",
            (kind, version),
        ).fetchone()
        if not row:
            raise ValueError(f"prompt not found: kind={kind} version={version}")
        if row["is_active"]:
            raise ValueError(
                f"cannot delete active version (kind={kind} version={version}) — "
                "activate another version first"
            )

        conn.execute(
            "DELETE FROM prompts WHERE kind = ? AND version = ?",
            (kind, version),
        )
        conn.commit()
        logger.info("prompt deleted: kind=%s version=%d", kind, version)


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r} (allowed: {VALID_KINDS})")
