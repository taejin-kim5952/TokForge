"""project.ai — 프로젝트 메뉴별 AI 및 문서 엔드포인트 취합 라우터.

각 메뉴(overview, requirements, features, wbs, ...)의 하위 라우터를 모아
main.py 에 단일 진입점으로 제공한다.

새 메뉴를 추가할 때:
  1. app/api/project/ai/<메뉴명>/ 폴더 생성
  2. 하위 엔드포인트 파일 작성
  3. 이 파일에 include_router 한 줄 추가
"""

from fastapi import APIRouter
from app.api.project.ai.overview import router as overview_router
from app.api.project.ai.requirements import router as requirements_router

router = APIRouter(prefix="/projects", tags=["project-ai"])

router.include_router(overview_router)
router.include_router(requirements_router)