"""overview — 프로젝트 개요 AI 및 문서 엔드포인트.

제공 기능:
  - 프로젝트 개요 문서 조회 / 저장
  - 개요 전용 AI 대화 (초안 생성, 수정, 분석)
    - 자동 대화 영속화 (conversations/messages 테이블)
    - 응답 헤더로 conversation_id, assistant_message_id 노출
"""
import json
import logging
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, OwnedProject
from app.llm import ollama
from app.services import conversation_repo, document_repo, prompt_repo
from app.services.rag_context import format_rag_prompt_block, search_rag_context

router = APIRouter(tags=["프로젝트 개요"])

logger = logging.getLogger(__name__)

OVERVIEW_SYSTEM_PROMPT = """당신은 프로젝트 개요 작성 전문 AI입니다.
목적, 배경, 범위, 핵심 기능, 이해관계자, 리스크를 체계적으로 작성해주세요.
한국어로 답하세요."""


class OverviewContent(BaseModel):
    purpose: str | None = None
    background: str | None = None
    scope: str | None = None
    out_of_scope: str | None = None
    key_features: str | None = None
    stakeholders: str | None = None
    tech_stack: str | None = None
    schedule: str | None = None
    risks: str | None = None


class OverviewAiRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    document_context: dict | None = None
    model: str | None = None
    stream: bool = True
    scope: str | None = None


def _norm_conversation_scope(value: str | None) -> str | None:
    """빈문자·공백만 → None (글로벌과 동일)."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _build_system_prompt(
    project_id: int,
    document_context: dict | None,
    rag_context: str | None = None,
    *,
    scope: str | None = None,
) -> str:
    kind = prompt_repo.overview_chat_prompt_kind(scope)
    system = (
        prompt_repo.get_active(kind, project_id=project_id)
        or prompt_repo.get_active("overview_chat", project_id=project_id)
        or OVERVIEW_SYSTEM_PROMPT
    )
    logger.info("system프롬프트 kind=%s ===> %s", kind, system[:200] if system else "")

    if document_context:
        ctx_lines = "\n".join(
            f"- {k}: {v}" for k, v in document_context.items() if v
        )
        if ctx_lines:
            system += f"\n\n현재 작성 중인 내용:\n{ctx_lines}"
    if rag_context:
        system += "\n\n" + format_rag_prompt_block(rag_context)
    return system


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _build_ollama_request(payload: OverviewAiRequest, project_id: int) -> dict:
    query = _last_user_content(payload.messages)
    _chunk_count, rag_context = search_rag_context(query, project_id=project_id)
    rag_text = rag_context or None
    logger.info("payload.document_context>> %s", payload.document_context)
    system = _build_system_prompt(
        project_id,
        payload.document_context,
        rag_text,
        scope=_norm_conversation_scope(payload.scope),
    )
    messages = [{"role": "system", "content": system}] + payload.messages
    return {
        "model": payload.model,
        "messages": messages,
        "stream": payload.stream,
    }


def _derive_title(messages: list[dict]) -> str:
    """첫 user 메시지 앞 40자를 제목으로."""
    for m in messages:
        if m.get("role") == "user":
            content = (m.get("content") or "").strip().replace("\n", " ")
            return (content[:40] + "…") if len(content) > 40 else (content or "New chat")
    return "New chat"


def _extract_delta_content(line: str) -> str:
    """SSE 한 줄에서 OpenAI delta.content 추출. 파싱 실패 시 빈 문자열."""
    line = line.strip()
    if not line.startswith("data:"):
        return ""
    data = line[5:].strip()
    if not data or data == "[DONE]":
        return ""
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return ""
    try:
        return obj["choices"][0]["delta"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return ""


@router.get("/{project_id}/overview")
def get_overview(project: OwnedProject):
    return document_repo.get(project["id"], "overview")


@router.put("/{project_id}/overview")
def save_overview(project: OwnedProject, payload: OverviewContent):
    return document_repo.save(
        project["id"],
        "overview",
        payload.model_dump(exclude_none=True),
    )


@router.post("/{project_id}/ai/overview")
async def overview_ai(
    project: OwnedProject,
    user: CurrentUser,
    payload: OverviewAiRequest,
):
    """채팅 + 자동 영속화.

    - conversation_id 없으면 새 conversation 생성
    - 마지막 user 메시지를 DB에 append (중복 시 멱등)
    - assistant 빈 메시지 미리 생성 → 스트림 종료 시 content 확정
    - 응답 헤더로 X-Conversation-Id, X-Assistant-Message-Id 반환
    """
    logger.info("## 입력정보 >>>> %s", payload.model_dump())
    req_scope = _norm_conversation_scope(payload.scope)
    # 1) conversation 보장
    cid = payload.conversation_id
    if cid:
        conv = conversation_repo.get_owned(cid, user["id"])
        conv_scope = _norm_conversation_scope(conv.get("scope") if conv else None)
        if (
            not conv
            or conv.get("project_id") != project["id"]
            or conv.get("menu_key") != conversation_repo.MENU_OVERVIEW
            or conv_scope != req_scope
        ):
            # 다른 사용자/프로젝트/메뉴의 conversation_id — 새로 생성
            cid = None
    if not cid:
        conv = conversation_repo.create(
            user["id"],
            title=_derive_title(payload.messages),
            project_id=project["id"],
            menu_key=conversation_repo.MENU_OVERVIEW,
            scope=req_scope,
        )
        cid = conv["id"]

    # 2) 마지막 user 메시지 저장
    last_user = next(
        (m for m in reversed(payload.messages) if m.get("role") == "user"),
        None,
    )
    if last_user and (last_user.get("content") or "").strip():
        conversation_repo.append_message(
            cid,
            user["id"],
            role="user",
            content=last_user["content"],
        )

    # 3) assistant 빈 메시지 미리 발급 (id 고정)
    assistant_id = str(uuid.uuid4())
    conversation_repo.append_message(
        cid,
        user["id"],
        role="assistant",
        content="",
        message_id=assistant_id,
        meta={"type": "chat", "model": payload.model},
    )

    ollama_request = _build_ollama_request(payload, project["id"])
    headers = {
        "X-Conversation-Id": cid,
        "X-Assistant-Message-Id": assistant_id,
    }

    if payload.stream:
        async def streamer():
            buffer: list[str] = []
            try:
                async for line in ollama.chat_completion_stream(ollama_request):
                    buffer.append(_extract_delta_content(line))
                    yield line
            finally:
                full = "".join(buffer).strip()
                if full:
                    conversation_repo.update_content(assistant_id, user["id"], full)
                else:
                    # 스트림 도중 중단 또는 빈 응답 — 빈 assistant 메시지 정리
                    conversation_repo.delete_if_empty_assistant(assistant_id, user["id"])

        return StreamingResponse(
            streamer(),
            media_type="text/event-stream",
            headers=headers,
        )

    # 비스트리밍
    response = await ollama.chat_completion(ollama_request)
    try:
        content = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        content = ""
    if content.strip():
        conversation_repo.update_content(assistant_id, user["id"], content)
    else:
        conversation_repo.delete_if_empty_assistant(assistant_id, user["id"])

    # 응답에 헤더 포함 (FastAPI는 dict 반환 시 헤더 추가 불가 — Response로 변환)
    from fastapi.responses import JSONResponse
    return JSONResponse(content=response, headers=headers)
