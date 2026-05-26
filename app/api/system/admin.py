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

import json
import logging

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
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
from app import db
from app.services import conversation_repo, prompt_repo
from app.services.monitor import get_monitor
from app.services.rag import get_rag, ingest_text_document, invalidate_rag
from app.services.rag_document_extract import extract_text_from_document
from app.services import project_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

TAG_STATUS = "admin-status"
TAG_PROMPTS = "admin-prompts"
TAG_CONVERSATIONS = "admin-conversations"
TAG_TRAINING = "admin-training"
TAG_PROJECTS = "admin-projects"
TAG_RAG = "admin-rag"


@router.get("/status", tags=[TAG_STATUS])
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


@router.get("/prompts", tags=[TAG_PROMPTS])
def list_prompts_summary() -> dict:
    """4종 kind별 활성 버전 + 총 버전 수 요약."""
    return {"kinds": prompt_repo.summary()}


@router.get("/prompts/{kind}", tags=[TAG_PROMPTS])
def list_prompt_versions(kind: str) -> dict:
    """특정 kind의 버전 목록 (본문은 길이만)."""
    try:
        versions = prompt_repo.list_versions(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"kind": kind, "versions": versions}


@router.get("/prompts/{kind}/{version}", tags=[TAG_PROMPTS])
def get_prompt_version(kind: str, version: int) -> dict:
    """특정 버전 전체 (본문 포함)."""
    try:
        row = prompt_repo.get_version(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not row:
        raise HTTPException(status_code=404, detail=f"prompt not found: {kind} v{version}")
    return row


@router.post("/prompts/{kind}", status_code=201, tags=[TAG_PROMPTS])
def create_prompt_version(kind: str, payload: CreatePromptRequest) -> dict:
    """새 버전 생성 (version 자동 할당, is_active=0). 별도 activate 호출 필요."""
    try:
        result = prompt_repo.save_new_version(kind, payload.body, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/prompts/{kind}/{version}/activate", tags=[TAG_PROMPTS])
def activate_prompt_version(kind: str, version: int) -> dict:
    """지정 버전을 활성으로 전환."""
    try:
        prompt_repo.activate(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/conversations", tags=[TAG_CONVERSATIONS])
def list_all_conversations(
    project_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """전체 대화 목록 + 별점 요약 (admin 전용)."""
    with db.connection() as conn:
        query = """
            SELECT
                c.id, c.title, c.project_id,
                c.owner_user_id,
                c.created_at, c.updated_at,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
                (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.rating IS NOT NULL) AS rated_count,
                (SELECT AVG(m.rating * 1.0) FROM messages m WHERE m.conversation_id = c.id AND m.rating IS NOT NULL) AS avg_rating
            FROM conversations c
        """
        params: list[object] = []
        if project_id is not None:
            query += " WHERE c.project_id = ?"
            params.append(project_id)
        query += " ORDER BY c.updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        total_row = conn.execute(
            "SELECT COUNT(*) AS count FROM conversations" +
            (" WHERE project_id = ?" if project_id is not None else ""),
            ([project_id] if project_id is not None else []),
        ).fetchone()
        return {
            "total": total_row["count"],
            "conversations": [dict(r) for r in rows],
        }


@router.get("/conversations/{conversation_id}/messages", tags=[TAG_CONVERSATIONS])
def get_conversation_messages(conversation_id: str) -> dict:
    """특정 대화의 메시지 목록 반환 (admin 전용)."""
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, rating, seq, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY seq
            """,
            [conversation_id],
        ).fetchall()
        return {"messages": [dict(r) for r in rows]}


@router.get("/training/export", tags=[TAG_TRAINING])
def export_training_data(
    min_rating: int = 4,
    project_id: int | None = None,
    limit: int | None = None,
) -> PlainTextResponse:
    try:
        pairs = conversation_repo.export_training_pairs(
            min_rating=min_rating, project_id=project_id, limit=limit,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    lines = [json.dumps(row, ensure_ascii=False) for row in pairs]
    return PlainTextResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        media_type="text/plain; charset=utf-8",
    )


@router.delete("/prompts/{kind}/{version}", tags=[TAG_PROMPTS])
def delete_prompt_version(kind: str, version: int) -> dict:
    """버전 삭제 — 활성 버전은 삭제 거부."""
    try:
        prompt_repo.delete_version(kind, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ─────────────────────────────────────────────
# Admin 공통: 전체 프로젝트 목록
# ─────────────────────────────────────────────

@router.get("/projects", tags=[TAG_PROJECTS])
def list_all_projects() -> dict:
    """전체 사용자의 모든 프로젝트 목록 (admin 전용)."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description, owner_user_id, created_at "
            "FROM projects ORDER BY id",
        ).fetchall()
        return {"projects": [dict(r) for r in rows]}


# ─────────────────────────────────────────────
# Admin RAG 관리 (프로젝트별)
# ─────────────────────────────────────────────

@router.get("/rag/sources", tags=[TAG_RAG])
def rag_list_sources(project_id: int | None = None) -> dict:
    """프로젝트(또는 글로벌)의 업로드된 문서 목록 반환."""
    sources = get_rag(project_id).list_sources()
    stats = get_rag(project_id).stats()
    return {"project_id": project_id, "sources": sources, "stats": stats}


@router.post("/rag/upload", tags=[TAG_RAG])
async def rag_upload(
    file: UploadFile = File(...),
    project_id: int | None = None,
) -> dict:
    """문서 파일을 지정 프로젝트 RAG 인덱스에 추가 (PDF/Office 포함)."""
    raw = await file.read()
    try:
        text = extract_text_from_document(file.filename, raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    chunk_count = ingest_text_document(project_id, file.filename, text)
    return {
        "ok": True,
        "project_id": project_id,
        "filename": file.filename,
        "size_bytes": len(raw),
        "chunks_created": chunk_count,
    }


@router.delete("/rag/sources", tags=[TAG_RAG])
def rag_delete_source(source: str, project_id: int | None = None) -> dict:
    """특정 문서의 모든 청크를 삭제 후 인덱스 재구성."""
    deleted = get_rag(project_id).delete_source(source)
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"소스를 찾을 수 없습니다: {source}")
    invalidate_rag(project_id)
    return {"ok": True, "project_id": project_id, "source": source, "deleted_chunks": deleted}


@router.get("/rag/search", tags=[TAG_RAG])
def rag_search(q: str, project_id: int | None = None, k: int = 5) -> dict:
    """검색 테스트 — 관리자 확인용."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="쿼리(q)가 비어있습니다")
    results = get_rag(project_id).search(q, k=k)
    return {"project_id": project_id, "query": q, "count": len(results), "results": results}
