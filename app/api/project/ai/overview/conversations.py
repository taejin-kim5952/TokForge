"""프로젝트 대화 목록 / 단건 조회.

사이드바에서 이전 대화 불러오기 / 새 대화 시작 UX 지원.
모든 엔드포인트는 OwnedProject + CurrentUser 로 격리 보장.
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, OwnedProject
from app.services import conversation_repo

router = APIRouter(tags=["프로젝트 개요"])

logger = logging.getLogger(__name__)


@router.get("/{project_id}/conversations")
def list_project_conversations(
    project: OwnedProject,
    user: CurrentUser,
    scope: str | None = Query(
        None,
        description="생략=전체; scope= 빈값=글로벌 패널 대화만; 그 외=탭 ID와 일치",
    ),
) -> dict:
    """프로젝트의 대화 목록 (최신순, 메시지 수 + has_organize 포함)."""
    return {
        "conversations": conversation_repo.list_by_project(
            user["id"],
            project["id"],
            menu_key=conversation_repo.MENU_OVERVIEW,
            limit=50,
            scope=scope,
        ),
    }


@router.get("/{project_id}/conversations/{conversation_id}")
def get_project_conversation(
    project: OwnedProject,
    user: CurrentUser,
    conversation_id: str,
) -> dict:
    """특정 대화의 전체 메시지 (대화 전환 시 사용)."""
    conv = conversation_repo.get_owned(conversation_id, user["id"])
    if (
        not conv
        or conv.get("project_id") != project["id"]
        or conv.get("menu_key") != conversation_repo.MENU_OVERVIEW
    ):
        raise HTTPException(404, "conversation not found")
    return conv
