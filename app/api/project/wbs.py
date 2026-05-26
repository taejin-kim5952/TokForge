"""WBS 엑셀 양식 자동 채우기 API.

POST /v1/wbs/analyze  — 양식 구조 분석
POST /v1/wbs/fill     — 항목 삽입 → 완성 파일 반환
DELETE /v1/wbs/{template_id} — 임시 파일 삭제
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.services import wbs_service

router = APIRouter(prefix="/v1/wbs", tags=["wbs"])

ALLOWED_EXTENSIONS = {".xlsx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/analyze")
async def analyze_template(file: UploadFile = File(...)) -> dict:
    """업로드된 .xlsx 양식을 분석해 헤더 구조를 반환합니다."""
    filename = file.filename or "template.xlsx"
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"xlsx 파일만 지원합니다 (받은 파일: {filename})")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(400, "파일 크기는 10MB 이하여야 합니다")
    if not raw:
        raise HTTPException(400, "빈 파일입니다")

    try:
        result = wbs_service.analyze_template(raw, filename)
    except Exception as e:
        raise HTTPException(500, f"양식 분석 실패: {e}")

    return result


class FillRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=64)
    header_row: int = Field(1, ge=1)
    columns: list[dict] = Field(..., min_length=1)
    mode: str = Field("manual")            # "auto" | "manual"
    conversation: str = Field("")          # mode=auto 시 사용
    items: list[dict] = Field(default_factory=list)  # mode=manual 시 사용


@router.post("/fill")
async def fill_template(payload: FillRequest) -> Response:
    """양식에 항목을 채워 완성된 .xlsx 파일을 반환합니다."""
    items = payload.items

    # 자동 추출 모드
    if payload.mode == "auto":
        if not payload.conversation.strip():
            raise HTTPException(400, "자동 추출 모드에서는 conversation이 필요합니다")
        items = await wbs_service.extract_items_from_conversation(
            payload.conversation, payload.columns
        )
        if not items:
            raise HTTPException(422, "대화에서 WBS 항목을 추출하지 못했습니다. 대화 내용을 더 구체적으로 입력해주세요.")

    if not items:
        raise HTTPException(400, "삽입할 항목이 없습니다")

    try:
        file_bytes = wbs_service.fill_template(
            payload.template_id, items, payload.header_row, payload.columns
        )
    except FileNotFoundError:
        raise HTTPException(404, "양식 파일을 찾을 수 없습니다. 다시 업로드해주세요.")
    except Exception as e:
        raise HTTPException(500, f"파일 생성 실패: {e}")

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="wbs_filled.xlsx"'},
    )


@router.delete("/{template_id}")
def delete_template(template_id: str) -> dict:
    """업로드된 임시 양식 파일을 삭제합니다."""
    wbs_service.delete_template(template_id)
    return {"ok": True}
