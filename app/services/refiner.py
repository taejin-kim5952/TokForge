"""Step 5 — 질문 정제 서비스.

작은 LLM 으로 사용자 질문의 오타, 중복, 모호한 의도를 정제.
LangChain PromptTemplate 로 프롬프트 구성, Ollama HTTP API 직접 호출.
재호출 방지를 위해 in-memory 캐시 유지.
"""

import httpx
from langchain.prompts import PromptTemplate

from app.config import OLLAMA_CHAT_URL, REFINER_MODEL
from app.services import prompt_repo


REFINER_TEMPLATE = """You are a query refiner. Clean up the user's question for downstream LLM processing.

Rules:
- Fix typos and grammatical errors
- Remove redundancy and filler words
- Make implicit intent explicit
- Keep the same language as the original (Korean stays Korean, English stays English)
- Return ONLY the refined question — no explanations, no prefixes like "Refined:"
- Output should be a single line

Original: {query}
Refined:"""


# 정제 결과 정상성 판단 임계값
_MIN_LENGTH_RATIO = 0.3
_MAX_LENGTH_RATIO = 3.0
_STRIP_PREFIXES = ("Refined:", "Cleaned:", "정제된:", "정제:", "Original:")


class QueryRefinerService:
    """사용자 질문을 LLM 으로 정제. 재호출 방지 in-memory 캐시 포함."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    async def refine(self, query: str) -> str:
        """질문 정제. 실패·이상 출력 시 원본을 안전하게 반환."""
        if not query or not query.strip():
            return query

        # 캐시 확인
        cached = self._cache.get(query)
        if cached is not None:
            return cached

        # LLM 호출 — DB 활성 프롬프트로 매번 새로 빌드
        template_body = prompt_repo.get_active("refiner") or REFINER_TEMPLATE
        template = PromptTemplate.from_template(template_body)
        prompt = template.format(query=query)
        try:
            raw = await self._call_ollama(prompt)
        except Exception as e:
            print(f"[REFINER ERROR] LLM call failed: {e}", flush=True)
            return query

        # 응답 정리 + 정상성 검사
        refined = self._clean(raw)
        if not self._is_valid(query, refined):
            print(
                f"[REFINER WARN] suspicious output, falling back to original\n"
                f"  original: {query!r}\n"
                f"  raw:      {raw!r}\n"
                f"  cleaned:  {refined!r}",
                flush=True,
            )
            return query

        # 캐시 저장
        self._cache[query] = refined
        return refined

    async def _call_ollama(self, prompt: str) -> str:
        """REFINER_MODEL 로 Ollama 호출, 응답 텍스트 반환."""
        request = {
            "model": REFINER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(OLLAMA_CHAT_URL, json=request)
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _clean(self, text: str) -> str:
        """흔한 LLM 결과 노이즈 제거."""
        s = text.strip()
        # prefix 제거
        for p in _STRIP_PREFIXES:
            if s.lower().startswith(p.lower()):
                s = s[len(p):].strip()
                break
        # 첫 줄만 (다중 줄 응답 방지)
        s = s.split("\n")[0].strip()
        # 따옴표로 감싸있으면 제거
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        return s

    def _is_valid(self, original: str, refined: str) -> bool:
        """정제 결과 사용 가능 여부."""
        if not refined:
            return False
        ratio = len(refined) / max(len(original), 1)
        return _MIN_LENGTH_RATIO <= ratio <= _MAX_LENGTH_RATIO


# ────────────── 싱글톤 ──────────────
_service: QueryRefinerService | None = None


def get_refiner() -> QueryRefinerService:
    """전역 QueryRefinerService 싱글톤."""
    global _service
    if _service is None:
        _service = QueryRefinerService()
    return _service
