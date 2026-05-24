"""FastAPI 공용 dependencies — 인증 추출 등.

`CurrentUser` 타입을 import해서 endpoint 파라미터로 받으면, FastAPI가 자동으로
세션 쿠키를 검증하고 user dict을 주입한다. 인증 실패 시 401.

운영 진입 전: `DEV_USER_ID` 환경변수로 OAuth 없이 인증 시뮬레이션 가능 (ENV=dev 한정).
"""

import logging
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException

from app.config import DEV_USER_ID, ENV, SESSION_COOKIE_NAME
from app.services import project_repo, session_repo, user_repo

logger = logging.getLogger(__name__)


def get_current_user(
    tf_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict:
    """현재 인증된 사용자 dict 반환. 미인증 시 401."""
    # 개발 편의 backdoor — dev 환경 + DEV_USER_ID 설정 시 cookie 없이도 인증 통과
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
        raise HTTPException(401, "not authenticated")

    sess = session_repo.touch_and_get(tf_session)
    if not sess:
        raise HTTPException(401, "session expired")

    user = user_repo.get_by_id(sess["user_id"])
    if not user:
        # session은 있는데 user가 사라짐 (DB 손상 등) — 세션도 정리
        session_repo.delete(tf_session)
        raise HTTPException(401, "user not found")

    return user


# 사용 예: def my_endpoint(user: CurrentUser): ...
CurrentUser = Annotated[dict, Depends(get_current_user)]


def get_owned_project(project_id: int, user: CurrentUser) -> dict:
    """project_id가 현재 유저 소유인지 확인. 아니면 404."""
    project = project_repo.get_owned(project_id, user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    return project


OwnedProject = Annotated[dict, Depends(get_owned_project)]
