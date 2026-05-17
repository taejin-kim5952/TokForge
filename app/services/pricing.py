"""LLM 비용 환산 — TokForge 의 절감 가치를 보이기 위한 가상 단가표.

실제로 cloud LLM 호출하지 않음. Ollama 로컬 응답의 토큰 수에
공개 단가를 곱해서 "cloud 였다면 얼마였을지" 추정.

가격 출처 (2026-05 기준):
- OpenAI:    https://openai.com/api/pricing/
- Anthropic: https://www.anthropic.com/pricing
- Google:    https://ai.google.dev/pricing
"""

import os


# per 1M tokens (USD)
PRICING = {
    "gpt4o_mini":    {"input": 0.15, "output": 0.60},
    "claude_haiku":  {"input": 0.80, "output": 4.00},
    "gemini_flash":  {"input": 0.10, "output": 0.40},
}

# 절감 표시의 기준 모델 (가장 흔하게 쓰는 가성비 cloud 모델)
BASELINE_PROVIDER = "claude_haiku"

# 원 환산 — env override 가능
USD_TO_KRW = float(os.environ.get("USD_TO_KRW", "1370"))


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> dict:
    """토큰 수를 3사 가상 비용으로 환산."""
    result = {}
    for provider, rates in PRICING.items():
        usd = (
            (prompt_tokens / 1_000_000) * rates["input"]
            + (completion_tokens / 1_000_000) * rates["output"]
        )
        result[provider] = {
            "usd": round(usd, 8),
            "krw": round(usd * USD_TO_KRW, 4),
        }
    return result


def baseline_cost(prompt_tokens: int, completion_tokens: int) -> dict:
    """절감 비교용 단일 기준 모델 비용."""
    return estimate_cost(prompt_tokens, completion_tokens)[BASELINE_PROVIDER]
