"""requirements — 요구사항정의서 메뉴 AI 및 문서 엔드포인트.

제공 기능:
  - 요구사항정의서 (메타 + 행) 조회 / 저장 (전용 DB 테이블)
  - 요구사항 전용 AI 대화 — 프로젝트 개요 + RAG 자동 참조
    - 자동 대화 영속화 (conversations/messages, menu_key=MENU_REQUIREMENTS)
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
from app.services import conversation_repo, document_repo, project_requirements_repo
from app.services.rag_context import format_rag_prompt_block, search_rag_context

router = APIRouter(tags=["프로젝트 요구사항정의서"])

logger = logging.getLogger(__name__)


REQUIREMENTS_SYSTEM_PROMPT = """당신은 IT 프로젝트 요구사항정의서 작성 전문 AI입니다.
사용자가 제공한 프로젝트 개요와 참고 문서(RAG)를 바탕으로
기능요구사항, 비기능요구사항, 사용자 요구를 명확히 도출하고 분류하세요.
요구사항ID는 `AP-FR-001`, `AP-NFR-001` 같은 일관된 패턴을 사용하세요.
한국어로 답하세요."""


# ────────────── Pydantic 모델 ──────────────

class RequirementRow(BaseModel):
    business_category: str = ""
    requirement_category: str = ""
    requirement_id: str = ""
    req_no: str = ""
    name: str = ""
    detail: str = ""


class RequirementsContent(BaseModel):
    business_name: str = ""
    system_name: str = ""
    rows: list[RequirementRow] = []


class RequirementsAiRequest(BaseModel):
    messages: list[dict]
    conversation_id: str | None = None
    document_context: dict | None = None
    model: str | None = None
    stream: bool = True


# ────────────── System prompt 빌더 ──────────────

def _format_overview_summary(overview_doc: dict) -> str:
    """overview 9필드를 간결한 요약으로 (system prompt 주입용)."""
    if not overview_doc:
        return ""
    field_labels = {
        "purpose":       "목적",
        "background":    "배경",
        "scope":         "포함 범위",
        "out_of_scope":  "제외 범위",
        "key_features":  "핵심 기능",
        "stakeholders":  "이해관계자",
        "tech_stack":    "기술 스택",
        "schedule":      "일정",
        "risks":         "리스크",
    }
    lines = []
    for key, label in field_labels.items():
        val = overview_doc.get(key)
        if val and str(val).strip():
            lines.append(f"- {label}: {val}")
    return "\n".join(lines)


def _format_requirements_context(content: dict | None) -> str:
    """현재 작성 중인 요구사항 폼을 system prompt 주입용 요약으로."""
    if not content:
        return ""
    parts = []
    biz = (content.get("business_name") or "").strip()
    sysn = (content.get("system_name") or "").strip()
    if biz:
        parts.append(f"- 업무명: {biz}")
    if sysn:
        parts.append(f"- 시스템명: {sysn}")
    rows = content.get("rows") or []
    if rows:
        parts.append(f"- 현재 등록된 요구사항 {len(rows)}개:")
        for r in rows[:20]:  # 너무 길어지지 않게 처음 20개만
            rid = (r.get("requirement_id") or "").strip()
            nm = (r.get("name") or "").strip()
            if rid or nm:
                parts.append(f"  · {rid} {nm}".rstrip())
    return "\n".join(parts)


def _build_system_prompt(
    document_context: dict | None,
    overview_doc: dict | None,
    rag_context: str | None,
) -> str:
    system = REQUIREMENTS_SYSTEM_PROMPT
    req_block = _format_requirements_context(document_context)
    if req_block:
        system += f"\n\n현재 작성 중인 요구사항정의서:\n{req_block}"
    ov_block = _format_overview_summary(overview_doc or {})
    if ov_block:
        system += f"\n\n참고 — 프로젝트 개요:\n{ov_block}"
    if rag_context:
        system += "\n\n" + format_rag_prompt_block(rag_context)
    return system


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _build_ollama_request(payload: RequirementsAiRequest, project_id: int) -> dict:
    query = _last_user_content(payload.messages)
    _chunk_count, rag_context = search_rag_context(query, project_id=project_id)
    rag_text = rag_context or None

    overview_doc = document_repo.get(project_id, "overview") or {}

    system = _build_system_prompt(payload.document_context, overview_doc, rag_text)
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


# ────────────── 문서 CRUD ──────────────

@router.get("/{project_id}/requirements")
def get_requirements(project: OwnedProject) -> dict:
    return project_requirements_repo.get(project["id"])


@router.put("/{project_id}/requirements")
def save_requirements(project: OwnedProject, payload: RequirementsContent) -> dict:
    return project_requirements_repo.save(
        project["id"],
        payload.business_name,
        payload.system_name,
        [r.model_dump() for r in payload.rows],
    )


# ────────────── AI 채팅 (SSE + 영속화) ──────────────

@router.post("/{project_id}/ai/requirements")
async def requirements_ai(
    project: OwnedProject,
    user: CurrentUser,
    payload: RequirementsAiRequest,
):
    """채팅 + 자동 영속화.

    - conversation_id 없으면 새 conversation 생성 (menu_key=MENU_REQUIREMENTS)
    - 마지막 user 메시지를 DB에 append
    - assistant 빈 메시지 미리 생성 → 스트림 종료 시 content 확정
    - 응답 헤더로 X-Conversation-Id, X-Assistant-Message-Id 반환
    """
    # 1) conversation 보장 (다른 menu_key면 새로 생성)
    cid = payload.conversation_id
    if cid:
        conv = conversation_repo.get_owned(cid, user["id"])
        if (
            not conv
            or conv.get("project_id") != project["id"]
            or conv.get("menu_key") != conversation_repo.MENU_REQUIREMENTS
        ):
            cid = None
    if not cid:
        conv = conversation_repo.create(
            user["id"],
            title=_derive_title(payload.messages),
            project_id=project["id"],
            menu_key=conversation_repo.MENU_REQUIREMENTS,
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

    # 3) assistant 빈 메시지 미리 발급
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

    from fastapi.responses import JSONResponse
    return JSONResponse(content=response, headers=headers)
