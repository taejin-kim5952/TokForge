"""Step 5 — 질문 정제 디버그 엔드포인트.

실제 채팅 호출 없이 정제 결과만 확인.

사용 예:
    GET /refiner/refine?q=fastapi 로터 추가법
"""

from fastapi import APIRouter, Query

from app.services.refiner import get_refiner

router = APIRouter()


@router.get("/refiner/refine")
async def refine(
    q: str = Query(..., description="정제할 사용자 질문"),
) -> dict:
    """질문 정제 결과 반환 — original/refined 비교."""
    original = q
    refined = await get_refiner().refine(q)
    return {
        "original": original,
        "refined": refined,
        "changed": original != refined,
    }
