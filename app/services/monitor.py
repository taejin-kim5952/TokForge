"""Step 8 — 비용/품질 모니터링 서비스.

각 요청이 파이프라인을 거치며 어떤 변화를 일으켰는지 SQLite 에 기록.
- 정제 변화 (Step 5)
- RAG hit + 압축률 (Step 3, 6)
- 모델 티어 (Step 7)
- 토큰·지연시간
- 캐시 hit (Step 2)
"""

import sqlite3
import time
from pathlib import Path

from app.config import MONITOR_DB_PATH


_DB_PATH = Path(__file__).parent.parent.parent / MONITOR_DB_PATH


class MonitorService:
    """요청별 지표 저장·집계."""

    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                original        TEXT,
                refined         TEXT,
                refined_changed BOOLEAN,
                rag_chunks      INTEGER,
                ctx_before      INTEGER,
                ctx_after       INTEGER,
                tier            TEXT,
                model           TEXT,
                prompt_toks     INTEGER,
                completion_toks INTEGER,
                total_toks      INTEGER,
                latency_ms      INTEGER,
                cache_hit       BOOLEAN,
                error           TEXT
            )
        """)

        # 단계별 시간·모델 컬럼 마이그레이션 (기존 DB 와 호환)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(requests)").fetchall()}
        new_cols = {
            "refine_ms":      "INTEGER",
            "cache_ms":       "INTEGER",
            "rag_ms":         "INTEGER",
            "compress_ms":    "INTEGER",
            "template_ms":    "INTEGER",
            "route_ms":       "INTEGER",
            "refine_model":   "TEXT",
            "compress_model": "TEXT",
            "compare_id":     "TEXT",
            "mode":           "TEXT",
        }
        for col, typ in new_cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE requests ADD COLUMN {col} {typ}")

        conn.commit()
        conn.close()

    def record(self, data: dict) -> None:
        """한 요청의 지표를 한 row 로 저장."""
        try:
            conn = sqlite3.connect(_DB_PATH)
            conn.execute(
                """
                INSERT INTO requests (
                    original, refined, refined_changed,
                    rag_chunks, ctx_before, ctx_after,
                    tier, model,
                    prompt_toks, completion_toks, total_toks,
                    latency_ms, cache_hit, error,
                    refine_ms, cache_ms, rag_ms, compress_ms, template_ms, route_ms,
                    refine_model, compress_model,
                    compare_id, mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("original"),
                    data.get("refined"),
                    data.get("refined_changed", False),
                    data.get("rag_chunks", 0),
                    data.get("ctx_before", 0),
                    data.get("ctx_after", 0),
                    data.get("tier"),
                    data.get("model"),
                    data.get("prompt_toks"),
                    data.get("completion_toks"),
                    data.get("total_toks"),
                    data.get("latency_ms"),
                    data.get("cache_hit", False),
                    data.get("error"),
                    data.get("refine_ms"),
                    data.get("cache_ms"),
                    data.get("rag_ms"),
                    data.get("compress_ms"),
                    data.get("template_ms"),
                    data.get("route_ms"),
                    data.get("refine_model"),
                    data.get("compress_model"),
                    data.get("compare_id"),
                    data.get("mode"),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            # 모니터 실패가 실제 응답을 막으면 안 됨
            print(f"[MONITOR ERROR] record failed: {e}", flush=True)

    def recent(self, limit: int = 20) -> list[dict]:
        """최근 요청 N건 반환."""
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM requests ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """집계 통계."""
        conn = sqlite3.connect(_DB_PATH)

        total = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        if total == 0:
            conn.close()
            return {"total_requests": 0}

        cache_hits = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE cache_hit = 1"
        ).fetchone()[0]

        refined_count = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE refined_changed = 1"
        ).fetchone()[0]

        avg_latency = conn.execute(
            "SELECT AVG(latency_ms) FROM requests WHERE latency_ms IS NOT NULL"
        ).fetchone()[0]

        avg_compression = conn.execute(
            """SELECT AVG(CAST(ctx_after AS REAL) / ctx_before)
               FROM requests
               WHERE ctx_before > 0 AND ctx_after > 0"""
        ).fetchone()[0]

        avg_tokens = conn.execute(
            "SELECT AVG(total_toks) FROM requests WHERE total_toks IS NOT NULL"
        ).fetchone()[0]

        tier_dist = conn.execute(
            """SELECT tier, COUNT(*) as n
               FROM requests
               WHERE tier IS NOT NULL
               GROUP BY tier"""
        ).fetchall()

        model_dist = conn.execute(
            """SELECT model, COUNT(*) as n
               FROM requests
               WHERE model IS NOT NULL
               GROUP BY model"""
        ).fetchall()

        errors = conn.execute(
            "SELECT COUNT(*) FROM requests WHERE error IS NOT NULL"
        ).fetchone()[0]

        # 단계별 평균 시간 (NULL 은 제외)
        stage_cols = ["refine_ms", "cache_ms", "rag_ms", "compress_ms", "template_ms", "route_ms"]
        stage_avg = {}
        for col in stage_cols:
            avg = conn.execute(
                f"SELECT AVG({col}) FROM requests WHERE {col} IS NOT NULL"
            ).fetchone()[0]
            stage_avg[f"avg_{col}"] = round(avg, 1) if avg else None

        conn.close()

        return {
            "total_requests": total,
            "cache_hits": cache_hits,
            "cache_hit_rate": round(cache_hits / total, 3),
            "refined_count": refined_count,
            "refined_rate": round(refined_count / total, 3),
            "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
            "avg_compression_ratio": (
                round(avg_compression, 3) if avg_compression else None
            ),
            "avg_total_tokens": round(avg_tokens, 1) if avg_tokens else None,
            "tier_distribution": {t: n for t, n in tier_dist},
            "model_distribution": {m: n for m, n in model_dist},
            "error_count": errors,
            **stage_avg,
        }


# ────────────── 싱글톤 ──────────────
_service: MonitorService | None = None


def get_monitor() -> MonitorService:
    """전역 MonitorService 싱글톤."""
    global _service
    if _service is None:
        _service = MonitorService()
    return _service


def now_ms() -> int:
    """현재 시각 (ms). 지연시간 측정용 헬퍼."""
    return int(time.time() * 1000)
