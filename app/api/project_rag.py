"""프로젝트별 RAG 문서 — 목록·업로드·다운로드·삭제 (소유자 전용)."""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, OwnedProject
from app.services import rag_file_repo, rag_service
from app.services.rag_document_extract import guess_media_type
from app.services.rag_file_repo import DuplicateRagFilename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/rag", tags=["project-rag"])


def _serialize_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "chunk_count": row["chunk_count"],
        "created_at": row["created_at"],
    }


@router.get("/files")
def list_rag_files(project: OwnedProject) -> dict:
    """목록·집계는 DB(등록된 원본 파일) 기준. FAISS 잔여 인덱스는 반영하지 않음."""
    rows = rag_file_repo.list_for_project(project["id"])
    total_chunks = sum(int(r["chunk_count"]) for r in rows)
    return {
        "files": [_serialize_row(r) for r in rows],
        "stats": {
            "total_sources": len(rows),
            "total_chunks": total_chunks,
        },
    }


@router.post("/files", status_code=201)
async def upload_rag_file(
    project: OwnedProject,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    raw = await file.read()
    try:
        row = rag_service.upload_file(
            project_id=project["id"],
            filename=file.filename or "document.txt",
            raw=raw,
            user_id=user["id"],
        )
    except DuplicateRagFilename as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        logger.exception("rag upload failed project_id=%s", project["id"])
        raise HTTPException(500, "upload failed")

    return {"file": _serialize_row(row)}


@router.get("/files/{file_id}/download")
def download_rag_file(project: OwnedProject, file_id: int) -> FileResponse:
    row = rag_file_repo.get_owned(file_id, project["id"])
    if not row:
        raise HTTPException(404, "file not found")

    path = rag_service.resolve_disk_path(row["storage_path"])
    if not path.is_file():
        raise HTTPException(404, "file missing on disk")

    return FileResponse(
        path=path,
        filename=row["filename"],
        media_type=guess_media_type(row["filename"]),
    )


@router.delete("/files/{file_id}")
def delete_rag_file(project: OwnedProject, file_id: int) -> dict:
    if not rag_service.delete_file(project["id"], file_id):
        raise HTTPException(404, "file not found")
    return {"ok": True}
