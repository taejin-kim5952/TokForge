"""헬스체크 + 루트 엔드포인트."""

from fastapi import APIRouter
import httpx

from app.config import OLLAMA_BASE_URL

router = APIRouter()

@router.get("/")
def root():
    """루트 — 서버 식별용."""
    return {"name": "TokForge", "status": "running"}

@router.get("/health")
async def health():
    """서버 + Ollama 연결 상태."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False
    return {
        "status": "ok",
        "ollama": "connected" if ollama_ok else "disconnected",
    }
