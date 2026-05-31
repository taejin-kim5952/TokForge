"""FastAPI 공용 dependencies — 인증 추출 등.

`CurrentUser` 타입을 import해서 endpoint 파라미터로 받으면, FastAPI가 자동으로
세션 쿠키를 검증하고 user dict을 주입한다. 인증 실패 시 401.

운영 진입 전: `DEV_USER_ID` 환경변수로 OAuth 없이 인증 시뮬레이션 가능 (ENV=dev 한정).

공개 데모: `DEMO_PROJECT_ID`(기본 4) 프로젝트의 하위 API는 로그인 없이 접근 가능.
이때 프로젝트 소유자 계정으로 API가 동작한다 (대화·저장 등).
"""

import logging
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request

from app.config import DEMO_PROJECT_ID, DEV_USER_ID, ENV, SESSION_COOKIE_NAME
from app.services import project_repo, session_repo, user_repo

logger = logging.getLogger(__name__)


def _resolve_session_user(tf_session: str | None) -> dict | None:
    """세션 쿠키 → user dict. 없거나 만료면 None."""
    if ENV == "dev" and DEV_USER_ID and not tf_session:
        try:
            user_id = int(DEV_USER_ID)
        except ValueError:
            raise HTTPException(500, f"invalid DEV_USER_ID: {DEV_USER_ID!r}")
        user = user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(500, f"DEV_USER_ID={user_id} not in users table")
        return user

    if not tf_session:
        return None

    sess = session_repo.touch_and_get(tf_session)
    if not sess:
        return None

    user = user_repo.get_by_id(sess["user_id"])
    if not user:
        session_repo.delete(tf_session)
        return None

    return user


def _is_demo_api_path(path: str) -> bool:
    """데모 프로젝트 하위 API만 허용. admin·프로젝트 DELETE 경로는 제외."""
    if not DEMO_PROJECT_ID:
        return False
    prefix = f"/projects/{DEMO_PROJECT_ID}"
    if not path.startswith(prefix):
        return False
    if path.startswith(f"{prefix}/admin"):
        return False
    # DELETE /projects/{id} 등 루트 경로 차단
    if path == prefix or path == f"{prefix}/":
        return False
    return True


def _demo_owner_user() -> dict | None:
    if not DEMO_PROJECT_ID:
        return None
    project = project_repo.get_by_id(DEMO_PROJECT_ID)
    if not project:
        return None
    owner_id = project.get("owner_user_id")
    if owner_id is None:
        logger.error("demo project %s has no owner_user_id", DEMO_PROJECT_ID)
        return None
    return user_repo.get_by_id(owner_id)


def get_optional_current_user(
    tf_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict | None:
    """인증 선택 — 실패 시 None (401 아님)."""
    return _resolve_session_user(tf_session)


def get_current_user(
    request: Request,
    tf_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict:
    """현재 인증된 사용자 dict 반환. 미인증 시 401 (데모 API 경로는 소유자로 대행)."""
    user = _resolve_session_user(tf_session)
    if user:
        return user

    if _is_demo_api_path(request.url.path):
        demo_user = _demo_owner_user()
        if demo_user:
            return demo_user

    raise HTTPException(401, "not authenticated")


# 사용 예: def my_endpoint(user: CurrentUser): ...
CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_owned_project(
    project_id: int,
    request: Request,
    user: Annotated[dict | None, Depends(get_optional_current_user)] = None,
) -> dict:
    """project_id 접근 권한 확인. 데모 프로젝트는 비로그인 허용 (admin 제외)."""
    if DEMO_PROJECT_ID and project_id == DEMO_PROJECT_ID:
        project = project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        if not _is_demo_api_path(request.url.path):
            if not user:
                raise HTTPException(401, "not authenticated")
            owned = project_repo.get_owned(project_id, user["id"])
            if not owned:
                raise HTTPException(404, "Project not found")
            return owned
        if user is None:
            return project
        owned = project_repo.get_owned(project_id, user["id"])
        return owned or project

    if not user:
        raise HTTPException(401, "not authenticated")

    project = project_repo.get_owned(project_id, user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    return project


OwnedProject = Annotated[dict, Depends(get_owned_project)]
