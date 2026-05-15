"""Step 7 — 모델 라우팅 디버그 엔드포인트.

질문에 대한 분류 결과(tier) 와 선택된 모델을 반환.
실제 채팅 호출 없이 라우팅 동작만 확인.
"""

from fastapi import APIRouter, Query

from app.services.router import get_router

router = APIRouter()


@router.get("/router/classify")
async def classify(
    q: str = Query(..., description="복잡도를 분류할 사용자 질문"),
) -> dict:
    """질문 분류 결과 + 선택된 모델 반환."""
    tier, model = await get_router().route(q)
    return {
        "query": q,
        "tier": tier,
        "model": model,
    }
