"""모델 정보 엔드포인트."""

from fastapi import APIRouter
import httpx

from app.config import OLLAMA_BASE_URL, DEFAULT_MODEL

router = APIRouter()


@router.get("/v1/models")
async def list_models():
    """OpenAI 호환 모델 목록 (Continue.dev 자동 감지용)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = r.json()
        return {
            "object": "list",
            "data": [
                {"id": m["name"], "object": "model", "owned_by": "ollama"}
                for m in data.get("models", [])
            ],
        }
    except Exception:
        return {"object": "list", "data": []}


@router.get("/v1/models/current")
async def current_model():
    """TokForge 가 사용 중인 기본 모델."""
    return {
        "default_model": DEFAULT_MODEL,
        "ollama_url": OLLAMA_BASE_URL,
    }
