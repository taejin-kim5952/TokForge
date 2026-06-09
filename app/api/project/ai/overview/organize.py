"""프로젝트 개요 — 대화 정리(organize) 엔드포인트.

현재 활성 대화의 메시지를 분석해 9개 폼 필드로 구조화된 마크다운 출력.
정리 결과는 assistant 메시지로 저장 (meta.type='organize') 하여 재사용 가능.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, OwnedProject
from app.config import OVERVIEW_ORGANIZER_MODEL
from app.llm import ollama
from app.services import conversation_repo, prompt_repo

from .prompts import OVERVIEW_ORGANIZER_PROMPT, parse_overview_sections

router = APIRouter(tags=["프로젝트 개요"])

logger = logging.getLogger(__name__)


class OrganizeRequest(BaseModel):
    conversation_id: str
    model: str | None = None


@router.post("/{project_id}/ai/overview/organize")
async def organize_overview(
    project: OwnedProject,
    user: CurrentUser,
    payload: OrganizeRequest,
) -> dict:
    """대화 → 6개 폼 필드 구조화 마크다운."""
    logger.info("organize start #1")
    # 1. 대화 소유권 + 프로젝트 매칭 검증
    conv = conversation_repo.get_owned(payload.conversation_id, user["id"])
    logger.info("organize start #2")
    if (
        not conv
        or conv.get("project_id") != project["id"]
        or conv.get("menu_key") != conversation_repo.MENU_OVERVIEW
    ):
        raise HTTPException(404, "conversation not found")
    logger.info("organize start #3")
    # 2. 메시지 필터 — organize 결과 메시지는 제외 (재정리 노이즈 방지)
    messages: list[dict] = []
    for m in conv.get("messages", []):
        meta = m.get("meta") or {}
        if meta.get("type") == "organize":
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        messages.append({"role": m["role"], "content": content})
    logger.info("organize start #4")
    if not messages:
        raise HTTPException(400, "no messages to organize")

    # 3. 시스템 프롬프트 (탭별 kind → 없으면 글로벌 overview_organizer → 코드 fallback)
    def _conv_scope_norm(value: object) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None
    logger.info("organize start #5")
    conv_scope = _conv_scope_norm(conv.get("scope"))
    org_kind = prompt_repo.overview_organizer_prompt_kind(conv_scope)
    system_prompt = (
        prompt_repo.get_active(org_kind, project_id=project["id"])
        or prompt_repo.get_active("overview_organizer", project_id=project["id"])
        or OVERVIEW_ORGANIZER_PROMPT
    )
    logger.info("organize start #6")
    # 4. LLM 호출 (비스트리밍, 큰 모델, 낮은 temperature)

    # AI 모델 세팅
    if payload.model != None:
        model = (payload.model or "").strip() or OVERVIEW_ORGANIZER_MODEL

    ollama_request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
            {"role": "user", "content": "위 대화를 위 규칙대로 9개 섹션의 마크다운으로 정리해줘."},
        ],
        "stream": False,
        "temperature": 0.3,
    }
    try:
        logger.info("organize start #7")
        response = await ollama.chat_completion(ollama_request)
        logger.info("organize start #8")
        content = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(500, "organizer response malformed")
    except Exception as e:
        logger.exception("organizer LLM call failed")
        raise HTTPException(500, f"organizer failed: {e}")

    if not content.strip():
        raise HTTPException(500, "organizer returned empty content")

    # 5. 마크다운 → 9 섹션 dict 파싱
    sections = parse_overview_sections(content)
    logger.info("organize start #9")
    # 6. assistant 메시지로 저장 (재적용 / 히스토리)
    msg_id = str(uuid.uuid4())
    conversation_repo.append_message(
        payload.conversation_id,
        user["id"],
        role="assistant",
        content=content,
        message_id=msg_id,
        meta={
            "type": "organize",
            "model": OVERVIEW_ORGANIZER_MODEL,
            "sections": sections,
            "source_message_count": len(messages),
        },
    )
    logger.info("organize start #10")
    return {
        "message_id": msg_id,
        "content": content,
        "sections": sections,
    }
