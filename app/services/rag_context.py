"""프로젝트 RAG 검색 — chat / overview 공통."""

from __future__ import annotations

import logging

from app.services.rag import get_rag

logger = logging.getLogger(__name__)

DEFAULT_RAG_K = 3


def search_rag_context(
    query: str,
    *,
    project_id: int | None = None,
    k: int = DEFAULT_RAG_K,
) -> tuple[int, str]:
    """유사 청크 검색 후 컨텍스트 문자열 반환.

    - project_id 가 있으면 해당 프로젝트 인덱스만 사용 (글로벌 폴백 없음).
    - project_id 가 없으면 글로벌 인덱스만 사용.

    Returns:
        (chunk_count, context_text) — 청크 없으면 (0, "").
    """
    q = (query or "").strip()
    if not q:
        return 0, ""

    store = get_rag(project_id)
    if store.store is None:
        logger.debug("rag empty index project_id=%r", project_id)
        return 0, ""

    chunks = store.search(q, k=k)
    if not chunks:
        return 0, ""

    context = "\n\n".join(c["content"] for c in chunks)
    logger.info(
        "rag search project_id=%r query_len=%d chunks=%d ctx_len=%d",
        project_id,
        len(q),
        len(chunks),
        len(context),
    )
    return len(chunks), context


def format_rag_prompt_block(context: str) -> str:
    """시스템 프롬프트에 붙일 참고 문서 블록."""
    return f"참고 문서:\n{context}\n\n위 내용을 참고해 답하세요."
