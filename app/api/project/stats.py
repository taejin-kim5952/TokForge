"""프로젝트 대시보드 집계 — GET /projects/{project_id}/stats (소유자 전용).

대시보드 탭에서 필요한 진행률·산출물 상태·WBS·RAG·대화 수를 한 번에 반환한다.
프론트의 개별 호출(`/issues`, `/rag/files`, `/overview`, `/requirements`, `/conversations`)을
이 엔드포인트 하나로 대체하는 것이 목적이다.

인증: ``OwnedProject`` + ``CurrentUser`` (`app.api.deps`) — 비소유 프로젝트는 404.
응답 계약·status 규칙: ``개발내용/dashboard작업.md`` Step 1.
"""
import logging

from fastapi import APIRouter
from app.api.deps import CurrentUser, OwnedProject
from app.services import (
    conversation_repo,
    document_repo,
    project_features_repo,
    project_requirements_repo,
    rag_file_repo,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["project-stats"],
)


@router.get("/stats")
def get_project_stats(project: OwnedProject, user: CurrentUser) -> dict:
    """프로젝트 대시보드 집계 반환.

    progress(산출물 진행률), issues(WBS 상태별 건수),
    rag(문서 수·청크 수), conversations(메뉴별 대화 수)를
    한 번에 응답한다.
    """
    logger.info("stats project_id=%s", project["id"])

    project_id = project["id"]
    user_id = user["id"]

    # RAG
    rag_rows = rag_file_repo.list_for_project(project_id)
    rag_source_count = len(rag_rows)
    rag_chunk_count = sum(int(r["chunk_count"]) for r in rag_rows)

    # conversations — overview
    overview_convs = conversation_repo.list_by_project(
        user_id,
        project_id,
        menu_key=conversation_repo.MENU_OVERVIEW,
        limit=50,
    )
    conv_overview_count = len(overview_convs)

    # conversations — requirements
    requirements_convs = conversation_repo.list_by_project(
        user_id,
        project_id,
        menu_key=conversation_repo.MENU_REQUIREMENTS,
        limit=50,
    )
    conv_requirements_count = len(requirements_convs)

    # document — overview
    overview_doc = document_repo.get(project_id, "overview")
    overview_filled = sum(
        1 for v in overview_doc.values()
        if isinstance(v, str) and v.strip()
    )
    if overview_filled == 0:
        overview_status = "todo"
    elif overview_filled < 3:   # 임계값: 나중에 조정 가능
        overview_status = "wip"
    else:
        overview_status = "done"

    # document — requirements
    req_doc = project_requirements_repo.get(project_id)
    req_has = bool((req_doc.get("business_name") or "").strip()) or bool(
        (req_doc.get("system_name") or "").strip()
    )
    if not req_has:
        for row in req_doc.get("rows") or []:
            if (row.get("name") or "").strip() or (row.get("detail") or "").strip():
                req_has = True
                break
    requirements_status = "done" if req_has else "todo"

    # document — features (요구사항과 동일 done/todo 의미)
    feat_doc = project_features_repo.get(project_id)
    feat_has = bool((feat_doc.get("business_name") or "").strip()) or bool(
        (feat_doc.get("system_name") or "").strip()
    )
    if not feat_has:
        for row in feat_doc.get("rows") or []:
            if (row.get("name") or "").strip() or (row.get("description") or "").strip():
                feat_has = True
                break
    features_status = "done" if feat_has else "todo"

    progress_items = {
        "overview": {"status": overview_status},
        "requirements": {"status": requirements_status},
        "features": {"status": features_status},
        "screens": {"status": "pending"},
        "api": {"status": "pending"},
        "test": {"status": "pending"},
        "wbs": {"status": "todo"},  # issues API 없으면 일단 todo
    }
    progress_total = 7
    progress_done = sum(
        1 for item in progress_items.values() if item["status"] == "done"
    )
    progress_pct = round((progress_done / progress_total) * 100) if progress_total else 0

    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "description": project.get("description"),
        },
        "progress": {
            "done": progress_done,
            "total": progress_total,
            "pct": progress_pct,
            "items": progress_items,
        },
        "issues":   {"total": 0, "todo": 0, "in_progress": 0, "done": 0},
        "rag": {
            "source_count": rag_source_count,
            "chunk_count": rag_chunk_count,
        },
        "conversations": {
            "overview": conv_overview_count,
            "requirements": conv_requirements_count,
        },
    }