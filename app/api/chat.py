"""채팅 엔드포인트 — Continue.dev 가 호출하는 메인 API."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.llm import ollama
from app.services.cache import get_cache

router = APIRouter()


def _last_user_message(request: dict) -> str | None:
    """messages 배열에서 마지막 user 메시지 추출."""
    for msg in reversed(request.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content")
    return None


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """
    OpenAI 호환 채팅 엔드포인트.
    2단계 — 의미 캐시 적용 (비스트리밍만).
    """
    # 스트리밍은 캐시 우회 (그대로 Ollama 호출)
    if request.get("stream"):
        return StreamingResponse(
            ollama.chat_completion_stream(request),
            media_type="text/event-stream",
        )

    # 비스트리밍 — 캐시 확인
    query = _last_user_message(request)
    cache = get_cache()

    if query:
        cached = cache.lookup(query)
        if cached is not None:
            return cached

    # 캐시 미스 → Ollama 호출
    response = await ollama.chat_completion(request)

    # 결과 캐시 저장
    if query:
        cache.save(query, response)

    return response
