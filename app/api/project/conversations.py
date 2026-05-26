"""대화 메시지 저장·별점 — 인증 필수."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services import conversation_repo

router = APIRouter(prefix="/conversations")


class CreateConversationRequest(BaseModel):
    id: str | None = Field(None, max_length=64)
    title: str = Field("New chat", max_length=200)
    project_id: int | None = None
    menu_key: str = Field("tokforge", max_length=64)


class AppendMessageRequest(BaseModel):
    id: str | None = Field(None, max_length=64)
    role: str
    content: str = Field(..., min_length=0)
    reasoning: str | None = None
    meta: dict | None = None


class RatingRequest(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)


@router.post("", status_code=201)
def create_conversation(payload: CreateConversationRequest, user: CurrentUser) -> dict:
    try:
        return conversation_repo.create(
            user["id"],
            payload.title,
            conversation_id=payload.id,
            project_id=payload.project_id,
            menu_key=payload.menu_key,
        )
    except ValueError as e:
        if "already exists" in str(e):
            raise HTTPException(409, str(e))
        raise HTTPException(400, str(e))


@router.post("/{conversation_id}/messages", status_code=201)
def append_message(
    conversation_id: str, payload: AppendMessageRequest, user: CurrentUser,
) -> dict:
    try:
        msg = conversation_repo.append_message(
            conversation_id, user["id"],
            role=payload.role, content=payload.content,
            message_id=payload.id, reasoning=payload.reasoning, meta=payload.meta,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not msg:
        raise HTTPException(404, "conversation not found")
    return msg


@router.patch("/{conversation_id}/messages/{message_id}/rating")
def rate_message(
    conversation_id: str, message_id: str, payload: RatingRequest, user: CurrentUser,
) -> dict:
    try:
        msg = conversation_repo.set_rating(
            conversation_id, message_id, user["id"], payload.rating,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not msg:
        raise HTTPException(404, "message not found")
    return msg
