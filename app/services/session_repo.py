"""세션 저장소 — 불투명 세션 ID 발급/검증/소멸.

쿠키 (`tf_session`) 에 담긴 세션 ID로 user를 조회. 매 요청마다 last_seen_at 갱신,
expires_at 도래시 슬라이딩 윈도우로 자동 연장. 로그아웃 = 행 삭제.
"""

import logging
import secrets
from datetime import datetime, timedelta

from app import db
from app.config import SESSION_TTL_DAYS, SESSION_REFRESH_THRESHOLD_DAYS

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """앱 기동 시 1회."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id            TEXT    PRIMARY KEY,
                user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at    TEXT    NOT NULL,
                expires_at    TEXT    NOT NULL,
                last_seen_at  TEXT    NOT NULL,
                user_agent    TEXT,
                ip            TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")
        conn.commit()


def create(user_id: int, user_agent: str | None = None, ip: str | None = None) -> str:
    """새 세션 생성. 반환: 세션 ID (쿠키에 넣을 값)."""
    session_id = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=SESSION_TTL_DAYS)
    now_iso, expires_iso = now.isoformat(), expires.isoformat()

    with db.connection() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at, "
            "last_seen_at, user_agent, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, user_id, now_iso, expires_iso, now_iso, user_agent, ip),
        )
        conn.commit()
    logger.info("session created: user_id=%d", user_id)
    return session_id


def touch_and_get(session_id: str) -> dict | None:
    """세션 검증 + last_seen 갱신 + (필요시) expires_at 연장.

    만료된 세션은 None 반환. 정상이면 dict 반환 (id, user_id, expires_at, ...).
    """
    if not session_id:
        return None

    now = datetime.utcnow()
    now_iso = now.isoformat()

    with db.connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, created_at, expires_at, last_seen_at "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= now:
            # 만료 — 자동 정리
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
            return None

        # 슬라이딩 윈도우 — 남은 시간이 임계값 이하면 연장
        if expires_at - now < timedelta(days=SESSION_REFRESH_THRESHOLD_DAYS):
            new_expires = (now + timedelta(days=SESSION_TTL_DAYS)).isoformat()
            conn.execute(
                "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                (now_iso, new_expires, session_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                (now_iso, session_id),
            )
        conn.commit()
        return dict(row)


def delete(session_id: str) -> None:
    """로그아웃 — 세션 행 삭제. 멱등 (없어도 OK)."""
    if not session_id:
        return
    with db.connection() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    logger.info("session deleted: id=%s...", session_id[:8])


def delete_expired() -> int:
    """만료 세션 일괄 정리 — 운영용 (현재 자동 호출 안 함). 삭제 건수 반환."""
    now_iso = datetime.utcnow().isoformat()
    with db.connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso,))
        conn.commit()
        return cursor.rowcount
