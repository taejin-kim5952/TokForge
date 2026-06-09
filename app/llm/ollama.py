"""Ollama LLM 호출 모듈.

request["model"] 이 이미 지정돼 있으면 그대로 사용 (Step 7 라우팅 호환).
없으면 DEFAULT_MODEL 로 폴백.
"""

import logging
import httpx

logger = logging.getLogger(__name__)

from app.config import (
    OLLAMA_CHAT_URL, 
    DEFAULT_MODEL,
    AZURE_OPENAI_MODEL,
    AZURE_OPENAI_BASE_URL,
    AZURE_OPENAI_API_KEY,
)

def _ensure_model(request: dict) -> None:
    """request 에 model 이 없으면 DEFAULT_MODEL 설정."""
    if not request.get("model"):
        request["model"] = DEFAULT_MODEL


def _is_azure_model(model: str) -> bool:
    """model 이 Azure OpenAI 모델인지 확인."""
    if not AZURE_OPENAI_MODEL or not AZURE_OPENAI_BASE_URL or not AZURE_OPENAI_API_KEY:
        return False
    return model == AZURE_OPENAI_MODEL


def _convert_images_to_vision_format(request: dict) -> None:
    """messages 내 images 필드를 OpenAI vision content 배열로 변환.

    프론트엔드가 Ollama 네이티브 포맷(images: [base64, ...])으로 보내는 경우,
    /v1/chat/completions 엔드포인트가 이해하는 OpenAI vision 포맷으로 변환한다.

    변환 전:
        {"role": "user", "content": "분석해줘", "images": ["base64..."]}
    변환 후:
        {"role": "user", "content": [
            {"type": "text", "text": "분석해줘"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
        ]}
    """
    for msg in request.get("messages", []):
        images = msg.pop("images", None)
        if not images:
            continue
        text = msg.get("content", "")
        content: list = []
        if text:
            content.append({"type": "text", "text": text})
        for b64 in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        msg["content"] = content


async def chat_completion(request: dict) -> dict:
    """비스트리밍 채팅 호출. 응답 JSON 그대로 반환."""
    _ensure_model(request)
    _convert_images_to_vision_format(request)
    logger.info("ollama start #1")
    logger.info(f"ollama mode : {request.get('model')} ")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            if _is_azure_model(request.get("model", "")):
                logger.info("ollama start #1_1")
                response = await client.post(
                    AZURE_OPENAI_BASE_URL,
                    json=request,
                    headers={"api-key": AZURE_OPENAI_API_KEY},
                )
            else:
                response = await client.post(OLLAMA_CHAT_URL, json=request)
    except httpx.RequestError as e:
        raise RuntimeError(f"LLM 서버 연결 실패: {e}") from e
    logger.info("ollama start #2")
    if response.status_code >= 400:
        body = response.text[:500]
        raise RuntimeError(f"LLM HTTP {response.status_code}: {body}")

    try:
        return response.json()
    except ValueError as e:
        raise RuntimeError("LLM 응답이 JSON이 아님") from e


async def chat_completion_stream(request: dict):
    """스트리밍 채팅 호출. SSE 라인을 하나씩 yield."""
    _ensure_model(request)
    _convert_images_to_vision_format(request)
    async with httpx.AsyncClient(timeout=300.0) as client:
        if _is_azure_model(request.get("model", "")):
            async with client.stream(
                "POST",
                AZURE_OPENAI_BASE_URL,
                json=request,
                headers={"api-key": AZURE_OPENAI_API_KEY},
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
        else:
            async with client.stream("POST", OLLAMA_CHAT_URL, json=request) as response:
                async for line in response.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
