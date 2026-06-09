"""프로젝트 Admin — PPT 템플릿 (레이아웃 블록 템플릿 CRUD·활성·프리뷰)."""

from __future__ import annotations

import io
import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, OwnedProject
from app.services import ppt_template_asset_service, ppt_template_repo
from app.services.ppt_template_repo import DuplicateTemplateName
from app.services.rag_document_extract import RAG_MAX_FILE_BYTES, file_extension

from app.api.project.ai.ppt.builder import build_pptx
from app.api.project.ai.ppt.ppt_presets import list_presets
from app.api.project.ai.ppt.pptx_template_parser import parse_pptx_to_template

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/admin/ppt-templates",
    tags=["project-admin-ppt-template"],
)

PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


# ───────── 콘텐츠 검증 모델 ─────────
class SlideCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    w: float = 13.333
    h: float = 7.5
    margin: float = 0.85


class ThemeModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)


class TemplateContentModel(BaseModel):
    """느슨한 검증 — 골격(slide/theme/blocks)만 강제하고 elements 는 자유 dict.
    ref 불일치는 인터프리터가 폴백 처리하므로 저장은 막지 않는다."""
    model_config = ConfigDict(extra="allow")
    schema_version: int = 1
    slide: SlideCfg = Field(default_factory=SlideCfg)
    theme: ThemeModel
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    content: TemplateContentModel
    set_active: bool = False


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: TemplateContentModel | None = None


class PreviewRequest(BaseModel):
    content: TemplateContentModel
    deck: dict[str, Any] | None = None


# ───────── 라우트 ─────────
@router.get("")
def list_templates(project: OwnedProject, user: CurrentUser) -> dict[str, Any]:
    return {"templates": ppt_template_repo.list_for_project(project["id"])}


@router.get("/presets")
def get_presets(project: OwnedProject, user: CurrentUser) -> dict[str, Any]:
    return {"presets": list_presets()}


@router.get("/assets/{asset_id}")
def get_asset(
    project: OwnedProject,
    user: CurrentUser,
    asset_id: str = Path(...),
) -> FileResponse:
    """템플릿 이미지 에셋 서빙 (에디터 <img> / 디버그용)."""
    path = ppt_template_asset_service.resolve_asset_path(project["id"], asset_id)
    if not path or not path.is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(
        path=str(path),
        media_type=ppt_template_asset_service.asset_media_type(path),
    )


@router.post("/upload-parse")
async def upload_parse_template(
    project: OwnedProject,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """회사 .pptx 업로드 → 파싱 → 편집 가능 TemplateContent 반환 (템플릿 미저장).

    추출된 이미지 에셋은 즉시 디스크에 저장하고 content 의 image.asset hint 를
    실제 asset id 로 치환한다 (편집 중 <img>·preview·생성이 id 로 해석).
    """
    raw = await file.read()
    if file_extension(file.filename) != ".pptx":
        raise HTTPException(400, "PPTX(.pptx) 파일만 지원합니다")
    if len(raw) > RAG_MAX_FILE_BYTES:
        raise HTTPException(400, f"파일 크기는 {RAG_MAX_FILE_BYTES // (1024 * 1024)}MB 이하여야 합니다")
    if not raw:
        raise HTTPException(400, "빈 파일입니다")

    try:
        result = parse_pptx_to_template(raw)
    except Exception as e:  # noqa: BLE001
        logger.exception("pptx parse failed: project_id=%s", project["id"])
        raise HTTPException(422, f"PPTX 파싱 실패: {e}")

    # 에셋 저장 + hint→실제 id 치환
    content = result["content"]
    hint_to_id: dict[str, str] = {}
    for a in result["assets"]:
        aid = ppt_template_asset_service.save_asset(project["id"], a["blob"], a["ext"])
        hint_to_id[a["hint"]] = aid
    if hint_to_id:
        for block in content.get("blocks", []):
            for el in block.get("elements", []):
                if el.get("kind") == "image" and el.get("asset") in hint_to_id:
                    el["asset"] = hint_to_id[el["asset"]]

    from pathlib import PurePath

    suggested = PurePath(file.filename or "template").stem or "template"
    return {"suggested_name": suggested, "content": content, "report": result["report"]}


@router.get("/{template_id}")
def get_template(
    project: OwnedProject,
    user: CurrentUser,
    template_id: int = Path(...),
) -> dict[str, Any]:
    tpl = ppt_template_repo.get(project["id"], template_id)
    if not tpl:
        raise HTTPException(404, "template not found")
    return tpl


@router.post("")
def create_template(
    project: OwnedProject,
    user: CurrentUser,
    payload: TemplateCreate,
) -> dict[str, Any]:
    try:
        return ppt_template_repo.create(
            project["id"],
            payload.name,
            payload.description,
            payload.content.model_dump(),
            set_active=payload.set_active,
        )
    except DuplicateTemplateName as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.put("/{template_id}")
def update_template(
    project: OwnedProject,
    user: CurrentUser,
    payload: TemplateUpdate,
    template_id: int = Path(...),
) -> dict[str, Any]:
    try:
        tpl = ppt_template_repo.update(
            project["id"],
            template_id,
            name=payload.name,
            description=payload.description,
            content=payload.content.model_dump() if payload.content else None,
        )
    except DuplicateTemplateName as e:
        raise HTTPException(409, str(e))
    if not tpl:
        raise HTTPException(404, "template not found")
    return tpl


@router.post("/{template_id}/activate")
def activate_template(
    project: OwnedProject,
    user: CurrentUser,
    template_id: int = Path(...),
) -> dict[str, bool]:
    if not ppt_template_repo.set_active(project["id"], template_id):
        raise HTTPException(404, "template not found")
    return {"ok": True}


@router.delete("/{template_id}")
def delete_template(
    project: OwnedProject,
    user: CurrentUser,
    template_id: int = Path(...),
) -> dict[str, bool]:
    if not ppt_template_repo.delete(project["id"], template_id):
        raise HTTPException(404, "template not found")
    return {"ok": True}


@router.post("/preview")
def preview_template(
    project: OwnedProject,
    user: CurrentUser,
    payload: PreviewRequest,
):
    content = payload.content.model_dump()
    deck = payload.deck or _sample_deck(content)
    try:
        pptx_bytes = build_pptx(deck, content, project_id=project["id"])
    except Exception as e:  # noqa: BLE001 — 프리뷰 실패는 422 로
        logger.exception("template preview failed: project_id=%s", project["id"])
        raise HTTPException(422, f"preview render failed: {e}")
    import io

    return StreamingResponse(
        io.BytesIO(pptx_bytes),
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote("template-preview.pptx")
        },
    )


# ───────── 프리뷰용 샘플 덱 ─────────
_SAMPLE_SLIDES = {
    "title": {"type": "title", "title": "샘플 제목",
              "subtitle": "부제목 예시 텍스트", "meta": "2026 SAMPLE"},
    "section": {"type": "section", "title": "섹션 제목", "note": "섹션 한 줄 요약"},
    "bullets": {"type": "bullets", "title": "슬라이드 제목", "subtitle": "부제",
                "bullets": ["첫 번째 요점", "두 번째 요점", "세 번째 요점"]},
    "cards": {"type": "cards", "title": "카드 제목",
              "bullets": ["카드 A", "카드 B", "카드 C", "카드 D"]},
}


def _sample_deck(content: dict) -> dict:
    """템플릿의 블록 타입마다 한 장씩 샘플 슬라이드를 만든 미리보기 덱."""
    slides = []
    for b in content.get("blocks", []):
        tp = b.get("type")
        if tp in _SAMPLE_SLIDES:
            slides.append(_SAMPLE_SLIDES[tp])
        else:
            slides.append({
                "type": tp,
                "title": f"{b.get('label', tp)} 샘플",
                "subtitle": "부제 예시",
                "note": "노트 예시",
                "meta": "META",
                "bullets": ["요점 1", "요점 2", "요점 3"],
            })
    if not slides:
        slides = [_SAMPLE_SLIDES["bullets"]]
    return {"title": "템플릿 미리보기", "slides": slides}
