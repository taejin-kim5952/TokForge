"""Step 4 — 프롬프트 템플릿 서비스.

LangChain `ChatPromptTemplate` 로 system 프롬프트를 구성하고,
사용자 메시지 + RAG 컨텍스트를 표준 OpenAI messages 배열로 합성한다.
"""

from langchain.prompts import ChatPromptTemplate

SYSTEM_TEMPLATE = """You are a precise coding assistant for the TokForge user.

Rules:
- Answer in the same language as the question (Korean ↔ English).
- If code is requested: provide complete, runnable code first, then a brief explanation.
- If reference documents are provided below, cite the source for each non-trivial claim.
- If you don't know, say so explicitly — do not invent APIs or behavior.{context_block}"""


CONTEXT_BLOCK_TEMPLATE = """

Reference documents:
{context}"""


class PromptTemplateService:
    """OpenAI 호환 messages 배열을 표준 system 프롬프트로 감싸 재구성."""

    def __init__(self) -> None:
        self._system_tpl = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_TEMPLATE),
        ])

    def apply(
        self,
        user_messages: list[dict],
        rag_context: str | None,
    ) -> list[dict]:
        """원본 messages + RAG 컨텍스트 → 표준 messages 리스트."""
        # 1. RAG 컨텍스트 블록 만들기
        context_block = ""
        if rag_context:
            context_block = CONTEXT_BLOCK_TEMPLATE.format(context=rag_context)

        # 2. LangChain 으로 system 메시지 렌더링
        rendered = self._system_tpl.format_messages(context_block=context_block)
        template_system = rendered[0].content

        # 3. 사용자 메시지에서 기존 system 추출 + 나머지 분리
        existing_system: str | None = None
        rest: list[dict] = []
        for m in user_messages:
            if m.get("role") == "system" and existing_system is None:
                existing_system = m.get("content", "")
            else:
                rest.append(m)

        # 4. system 합성: 우리 템플릿 + (있다면) 사용자 system
        if existing_system:
            final_system = f"{template_system}\n\n{existing_system}"
        else:
            final_system = template_system

        return [{"role": "system", "content": final_system}] + rest

    def preview(self, query: str, rag_context: str | None = None) -> list[dict]:
        """디버그용 — 단일 query 로 빠르게 결과 확인."""
        return self.apply(
            [{"role": "user", "content": query}],
            rag_context,
        )


# ────────────── 싱글톤 ──────────────
_service: PromptTemplateService | None = None


def get_template_service() -> PromptTemplateService:
    """전역 PromptTemplateService 싱글톤."""
    global _service
    if _service is None:
        _service = PromptTemplateService()
    return _service
