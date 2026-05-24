"""프로젝트 RAG 원본 파일 + FAISS 인덱스 통합 서비스."""

import logging
import re
import shutil
import uuid
from pathlib import Path

from app.services import rag_file_repo
from app.services.rag import RAG_BASE_DIR, ingest_text_document, invalidate_rag
from app.services.rag_document_extract import extract_text_from_document
from app.services.rag_file_repo import DuplicateRagFilename

logger = logging.getLogger(__name__)

RAG_FILES_BASE = Path(__file__).parent.parent.parent / "storage" / "rag_files"


def _project_files_dir(project_id: int) -> Path:
    return RAG_FILES_BASE / f"project_{project_id}"


def _index_dir(project_id: int) -> Path:
    return RAG_BASE_DIR / f"project_{project_id}"


def safe_filename(name: str) -> str:
    base = Path(name or "document").name
    cleaned = re.sub(r"[^\w.\-가-힣ㄱ-ㅎㅏ-ㅣ ]", "_", base).strip()
    return cleaned or "document.txt"


def upload_file(
    project_id: int,
    filename: str,
    raw: bytes,
    user_id: int | None,
) -> dict:
    """원본 저장 → DB → FAISS 인덱싱."""
    display_name = Path(filename or "document").name
    text = extract_text_from_document(filename, raw)

    row: dict | None = None
    disk_path: Path | None = None
    storage_root = Path(__file__).parent.parent.parent / "storage"

    try:
        rel_path = (
            f"rag_files/project_{project_id}/"
            f"{uuid.uuid4().hex[:12]}_{safe_filename(display_name)}"
        )
        disk_path = storage_root / rel_path
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(raw)

        row = rag_file_repo.create(
            project_id=project_id,
            filename=display_name,
            storage_path=rel_path,
            size_bytes=len(raw),
            created_by=user_id,
        )
        file_id = row["id"]

        chunk_count = ingest_text_document(project_id, display_name, text)
        rag_file_repo.update_chunk_count(file_id, project_id, chunk_count)
        row["chunk_count"] = chunk_count
        return row

    except DuplicateRagFilename:
        raise
    except Exception:
        if row:
            rag_file_repo.delete_owned(row["id"], project_id)
        if disk_path and disk_path.exists():
            disk_path.unlink(missing_ok=True)
        if display_name:
            try:
                from app.services.rag import get_rag

                get_rag(project_id).delete_source(display_name)
                invalidate_rag(project_id)
            except Exception:
                logger.exception("rollback index failed for %s", display_name)
        raise


def delete_file(project_id: int, file_id: int) -> bool:
    row = rag_file_repo.delete_owned(file_id, project_id)
    if not row:
        return False

    from app.services.rag import get_rag

    get_rag(project_id).delete_source(row["filename"])
    invalidate_rag(project_id)

    disk = Path(__file__).parent.parent.parent / "storage" / row["storage_path"]
    disk.unlink(missing_ok=True)
    return True


def resolve_disk_path(storage_path: str) -> Path:
    return Path(__file__).parent.parent.parent / "storage" / storage_path


def cleanup_project(project_id: int) -> None:
    """프로젝트 삭제 시 디스크·인덱스 캐시 정리 (DB는 CASCADE)."""
    invalidate_rag(project_id)
    shutil.rmtree(_project_files_dir(project_id), ignore_errors=True)
    shutil.rmtree(_index_dir(project_id), ignore_errors=True)
