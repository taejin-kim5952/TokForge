"""관리자 페이지용 — 시스템 상태 조회.

운영자가 한눈에 보고 싶은 정보:
- Ollama 연결 상태 + 사용 가능한 모델 목록
- TokForge 가 사용 중인 모델들 (Refiner / Compressor / Router / Default)
- 단계별 활성화 상태
- monitor 집계 통계 (단계별 평균 시간 포함)
"""

import httpx
from fastapi import APIRouter

from app.config import (
    COMPRESSOR_MODEL,
    DEFAULT_MODEL,
    ENABLE_CONTEXT_COMPRESSION,
    ENABLE_MODEL_ROUTING,
    ENABLE_MONITORING,
    ENABLE_PROMPT_TEMPLATE,
    ENABLE_QUERY_REFINEMENT,
    OLLAMA_BASE_URL,
    REFINER_MODEL,
    ROUTER_MODEL,
)
from app.services.monitor import get_monitor

router = APIRouter(prefix="/admin")


@router.get("/status")
async def status() -> dict:
    """시스템 상태 + 활성 설정 + 모니터 통계 한 번에 반환."""
    # Ollama 연결 시도
    ollama_ok = False
    ollama_models: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = response.json()
            ollama_models = [m.get("name", "") for m in data.get("models", [])]
            ollama_ok = True
    except Exception as e:
        print(f"[ADMIN] Ollama check failed: {e}", flush=True)

    return {
        "ollama": {
            "url": OLLAMA_BASE_URL,
            "connected": ollama_ok,
            "models": ollama_models,
        },
        "models_in_use": {
            "refiner":    REFINER_MODEL,
            "compressor": COMPRESSOR_MODEL,
            "router":     ROUTER_MODEL,
            "default":    DEFAULT_MODEL,
        },
        "stages_enabled": {
            "refine":     ENABLE_QUERY_REFINEMENT,
            "compress":   ENABLE_CONTEXT_COMPRESSION,
            "template":   ENABLE_PROMPT_TEMPLATE,
            "route":      ENABLE_MODEL_ROUTING,
            "monitoring": ENABLE_MONITORING,
        },
        "stats": get_monitor().stats(),
    }
