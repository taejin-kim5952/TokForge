"""기능정의서 — 대화 정리(organize) 엔드포인트.

현재 활성 대화의 메시지를 분석해 (헤더 + 기능 표 행) 형태의 구조화된 마크다운 출력.
정리 결과는 assistant 메시지로 저장 (meta.type='organize') 하여 재적용/히스토리 가능.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, OwnedProject
from app.config import OVERVIEW_ORGANIZER_MODEL
from app.llm import ollama
from app.services import conversation_repo, prompt_repo

from .prompts import FEATURES_ORGANIZER_PROMPT, parse_features_markdown

router = APIRouter(tags=["프로젝트 기능정의서"])

logger = logging.getLogger(__name__)


class OrganizeRequest(BaseModel):
    conversation_id: str


@router.post("/{project_id}/ai/features/organize")
async def organize_features(
    project: OwnedProject,
    user: CurrentUser,
    payload: OrganizeRequest,
) -> dict:
    """대화 → (헤더, 기능 표 행 배열) 구조화."""

    # 1. 대화 소유권 + 프로젝트/메뉴 매칭 검증
    conv = conversation_repo.get_owned(payload.conversation_id, user["id"])
    if (
        not conv
        or conv.get("project_id") != project["id"]
        or conv.get("menu_key") != conversation_repo.MENU_FEATURES
    ):
        raise HTTPException(404, "conversation not found")

    # 2. 메시지 필터 — 이전 organize 결과는 제외 (재정리 노이즈 방지)
    messages: list[dict] = []
    for m in conv.get("messages", []):
        meta = m.get("meta") or {}
        if meta.get("type") == "organize":
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        messages.append({"role": m["role"], "content": content})

    if not messages:
        raise HTTPException(400, "no messages to organize")

    # 3. 시스템 프롬프트 (DB 활성 버전 우선, 없으면 코드 fallback)
    system_prompt = (
        prompt_repo.get_active("features_organizer", project_id=project["id"])
        or FEATURES_ORGANIZER_PROMPT
    )

    # 4. LLM 호출 (비스트리밍, 큰 모델, 낮은 temperature)
    ollama_request = {
        "model": OVERVIEW_ORGANIZER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
            {
                "role": "user",
                "content": "위 대화를 위 규칙대로 (헤더 + 기능 표) 마크다운 형식으로 정리해줘.",
            },
        ],
        "stream": False,
        "temperature": 0.3,
    }
    try:
        response = await ollama.chat_completion(ollama_request)
        content = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(500, "organizer response malformed")
    except Exception as e:
        logger.exception("features organizer LLM call failed")
        raise HTTPException(500, f"organizer failed: {e}")

    if not content.strip():
        raise HTTPException(500, "organizer returned empty content")

    # 5. 마크다운 → (header, rows) 파싱
    header, rows = parse_features_markdown(content)

    # 6. assistant 메시지로 저장 (재적용/히스토리)
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
            "header": header,
            "rows": rows,
            "source_message_count": len(messages),
        },
    )

    return {
        "message_id": msg_id,
        "content": content,
        "header": header,
        "rows": rows,
    }
