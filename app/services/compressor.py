"""Step 6 — 컨텍스트 압축 서비스.

RAG 검색 결과를 작은 LLM 으로 한 번 처리해서, 사용자 질문에 직접 관련된 부분만 남김.
입력 토큰을 줄이고 LLM 의 집중도를 높여 답변 품질을 향상시킨다.
"""

import hashlib

import httpx
from langchain.prompts import PromptTemplate

from app.config import OLLAMA_CHAT_URL, COMPRESSOR_MODEL


COMPRESSOR_TEMPLATE = """You are a context compressor. Given a user question and reference documents, extract ONLY the information needed to answer the question.

Rules:
- Keep facts, code snippets, and concrete details that directly relate to the question
- Drop unrelated paragraphs entirely
- Preserve source attribution if present (e.g., file names, section titles)
- Use the same language as the reference documents
- Output the compressed context only — no explanation, no preamble
- If nothing in the documents is relevant, output exactly: (no relevant context)

Question: {query}

Reference documents:
{context}

Compressed context:"""


# 정상성 판단 임계값
_MIN_LENGTH_RATIO = 0.05      # 원본의 5% 미만이면 의심 (너무 잘림)
_MAX_LENGTH_RATIO = 1.2       # 원본보다 길어지면 LLM 이 설명을 시작했을 가능성
_NO_CONTEXT_SENTINEL = "(no relevant context)"


class ContextCompressorService:
    """RAG 컨텍스트를 LLM 으로 압축. 재호출 방지 in-memory 캐시 포함."""

    def __init__(self) -> None:
        self._template = PromptTemplate.from_template(COMPRESSOR_TEMPLATE)
        self._cache: dict[str, str] = {}

    async def compress(self, query: str, context: str) -> str:
        """컨텍스트 압축. 실패·이상 출력 시 원본 반환."""
        if not context or not context.strip():
            return context
        if not query or not query.strip():
            return context

        cache_key = self._make_key(query, context)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        prompt = self._template.format(query=query, context=context)
        try:
            raw = await self._call_ollama(prompt)
        except Exception as e:
            print(f"[COMPRESSOR ERROR] LLM call failed: {e}", flush=True)
            return context

        compressed = raw.strip()

        if compressed.lower().startswith(_NO_CONTEXT_SENTINEL.lower()):
            self._cache[cache_key] = ""
            print(f"[COMPRESSOR] no relevant context found", flush=True)
            return ""

        if not self._is_valid(context, compressed):
            print(
                f"[COMPRESSOR WARN] suspicious output, falling back to original\n"
                f"  context_len: {len(context)}\n"
                f"  output_len:  {len(compressed)}\n"
                f"  output_preview: {compressed[:120]!r}",
                flush=True,
            )
            return context

        self._cache[cache_key] = compressed
        ratio = len(compressed) / len(context)
        print(
            f"[COMPRESSOR] compressed {len(context)} → {len(compressed)} chars "
            f"({ratio:.1%})",
            flush=True,
        )
        return compressed

    async def _call_ollama(self, prompt: str) -> str:
        request = {
            "model": COMPRESSOR_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(OLLAMA_CHAT_URL, json=request)
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _make_key(self, query: str, context: str) -> str:
        h = hashlib.sha1()
        h.update(query.encode("utf-8"))
        h.update(b"\x00")
        h.update(context.encode("utf-8"))
        return h.hexdigest()

    def _is_valid(self, original: str, compressed: str) -> bool:
        if not compressed:
            return False
        ratio = len(compressed) / max(len(original), 1)
        return _MIN_LENGTH_RATIO <= ratio <= _MAX_LENGTH_RATIO


# ────────────── 싱글톤 ──────────────
_service: ContextCompressorService | None = None


def get_compressor() -> ContextCompressorService:
    """전역 ContextCompressorService 싱글톤."""
    global _service
    if _service is None:
        _service = ContextCompressorService()
    return _service
