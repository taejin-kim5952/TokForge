"""RAG 엔드포인트 — 문서 업로드 + 검색 + 통계."""

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.rag import get_rag

router = APIRouter(prefix="/v1/rag", tags=["rag"])

ALLOWED_EXTENSIONS = {".txt", ".md"}


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """TXT/MD 파일 업로드 → 청킹 + 인덱싱."""
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"지원 형식: {', '.join(ALLOWED_EXTENSIONS)} (받은 파일: {file.filename})",
        )

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="UTF-8 인코딩 파일만 지원합니다")

    if not text.strip():
        raise HTTPException(status_code=400, detail="빈 파일입니다")

    chunk_count = get_rag().add_document(file.filename, text)
    return {
        "filename": file.filename,
        "size_bytes": len(raw),
        "chunks_created": chunk_count,
    }


@router.get("/search")
def search_documents(q: str, k: int = 5):
    """질문으로 chunk 검색 (디버깅용)."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="쿼리(q)가 비어있습니다")
    results = get_rag().search(q, k=k)
    return {"query": q, "count": len(results), "results": results}


@router.get("/stats")
def rag_stats():
    """RAG 통계 — chunk 수, 문서 수, 인덱스 크기."""
    return get_rag().stats()
