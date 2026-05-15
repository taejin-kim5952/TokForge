"""Step 4 — 프롬프트 템플릿 미리보기 엔드포인트.

디버깅·개발 편의용. 실제 LLM 호출 없이 템플릿 적용 결과만 확인.

사용 예:
    GET /prompt/preview?q=fastapi 라우터 추가법
    GET /prompt/preview?q=hello&use_rag=false
"""

from fastapi import APIRouter, Query

from app.services.prompt import get_template_service
from app.services.rag import get_rag

router = APIRouter()


@router.get("/prompt/preview")
def preview(
    q: str = Query(..., description="템플릿을 적용할 사용자 질문"),
    use_rag: bool = Query(True, description="RAG 검색 결과를 포함할지 여부"),
    k: int = Query(3, ge=1, le=10, description="RAG top-k"),
) -> dict:
    """질문 + (선택적 RAG) 에 템플릿을 적용한 최종 messages 배열을 반환."""
    rag_context: str | None = None
    rag_chunks: list = []

    if use_rag:
        rag_chunks = get_rag().search(q, k=k)
        if rag_chunks:
            rag_context = "\n\n".join(c["content"] for c in rag_chunks)

    messages = get_template_service().preview(q, rag_context)

    return {
        "query": q,
        "use_rag": use_rag,
        "rag_chunks_count": len(rag_chunks),
        "messages": messages,
    }
