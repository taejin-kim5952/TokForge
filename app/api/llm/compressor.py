"""Step 6 — 컨텍스트 압축 디버그 엔드포인트.

질문에 대해 RAG 검색 → 압축 흐름을 실행하고 before/after 결과를 반환.
"""

from fastapi import APIRouter, Query

from app.services.compressor import get_compressor
from app.services.rag import get_rag

router = APIRouter(tags=["pipeline"])


@router.get("/compressor/compress")
async def compress(
    q: str = Query(..., description="압축에 사용할 사용자 질문"),
    k: int = Query(3, ge=1, le=10, description="RAG top-k"),
) -> dict:
    """RAG 검색 결과를 압축하고 before/after 비교 반환."""
    # 1. RAG 검색
    chunks = get_rag().search(q, k=k)
    original = "\n\n".join(c["content"] for c in chunks) if chunks else ""

    if not original:
        return {
            "query": q,
            "rag_chunks_count": 0,
            "original": "",
            "compressed": "",
            "original_chars": 0,
            "compressed_chars": 0,
            "compression_ratio": None,
            "message": "no RAG chunks — nothing to compress",
        }

    # 2. 압축
    compressed = await get_compressor().compress(q, original)

    return {
        "query": q,
        "rag_chunks_count": len(chunks),
        "original": original,
        "compressed": compressed,
        "original_chars": len(original),
        "compressed_chars": len(compressed),
        "compression_ratio": (
            round(len(compressed) / len(original), 3) if original else None
        ),
    }
