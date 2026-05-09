"""Ollama LLM 호출 모듈."""

import httpx

from app.config import OLLAMA_CHAT_URL, DEFAULT_MODEL

async def chat_completion(request: dict) -> dict:
    """비스트리밍 채팅 호출. 응답 JSON 그대로 반환."""
    request["model"] = DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(OLLAMA_CHAT_URL, json=request)
        return response.json()
    
async def chat_completion_stream(request: dict):
    """스트리밍 채팅 호출. SSE 라인을 하나씩 yield."""
    request["model"] = DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", OLLAMA_CHAT_URL, json=request) as response:
            async for line in response.aiter_lines():
                if line:
                    yield f"{line}\n\n"