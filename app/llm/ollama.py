"""Ollama LLM 호출 모듈.

request["model"] 이 이미 지정돼 있으면 그대로 사용 (Step 7 라우팅 호환).
없으면 DEFAULT_MODEL 로 폴백.
"""

import httpx

from app.config import OLLAMA_CHAT_URL, DEFAULT_MODEL


def _ensure_model(request: dict) -> None:
    """request 에 model 이 없으면 DEFAULT_MODEL 설정."""
    if not request.get("model"):
        request["model"] = DEFAULT_MODEL


async def chat_completion(request: dict) -> dict:
    """비스트리밍 채팅 호출. 응답 JSON 그대로 반환."""
    _ensure_model(request)
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(OLLAMA_CHAT_URL, json=request)
        return response.json()


async def chat_completion_stream(request: dict):
    """스트리밍 채팅 호출. SSE 라인을 하나씩 yield."""
    _ensure_model(request)
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", OLLAMA_CHAT_URL, json=request) as response:
            async for line in response.aiter_lines():
                if line:
                    yield f"{line}\n\n"
