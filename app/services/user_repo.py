"""사용자 저장소 — Google OAuth 기반 사용자 관리.

`google_sub` (Google의 안정 식별자) 를 join key로 사용. email은 변경될 수 있어 식별자로 부적합.
"""

import logging
from datetime import datetime

from app import db

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """앱 기동 시 1회. 테이블 없으면 생성."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                google_sub      TEXT    NOT NULL UNIQUE,
                email           TEXT    NOT NULL,
                email_verified  INTEGER NOT NULL DEFAULT 0,
                name            TEXT,
                picture_url     TEXT,
                created_at      TEXT    NOT NULL,
                last_login_at   TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )
        conn.commit()


def get_by_id(user_id: int) -> dict | None:
    """user.id로 조회. 없으면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, google_sub, email, email_verified, name, picture_url, "
            "created_at, last_login_at "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_by_google_sub(google_sub: str) -> dict | None:
    """Google sub로 조회. 없으면 None."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, google_sub, email, email_verified, name, picture_url, "
            "created_at, last_login_at "
            "FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()
        return dict(row) if row else None


def upsert_from_google(
    google_sub: str,
    email: str,
    email_verified: bool,
    name: str | None,
    picture_url: str | None,
) -> dict:
    """Google 인증 결과로 user upsert. 신규면 생성, 기존이면 last_login_at + 메타 갱신.

    반환: 최신 user dict.
    """
    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE users SET email = ?, email_verified = ?, name = ?, "
                "picture_url = ?, last_login_at = ? "
                "WHERE google_sub = ?",
                (email, int(email_verified), name, picture_url, now, google_sub),
            )
            user_id = existing["id"]
            logger.info("user updated: id=%d google_sub=%s", user_id, google_sub)
        else:
            cursor = conn.execute(
                "INSERT INTO users (google_sub, email, email_verified, name, "
                "picture_url, created_at, last_login_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (google_sub, email, int(email_verified), name, picture_url, now, now),
            )
            user_id = cursor.lastrowid
            logger.info("user created: id=%d email=%s", user_id, email)

        conn.commit()

    result = get_by_id(user_id)
    if result is None:
        raise RuntimeError(f"failed to load user after upsert: id={user_id}")
    return result
