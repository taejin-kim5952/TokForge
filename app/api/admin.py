"""관리자 페이지용 — 시스템 상태 조회 + 프롬프트 관리.

운영자가 한눈에 보고 싶은 정보:
- Ollama 연결 상태 + 사용 가능한 모델 목록
- TokForge 가 사용 중인 모델들 (Refiner / Compressor / Router / Default)
- 단계별 활성화 상태
- monitor 집계 통계 (단계별 평균 시간 포함)

프롬프트 관리:
- 4종 프롬프트 (refiner/classifier/compressor/system) 의 버전별 CRUD
- 활성 버전 전환 (재기동 없이 즉시 반영)
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
from app.services import prompt_repo
from app.services.monitor import get_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")


@router.get("/status")
async def status() -> dict:
    """시스템 상태 + 활성 설정 + 모니터 통계 한 번에 반환."""
    ollama_ok = False
    ollama_models: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = response.json()
            ollama_models = [m.get("name", "") for m in data.get("models", [])]
            ollama_ok = True
    except Exception:
        logger.exception("ollama check failed")

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


# ────────────── Prompts ──────────────

class CreatePromptRequest(BaseModel):
    body: str = Field(..., min_length=1, description="새 프롬프트 본문")
    note: str | None = Field(None, description="선택 — 변경 사유 메모")


@router.get("/prompts")
def list_prompts_summary() -> dict:
    """4종 kind별 활성 버전 + 총 버전 수 요약."""
    return {"kinds": prompt_repo.summary()}


@router.get("/prompts/{kind}")
def list_prompt_versions(kind: str) -> dict:
    """특정 kind의 버전 목록 (본문은 길이만)."""
    try:
        versions = prompt_repo.list_versions(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"kind": kind, "versions": versions}


@router.get("/prompts/{kind}/{version}")
def get_prompt_version(kind: str, version: int) -> dict:
    """특정 버전 전체 (본문 포함)."""
    try:
        row = prompt_repo.get_version(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail=f"prompt not found: {kind} v{version}")
    return row


@router.post("/prompts/{kind}", status_code=201)
def create_prompt_version(kind: str, payload: CreatePromptRequest) -> dict:
    """새 버전 생성 (version 자동 할당, is_active=0). 별도 activate 호출 필요."""
    try:
        result = prompt_repo.save_new_version(kind, payload.body, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/prompts/{kind}/{version}/activate")
def activate_prompt_version(kind: str, version: int) -> dict:
    """지정 버전을 활성으로 전환."""
    try:
        prompt_repo.activate(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/prompts/{kind}/{version}")
def delete_prompt_version(kind: str, version: int) -> dict:
    """버전 삭제 — 활성 버전은 삭제 거부."""
    try:
        prompt_repo.delete_version(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}
