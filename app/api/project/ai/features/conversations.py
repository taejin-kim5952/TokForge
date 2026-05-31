"""기능정의서 메뉴 — 대화 목록 / 단건 조회.

requirements/conversations.py 와 동일 패턴, menu_key=MENU_FEATURES 로 필터.
URL prefix는 `/features/conversations`.
"""
import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, OwnedProject
from app.services import conversation_repo

router = APIRouter(tags=["프로젝트 기능정의서"])

logger = logging.getLogger(__name__)


@router.get("/{project_id}/features/conversations")
def list_features_conversations(project: OwnedProject, user: CurrentUser) -> dict:
    """기능정의서 메뉴의 대화 목록 (최신순)."""
    return {
        "conversations": conversation_repo.list_by_project(
            user["id"],
            project["id"],
            menu_key=conversation_repo.MENU_FEATURES,
            limit=50,
        ),
    }


@router.get("/{project_id}/features/conversations/{conversation_id}")
def get_features_conversation(
    project: OwnedProject,
    user: CurrentUser,
    conversation_id: str,
) -> dict:
    """특정 기능정의서 대화의 전체 메시지."""
    conv = conversation_repo.get_owned(conversation_id, user["id"])
    if (
        not conv
        or conv.get("project_id") != project["id"]
        or conv.get("menu_key") != conversation_repo.MENU_FEATURES
    ):
        raise HTTPException(404, "conversation not found")
    return conv
