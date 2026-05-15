"""Step 7 — 모델 자동 라우팅 서비스.

작은 LLM 으로 사용자 질문의 복잡도를 simple/medium/complex 로 분류해서
적합한 답변 모델을 선택한다.
"""

import httpx
from langchain.prompts import PromptTemplate

from app.config import (
    DEFAULT_MODEL,
    MODEL_TIERS,
    OLLAMA_CHAT_URL,
    ROUTER_MODEL,
)


CLASSIFIER_TEMPLATE = """You are a query complexity classifier. Classify the user's question into exactly one of:
- simple: greetings, basic factual queries, single-line questions
- medium: short code snippets (up to 20 lines), conceptual explanations, typical debugging
- complex: architecture or design decisions, multi-file changes, deep debugging, long generation requests

Rules:
- Output exactly one word: simple, medium, or complex
- No explanation, no punctuation, no quotes, no markdown

Question: {query}
Classification:"""


_VALID_TIERS = ("simple", "medium", "complex")


class ModelRouterService:
    """질문 복잡도 → 모델 매핑. 분류 결과 캐싱."""

    def __init__(self) -> None:
        self._template = PromptTemplate.from_template(CLASSIFIER_TEMPLATE)
        self._cache: dict[str, str] = {}    # query → tier

    async def route(self, query: str) -> tuple[str, str]:
        """질문을 분류해 (tier, model) 반환. 실패 시 (DEFAULT_MODEL 매핑 tier, DEFAULT_MODEL)."""
        if not query or not query.strip():
            return ("simple", MODEL_TIERS.get("simple", DEFAULT_MODEL))

        tier = await self._classify(query)
        model = MODEL_TIERS.get(tier, DEFAULT_MODEL)
        return (tier, model)

    async def _classify(self, query: str) -> str:
        """LLM 으로 simple/medium/complex 분류. 결과 캐싱."""
        cached = self._cache.get(query)
        if cached is not None:
            return cached

        prompt = self._template.format(query=query)
        try:
            raw = await self._call_ollama(prompt)
        except Exception as e:
            print(f"[ROUTER ERROR] LLM call failed: {e}", flush=True)
            return "medium"     # 안전한 중간값

        tier = self._parse(raw)
        if tier not in _VALID_TIERS:
            print(
                f"[ROUTER WARN] invalid classification {raw!r} → fallback to medium",
                flush=True,
            )
            return "medium"

        self._cache[query] = tier
        return tier

    async def _call_ollama(self, prompt: str) -> str:
        """ROUTER_MODEL 로 Ollama 호출, 응답 텍스트 반환."""
        request = {
            "model": ROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(OLLAMA_CHAT_URL, json=request)
            data = response.json()
        return data["choices"][0]["message"]["content"]

    def _parse(self, raw: str) -> str:
        """LLM 응답에서 tier 단어만 추출 (소문자, 공백·따옴표·문장부호 제거)."""
        s = raw.strip().lower()
        # 따옴표/문장부호 제거
        s = s.strip('"\'.,!?()[]{}*`')
        # 첫 줄만
        s = s.split("\n")[0].strip()
        # 첫 단어만
        s = s.split()[0] if s.split() else ""
        return s


# ────────────── 싱글톤 ──────────────
_service: ModelRouterService | None = None


def get_router() -> ModelRouterService:
    """전역 ModelRouterService 싱글톤."""
    global _service
    if _service is None:
        _service = ModelRouterService()
    return _service
