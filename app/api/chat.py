"""채팅 엔드포인트 — Continue.dev 가 호출하는 메인 API.

흐름: 정제(5) → 캐시(2) → RAG(3) → 압축(6) → 템플릿(4) → 라우팅(7) → Ollama
모니터링(8) 은 각 단계의 변화를 dict 로 수집해 응답 직전 SQLite 기록.
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import (
    ENABLE_CONTEXT_COMPRESSION,
    ENABLE_MODEL_ROUTING,
    ENABLE_MONITORING,
    ENABLE_PROMPT_TEMPLATE,
    ENABLE_QUERY_REFINEMENT,
)
from app.llm import ollama
from app.services.cache import get_cache
from app.services.compressor import get_compressor
from app.services.monitor import get_monitor, now_ms
from app.services.prompt import get_template_service
from app.services.rag import get_rag
from app.services.refiner import get_refiner
from app.services.router import get_router as get_model_router

router = APIRouter()


def _last_user_message(request: dict) -> str | None:
    """messages 배열에서 마지막 user 메시지 추출."""
    for msg in reversed(request.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content")
    return None


def _replace_last_user_message(request: dict, new_content: str) -> None:
    """마지막 user 메시지의 content 를 정제본으로 교체."""
    messages = request.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            msg["content"] = new_content
            return


async def _refine_query(request: dict, metrics: dict) -> str | None:
    """Step 5 — 마지막 user 메시지 정제."""
    if not ENABLE_QUERY_REFINEMENT:
        return _last_user_message(request)

    original = _last_user_message(request)
    metrics["original"] = original
    if not original:
        return None

    refined = await get_refiner().refine(original)
    metrics["refined"] = refined
    metrics["refined_changed"] = refined != original
    if refined != original:
        _replace_last_user_message(request, refined)
        print(
            f"[REFINER] original={original!r} → refined={refined!r}",
            flush=True,
        )
    return refined


def _build_context(query: str, metrics: dict) -> str:
    """RAG 검색 → chunk 들을 컨텍스트 문자열로 합치기."""
    if not query:
        return ""
    chunks = get_rag().search(query, k=3)
    metrics["rag_chunks"] = len(chunks)
    print(f"[RAG DEBUG] query={query!r}, chunks={len(chunks)}", flush=True)
    if not chunks:
        return ""
    result = "\n\n".join(c["content"] for c in chunks)
    metrics["ctx_before"] = len(result)
    print(f"[RAG DEBUG] context length={len(result)}", flush=True)
    return result


async def _compress_context(query: str, context: str, metrics: dict) -> str:
    """Step 6 — RAG 컨텍스트 압축."""
    if not ENABLE_CONTEXT_COMPRESSION or not context:
        metrics["ctx_after"] = len(context)
        return context
    compressed = await get_compressor().compress(query, context)
    metrics["ctx_after"] = len(compressed)
    return compressed


def _inject_context_legacy(request: dict, context: str) -> None:
    """ENABLE_PROMPT_TEMPLATE=False 일 때의 폴백."""
    messages = request.setdefault("messages", [])
    system_msg = next(
        (m for m in messages if m.get("role") == "system"),
        None,
    )
    block = f"참고 문서:\n{context}\n\n위 내용을 참고해 답하세요."
    if system_msg:
        system_msg["content"] = system_msg["content"] + "\n\n" + block
    else:
        messages.insert(0, {"role": "system", "content": block})


def _apply_template(request: dict, rag_context: str) -> None:
    """Step 4 — 프롬프트 템플릿 적용."""
    if ENABLE_PROMPT_TEMPLATE:
        user_messages = request.get("messages", [])
        request["messages"] = get_template_service().apply(
            user_messages,
            rag_context or None,
        )
    else:
        if rag_context:
            _inject_context_legacy(request, rag_context)


async def _select_model(query: str | None, request: dict, metrics: dict) -> None:
    """Step 7 — 라우팅으로 모델 선택. 토글 OFF 면 폴백."""
    if not ENABLE_MODEL_ROUTING:
        metrics["tier"] = None
        metrics["model"] = None
        return
    tier, model = await get_model_router().route(query or "")
    request["model"] = model
    metrics["tier"] = tier
    metrics["model"] = model
    print(f"[ROUTER] tier={tier} model={model}", flush=True)


def _extract_usage(response: dict, metrics: dict) -> None:
    """Ollama 응답에서 토큰 사용량 추출."""
    usage = response.get("usage") or {}
    metrics["prompt_toks"] = usage.get("prompt_tokens")
    metrics["completion_toks"] = usage.get("completion_tokens")
    metrics["total_toks"] = usage.get("total_tokens")


def _record(metrics: dict) -> None:
    """모니터 저장 (토글 OFF 면 noop)."""
    if not ENABLE_MONITORING:
        return
    get_monitor().record(metrics)


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """
    OpenAI 호환 채팅 엔드포인트.
    흐름: 정제 → 캐시 → RAG → 압축 → 템플릿 → 라우팅 → Ollama → 모니터링
    """
    metrics: dict = {}
    started = now_ms()

    try:
        # Step 5 — 정제
        query = await _refine_query(request, metrics)

        # 스트리밍 — 캐시 우회, 나머지 단계는 적용
        if request.get("stream"):
            context = _build_context(query or "", metrics)
            context = await _compress_context(query or "", context, metrics)  # Step 6
            _apply_template(request, context)                                  # Step 4
            await _select_model(query, request, metrics)                       # Step 7
            metrics["latency_ms"] = now_ms() - started
            _record(metrics)        # 스트리밍은 토큰 수집 X (응답 끝까지 기다리지 않음)
            return StreamingResponse(
                ollama.chat_completion_stream(request),
                media_type="text/event-stream",
            )

        # 비스트리밍 — 캐시 확인
        cache = get_cache()
        if query:
            cached = cache.lookup(query)
            if cached is not None:
                metrics["cache_hit"] = True
                _extract_usage(cached, metrics)
                metrics["latency_ms"] = now_ms() - started
                _record(metrics)
                return cached

        # 캐시 미스 → 풀 파이프라인
        context = _build_context(query or "", metrics)
        context = await _compress_context(query or "", context, metrics)   # Step 6
        _apply_template(request, context)                                   # Step 4
        await _select_model(query, request, metrics)                        # Step 7
        response = await ollama.chat_completion(request)

        if query:
            cache.save(query, response)

        _extract_usage(response, metrics)
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        return response

    except Exception as e:
        metrics["error"] = repr(e)
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        raise
