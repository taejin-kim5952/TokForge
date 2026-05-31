"""features — 기능정의서 메뉴 AI 및 문서 엔드포인트.

requirements.py 와 동일 패턴. 차이점:
  - 전용 DB 테이블 project_features (project_features_repo)
  - menu_key=MENU_FEATURES 로 대화 격리
  - 컨텍스트로 프로젝트 개요 + 확정된 요구사항(저장된 표) + RAG 자동 참조
"""
import json
import logging
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, OwnedProject
from app.llm import ollama
from app.services import (
    conversation_repo,
    document_repo,
    project_features_repo,
    project_requirements_repo,
)
from app.services.rag_context import format_rag_prompt_block, search_rag_context

router = APIRouter(tags=["프로젝트 기능정의서"])

logger = logging.getLogger(__name__)


FEATURES_SYSTEM_PROMPT = """당신은 IT 프로젝트 기능정의서 작성 전문 AI입니다.
사용자가 제공한 프로젝트 개요, 확정된 요구사항정의서, 참고 문서(RAG)를 바탕으로
요구사항을 구현 가능한 기능 단위로 분해하세요.
각 기능은 기능ID, 기능명, 관련요구사항ID, 기능설명, 처리흐름, 예외처리로 구성합니다.
기능ID는 `FN-001`, `FN-002` 같은 일관된 패턴을 사용하세요.
관련요구사항ID는 요구사항정의서의 요구사항ID(`AP-FR-001` 등)와 연결하세요.
한국어로 답하세요."""


# ────────────── Pydantic 모델 ──────────────

class FeatureRow(BaseModel):
    feature_id: str = ""
    name: str = ""
    requirement_id: str = ""
    description: str = ""
    flow: str = ""
    exception: str = ""


class FeaturesContent(BaseModel):
    business_name: str = ""
    system_name: str = ""
    rows: list[FeatureRow] = []


class FeaturesAiRequest(BaseModel):
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


def _format_requirements_summary(req_doc: dict | None) -> str:
    """저장된 요구사항정의서를 system prompt 주입용 요약으로 (크로스도큐먼트 참조)."""
    if not req_doc:
        return ""
    parts = []
    biz = (req_doc.get("business_name") or "").strip()
    sysn = (req_doc.get("system_name") or "").strip()
    if biz:
        parts.append(f"- 업무명: {biz}")
    if sysn:
        parts.append(f"- 시스템명: {sysn}")
    rows = req_doc.get("rows") or []
    if rows:
        parts.append(f"- 확정 요구사항 {len(rows)}개:")
        for r in rows[:30]:  # 토큰 보호 — 처음 30개만
            rid = (r.get("requirement_id") or "").strip()
            cat = (r.get("requirement_category") or "").strip()
            nm = (r.get("name") or "").strip()
            detail = (r.get("detail") or "").strip()
            cat_part = f" [{cat}]" if cat else ""
            detail_part = f" — {detail[:80]}" if detail else ""
            line = f"  · {rid}{cat_part} {nm}{detail_part}".rstrip()
            if line.strip():
                parts.append(line)
    return "\n".join(parts)


def _format_features_context(content: dict | None) -> str:
    """현재 작성 중인 기능정의서 폼을 system prompt 주입용 요약으로."""
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
        parts.append(f"- 현재 등록된 기능 {len(rows)}개:")
        for r in rows[:20]:  # 너무 길어지지 않게 처음 20개만
            fid = (r.get("feature_id") or "").strip()
            nm = (r.get("name") or "").strip()
            if fid or nm:
                parts.append(f"  · {fid} {nm}".rstrip())
    return "\n".join(parts)


def _build_system_prompt(
    document_context: dict | None,
    overview_doc: dict | None,
    req_doc: dict | None,
    rag_context: str | None,
) -> str:
    system = FEATURES_SYSTEM_PROMPT
    feat_block = _format_features_context(document_context)
    if feat_block:
        system += f"\n\n현재 작성 중인 기능정의서:\n{feat_block}"
    ov_block = _format_overview_summary(overview_doc or {})
    if ov_block:
        system += f"\n\n참고 — 프로젝트 개요:\n{ov_block}"
    req_block = _format_requirements_summary(req_doc or {})
    if req_block:
        system += f"\n\n참고 — 확정된 요구사항정의서:\n{req_block}"
    if rag_context:
        system += "\n\n" + format_rag_prompt_block(rag_context)
    return system


def _last_user_content(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _build_ollama_request(payload: FeaturesAiRequest, project_id: int) -> dict:
    query = _last_user_content(payload.messages)
    _chunk_count, rag_context = search_rag_context(query, project_id=project_id)
    rag_text = rag_context or None

    overview_doc = document_repo.get(project_id, "overview") or {}
    req_doc = project_requirements_repo.get(project_id)

    system = _build_system_prompt(payload.document_context, overview_doc, req_doc, rag_text)
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

@router.get("/{project_id}/features")
def get_features(project: OwnedProject) -> dict:
    return project_features_repo.get(project["id"])


@router.put("/{project_id}/features")
def save_features(project: OwnedProject, payload: FeaturesContent) -> dict:
    return project_features_repo.save(
        project["id"],
        payload.business_name,
        payload.system_name,
        [r.model_dump() for r in payload.rows],
    )


# ────────────── AI 채팅 (SSE + 영속화) ──────────────

@router.post("/{project_id}/ai/features")
async def features_ai(
    project: OwnedProject,
    user: CurrentUser,
    payload: FeaturesAiRequest,
):
    """채팅 + 자동 영속화 (menu_key=MENU_FEATURES)."""
    # 1) conversation 보장 (다른 menu_key면 새로 생성)
    cid = payload.conversation_id
    if cid:
        conv = conversation_repo.get_owned(cid, user["id"])
        if (
            not conv
            or conv.get("project_id") != project["id"]
            or conv.get("menu_key") != conversation_repo.MENU_FEATURES
        ):
            cid = None
    if not cid:
        conv = conversation_repo.create(
            user["id"],
            title=_derive_title(payload.messages),
            project_id=project["id"],
            menu_key=conversation_repo.MENU_FEATURES,
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
