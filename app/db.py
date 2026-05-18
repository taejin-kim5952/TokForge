"""SQLite 공통 접근 모듈.

모든 repository가 이 모듈을 통해 connection을 획득.
향후 변경(WAL 모드, FK 활성화, connection pool, RDB 교체)을
한 곳에서 처리하기 위한 일원화 지점.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import MONITOR_DB_PATH

_DB_PATH = Path(__file__).parent.parent / MONITOR_DB_PATH


def get_connection() -> sqlite3.Connection:
    """Row factory + FK enforcement 적용된 새 연결 반환. 호출자가 close() 책임.

    수동 제어가 필요한 경우에만 사용. 대부분은 connection() context manager 사용 권장.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """with 문 안에서 자동 close.

    사용 예:
        with db.connection() as conn:
            row = conn.execute("SELECT ...").fetchone()
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
