"""Step 8 — 모니터링 조회 엔드포인트.

기록된 요청 지표를 조회·집계.
"""

from fastapi import APIRouter, Query

from app.services.monitor import get_monitor

router = APIRouter()


@router.get("/monitor/recent")
def recent(
    limit: int = Query(20, ge=1, le=200, description="조회할 최근 요청 수"),
) -> dict:
    """최근 요청 N건의 단계별 변화 상세."""
    rows = get_monitor().recent(limit)
    return {"count": len(rows), "requests": rows}


@router.get("/monitor/stats")
def stats() -> dict:
    """집계 통계 — 캐시 hit율, 평균 압축률, 모델 분포 등."""
    return get_monitor().stats()
