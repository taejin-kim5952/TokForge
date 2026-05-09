"""캐시 통계 + 관리 엔드포인트."""

from fastapi import APIRouter

from app.services.cache import get_cache

router = APIRouter(prefix="/v1/cache", tags=["cache"])


@router.get("/stats")
def cache_stats():
    """캐시 통계 — 저장된 항목 수, 인덱스 크기, 임계값."""
    return get_cache().stats()
