"""PostgreSQL 공통 접근 모듈.

모든 repository가 `DATABASE_URL`(postgresql://...) 로 연결합니다.
SQLite(`storage/monitor.db`)는 사용하지 않습니다.

환경변수: DATABASE_URL
  - psycopg2용: postgresql://user:pass@host:5432/dbname
  - postgresql+asyncpg:// 는 자동으로 postgresql:// 로 정규화
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv()


def parse_datetime(value: Any) -> datetime:
    """Postgres TIMESTAMPTZ/datetime 또는 ISO 문자열 → naive UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value)
    else:
        raise TypeError(f"expected str or datetime, got {type(value)!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 필요합니다 (PostgreSQL). "
            "예: postgresql://user:pass@localhost:5432/tokforge"
        )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url.split("://", 1)[1]
    return url


def _to_pg_sql(sql: str) -> str:
    """SQLite `?` → psycopg2 `%s`. LIKE 등 리터럴 `%` 는 `%%` 로 이스케이프."""
    sql = sql.replace("?", "%s")
    sentinel = "\x00PGPH\x00"
    parts = sql.split("%s")
    escaped = [p.replace("%", "%%") for p in parts]
    return sentinel.join(escaped).replace(sentinel, "%s")


class _ExecuteResult:
    """sqlite3.Connection.execute() 와 유사한 결과 래퍼."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        """INSERT ... RETURNING id 직후 fetchone() 한 경우에만 유효."""
        return None


class PgConnection:
    """psycopg2 연결 + sqlite3 호환 execute()."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple | list = ()) -> _ExecuteResult:
        import psycopg2.extras

        pg_sql = _to_pg_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_sql, tuple(params) if params else None)
        return _ExecuteResult(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()


def get_connection() -> PgConnection:
    """수동 제어용 연결. 호출자가 close() 책임."""
    import psycopg2

    raw = psycopg2.connect(database_url())
    return PgConnection(raw)


@contextmanager
def connection() -> Iterator[PgConnection]:
    """with 문 안에서 자동 commit / rollback / close."""
    import psycopg2

    raw = psycopg2.connect(database_url())
    wrapper = PgConnection(raw)
    try:
        yield wrapper
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def init_all_schemas() -> None:
    """앱 기동 시 모든 Postgres 테이블 생성 (의존 순서)."""
    from app.api.system import auth
    from app.services import (
        conversation_repo,
        document_repo,
        ppt_template_repo,
        project_features_repo,
        project_repo,
        project_requirements_repo,
        prompt_repo,
        rag_file_repo,
        session_repo,
        user_repo,
    )

    user_repo.init_schema()
    session_repo.init_schema()
    project_repo.init_schema()
    auth.init_schema()
    conversation_repo.init_schema()
    document_repo.init_schema()
    ppt_template_repo.init_schema()
    rag_file_repo.init_schema()
    project_requirements_repo.init_schema()
    project_features_repo.init_schema()
    prompt_repo.init_schema()
