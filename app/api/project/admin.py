"""프로젝트 Admin 엔드포인트 — 소유 프로젝트의 설정·운영 (소유자 전용).

프론트 `/projects/{project_id}/admin` 화면과 연동한다.

- 프롬프트: 메뉴별 AI·내용정리 system 프롬프트 버전 조회·CRUD
  (`overview_chat`, `overview_organizer`, `requirements_chat`, `requirements_organizer`)
- (예정) RAG·대화 이력·학습 export

경로 prefix: `/projects/{project_id}/admin/...`
인증: `OwnedProject` + `CurrentUser` (`app.api.deps`).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, OwnedProject
from app.services import prompt_repo
from app.services.prompt_repo import PROJECT_KINDS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["project-admin"])

TAG_PROMPTS = "project-admin-prompts"


class CreatePromptRequest(BaseModel):
    body: str = Field(..., min_length=1, description="새 프롬프트 본문")
    note: str | None = Field(None, description="선택 — 변경 사유 메모")


def _validate_project_kind(kind: str) -> None:
    """프로젝트 Admin에서 허용하는 prompt kind만 통과."""
    if kind not in PROJECT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid project prompt kind: {kind!r}",
        )


def _serialize_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    """JSON 응답용 — Postgres datetime·bool을 프론트 계약에 맞게 정규화."""
    out = dict(row)
    created_at = out.get("created_at")
    if isinstance(created_at, datetime):
        out["created_at"] = created_at.isoformat()
    if "is_active" in out and out["is_active"] is not None:
        out["is_active"] = int(bool(out["is_active"]))
    return out


@router.get("/projects/{project_id}/admin/prompts", tags=[TAG_PROMPTS])
def list_project_prompts_summary(
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """프로젝트 Admin 프롬프트 탭 — 4종 kind별 버전 요약.

    로그인한 사용자가 해당 프로젝트 소유자일 때만 응답한다.
    ``OwnedProject`` 가 ``project_id`` 소유 여부를 검증하고,
    ``user`` 는 세션 쿠키 기반 인증(미로그인 시 401)용이다.

    대상 kind (프로젝트 전용 4종만, 플랫폼 ``/admin/prompts`` 와 분리):

    - ``overview_chat``, ``overview_organizer``
    - ``requirements_chat``, ``requirements_organizer``

    Returns:
        ``{"kinds": [{"kind", "active_version", "total_versions"}, ...]}``
        프론트 2차 탭(채팅/내용정리)의 ``vN · N versions`` 메타 표시에 사용한다.
    """
    kinds = prompt_repo.summary(project_id=project["id"])
    return {"kinds": kinds}


@router.get("/projects/{project_id}/admin/prompts/{kind}", tags=[TAG_PROMPTS])
def list_project_prompt_versions(
    kind: str,
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """특정 kind의 프롬프트 버전 목록 (본문 제외, 메타만).

    ``overview_chat`` 등 프로젝트 전용 kind 하나에 대해
    버전 번호·활성 여부·본문 길이 등을 반환한다. 편집기 textarea 본문은
    ``GET .../prompts/{kind}/{version}`` 로 조회한다.

    Args:
        kind: ``overview_chat`` | ``overview_organizer`` |
            ``requirements_chat`` | ``requirements_organizer``

    Returns:
        ``{"kind": "<kind>", "versions": [PromptVersionMeta, ...]}``
    """
    _validate_project_kind(kind)
    try:
        versions = prompt_repo.list_versions(kind, project_id=project["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "kind": kind,
        "versions": [_serialize_prompt_row(v) for v in versions],
    }


@router.get("/projects/{project_id}/admin/prompts/{kind}/{version}", tags=[TAG_PROMPTS])
def get_project_prompt_version(
    kind: str,
    version: int,
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """특정 버전의 프롬프트 전체 (본문 포함).

    프로젝트 Admin 편집기에 표시할 system 프롬프트 텍스트를 반환한다.

    Returns:
        id, kind, version, body, is_active, created_at, note, project_id 등.
    """
    _validate_project_kind(kind)
    try:
        row = prompt_repo.get_version(kind, version, project_id=project["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"prompt not found: {kind} v{version}",
        )
    return _serialize_prompt_row(row)


@router.post(
    "/projects/{project_id}/admin/prompts/{kind}",
    status_code=201,
    tags=[TAG_PROMPTS],
)
def create_project_prompt_version(
    kind: str,
    payload: CreatePromptRequest,
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """새 프롬프트 버전 생성 (version 자동 할당, is_active=0).

    첫 저장(v1) 포함. 활성화는 ``POST .../{version}/activate`` 또는
    프론트에서 활성화 버튼으로 처리한다.
    """
    _validate_project_kind(kind)
    try:
        result = prompt_repo.save_new_version(
            kind,
            payload.body,
            payload.note,
            project_id=project["id"],
        )
        # 프로젝트·kind의 첫 버전이면 바로 활성화 (Admin 첫 저장 UX)
        versions = prompt_repo.list_versions(kind, project_id=project["id"])
        if len(versions) == 1:
            prompt_repo.activate(kind, result["version"], project_id=project["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result


@router.post(
    "/projects/{project_id}/admin/prompts/{kind}/{version}/activate",
    tags=[TAG_PROMPTS],
)
def activate_project_prompt_version(
    kind: str,
    version: int,
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """지정 버전을 해당 프로젝트·kind의 활성 프롬프트로 전환."""
    _validate_project_kind(kind)
    try:
        prompt_repo.activate(kind, version, project_id=project["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.delete(
    "/projects/{project_id}/admin/prompts/{kind}/{version}",
    tags=[TAG_PROMPTS],
)
def delete_project_prompt_version(
    kind: str,
    version: int,
    project: OwnedProject,
    user: CurrentUser,
) -> dict:
    """버전 삭제 — 활성 버전은 삭제할 수 없음."""
    _validate_project_kind(kind)
    try:
        prompt_repo.delete_version(kind, version, project_id=project["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}
