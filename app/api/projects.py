"""프로젝트 CRUD 엔드포인트 — 모두 인증 필요.

격리 보장: 모든 호출이 CurrentUser dependency를 통과하고, repo SQL이
owner_user_id를 강제. API 표면에서 owner를 지정할 방법이 없음.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services import project_repo
from app.services.project_repo import DuplicateProjectName

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects")


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)


@router.get("")
def list_projects(user: CurrentUser) -> dict:
    """본인 프로젝트 목록."""
    return {"projects": project_repo.list_for_owner(user["id"])}


@router.post("", status_code=201)
def create_project(payload: CreateProjectRequest, user: CurrentUser) -> dict:
    """프로젝트 생성. 같은 이름 존재 시 409."""
    try:
        return project_repo.create(user["id"], payload.name, payload.description)
    except DuplicateProjectName as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{project_id}")
def delete_project(project_id: int, user: CurrentUser) -> dict:
    """본인 프로젝트 삭제. 없거나 남의 것이면 404 (존재 자체 은닉)."""
    ok = project_repo.delete_owned(project_id, user["id"])
    if not ok:
        raise HTTPException(404, "project not found")
    return {"ok": True}
