"""프로젝트 Admin 엔드포인트 — 소유 프로젝트의 설정·운영 (소유자 전용).

프론트 `/projects/{project_id}/admin` 화면과 연동한다.

- 프롬프트: 메뉴별 AI·내용정리 system 프롬프트 버전 조회·CRUD
  (`overview_chat`, `overview_organizer`, `requirements_chat`, `requirements_organizer`)
- (예정) RAG·대화 이력·학습 export

경로 prefix: `/projects/{project_id}/admin/...`
인증: `OwnedProject` + `CurrentUser` (`app.api.deps`).
"""
import logging

from fastapi import APIRouter

from app.api.deps import OwnedProject
from app.services import prompt_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["project-admin"])


@router.get("/projects/{project_id}/admin/prompts")
def get_prompt_list(project: OwnedProject) -> dict:
    """해당 프로젝트의 메뉴별 프롬프트 kind 요약을 반환한다.

    프로젝트 소유자만 호출할 수 있다. `project_id`에 묶인 프롬프트만 조회하며,
    플랫폼 전역(`/admin/prompts`) kind는 포함하지 않는다.

    대상 kind (4종):
      - overview_chat, overview_organizer
      - requirements_chat, requirements_organizer

    Returns:
        ``{"kinds": [{"kind", "active_version", "total_versions"}, ...]}``
    """
    return {"kinds": prompt_repo.summary(project_id=project["id"])}