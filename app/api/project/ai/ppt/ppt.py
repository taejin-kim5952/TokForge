"""PPT 생성 — 프롬프트 + 프로젝트 개요 + 업로드 문서(RAG) → .pptx 다운로드.

채팅 SSE가 아니라 1회 요청으로 처리한다:
  컨텍스트 수집 → LLM(비스트리밍, 큰 모델) → deck JSON 파싱 → pptx 빌드 → 파일 응답.
"""
import asyncio
import io
import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, OwnedProject
from app.config import OVERVIEW_ORGANIZER_MODEL
from app.llm import ollama
from app.services import document_repo, ppt_template_repo
from app.services.rag_context import format_rag_prompt_block, search_rag_context

from .builder import build_pptx
from .prompts import build_ppt_system_prompt, parse_deck_json

router = APIRouter(tags=["프로젝트 PPT 생성"])

logger = logging.getLogger(__name__)

PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


class PptRequest(BaseModel):
    prompt: str
    model: str | None = None
    use_context: bool = True  # 프로젝트 개요 + RAG 포함 여부
    template_id: int | None = None  # 미지정 시 프로젝트 활성 템플릿 사용


_OVERVIEW_FIELD_LABELS = {
    "purpose":      "목적",
    "background":   "배경",
    "scope":        "포함 범위",
    "out_of_scope": "제외 범위",
    "key_features": "핵심 기능",
    "stakeholders": "이해관계자",
    "tech_stack":   "기술 스택",
    "schedule":     "일정",
    "risks":        "리스크",
}


def _format_overview_summary(overview_doc: dict) -> str:
    if not overview_doc:
        return ""
    lines = []
    for key, label in _OVERVIEW_FIELD_LABELS.items():
        val = overview_doc.get(key)
        if val and str(val).strip():
            lines.append(f"- {label}: {val}")
    return "\n".join(lines)


def _build_system_prompt(
    overview_doc: dict, rag_context: str | None, template: dict | None = None
) -> str:
    system = build_ppt_system_prompt(template)
    ov_block = _format_overview_summary(overview_doc or {})
    if ov_block:
        system += f"\n\n참고 — 프로젝트 개요:\n{ov_block}"
    if rag_context:
        system += "\n\n" + format_rag_prompt_block(rag_context)
    return system


def _content_disposition(title: str) -> str:
    """한글 제목 안전 인코딩 (RFC 5987)."""
    safe = (title or "presentation").strip() or "presentation"
    return f"attachment; filename*=UTF-8''{quote(safe)}.pptx"


@router.post("/{project_id}/ai/ppt")
async def generate_ppt(
    project: OwnedProject,
    user: CurrentUser,
    payload: PptRequest,
):
    logger.info("generate_ppt start #1")
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    logger.info("generate_ppt start #2")
    overview_doc: dict = {}
    rag_text: str | None = None
    if payload.use_context:
        overview_doc = document_repo.get(project["id"], "overview") or {}
        try:
            _chunk_count, rag_context = await asyncio.to_thread(
                search_rag_context,
                prompt,
                project_id=project["id"],
            )
            rag_text = rag_context or None
        except Exception as e:
            logger.warning("ppt RAG skipped project_id=%s: %s", project["id"], e)
    logger.info("generate_ppt start #3")
    # 템플릿 결정: template_id 지정 시 해당 템플릿, 없으면 활성 템플릿 (둘 다 없으면 None=기본)
    if payload.template_id is not None:
        tpl = ppt_template_repo.get(project["id"], payload.template_id)
        if not tpl:
            raise HTTPException(404, "template not found")
    else:
        tpl = ppt_template_repo.get_active(project["id"])
    tpl_content = tpl["content"] if tpl else None

    system = _build_system_prompt(overview_doc, rag_text, tpl_content)
    ollama_request = {
        "model": payload.model or OVERVIEW_ORGANIZER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    logger.info(f"ollama_request: {ollama_request}")
    logger.info("generate_ppt start #4")
    try:
        response = await ollama.chat_completion(ollama_request)
        content = response["choices"][0]["message"]["content"] or ""
        logger.info(f"content: {content}")
    except (KeyError, IndexError, TypeError):
        raise HTTPException(500, "LLM 응답 형식 오류")
    except Exception as e:
        logger.exception("ppt LLM call failed")
        raise HTTPException(500, f"PPT 생성 실패: {e}")
    logger.info("generate_ppt start #5")
    try:
        deck = parse_deck_json(content, tpl_content)
    except ValueError as e:
        logger.warning("deck parse failed: %s | raw=%.500s", e, content)
        raise HTTPException(422, f"AI 응답을 슬라이드로 변환 실패: {e}")
    logger.info("generate_ppt start #6")
    pptx_bytes = build_pptx(deck, tpl_content, project_id=project["id"])

    return StreamingResponse(
        io.BytesIO(pptx_bytes),
        media_type=PPTX_MEDIA_TYPE,
        headers={"Content-Disposition": _content_disposition(deck["title"])},
    )
