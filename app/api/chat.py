"""채팅 엔드포인트 — Continue.dev 가 호출하는 메인 API.

흐름: 정제(5) → 캐시(2) → RAG(3) → 압축(6) → 템플릿(4) → 라우팅(7) → Ollama
모니터링(8) 은 각 단계의 변화를 dict 로 수집해 응답 직전 SQLite 기록.

스트리밍 모드에서는 OpenAI 표준 SSE 청크 앞에 커스텀
'pipeline' 이벤트를 인터리브해 보내 프론트엔드 시각화를 지원한다.
('event' 필드가 있는 청크는 OpenAI 호환 클라이언트가 무시하므로 호환성 유지)
"""

import json

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


def _sse_event(event: str, **payload) -> str:
    """커스텀 SSE 이벤트 (OpenAI 표준에 없는 'event' 필드 포함)."""
    body = {"event": event, **payload}
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"


def _last_user_message(request: dict) -> str | None:
    for msg in reversed(request.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content")
    return None


def _replace_last_user_message(request: dict, new_content: str) -> None:
    messages = request.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            msg["content"] = new_content
            return


async def _refine_query(request: dict, metrics: dict) -> str | None:
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
        print(f"[REFINER] original={original!r} → refined={refined!r}", flush=True)
    return refined


def _build_context(query: str, metrics: dict) -> str:
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
    if not ENABLE_CONTEXT_COMPRESSION or not context:
        metrics["ctx_after"] = len(context)
        return context
    compressed = await get_compressor().compress(query, context)
    metrics["ctx_after"] = len(compressed)
    return compressed


def _inject_context_legacy(request: dict, context: str) -> None:
    messages = request.setdefault("messages", [])
    system_msg = next((m for m in messages if m.get("role") == "system"), None)
    block = f"참고 문서:\n{context}\n\n위 내용을 참고해 답하세요."
    if system_msg:
        system_msg["content"] = system_msg["content"] + "\n\n" + block
    else:
        messages.insert(0, {"role": "system", "content": block})


def _apply_template(request: dict, rag_context: str) -> None:
    if ENABLE_PROMPT_TEMPLATE:
        user_messages = request.get("messages", [])
        request["messages"] = get_template_service().apply(user_messages, rag_context or None)
    else:
        if rag_context:
            _inject_context_legacy(request, rag_context)


async def _select_model(query: str | None, request: dict, metrics: dict) -> None:
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
    usage = response.get("usage") or {}
    metrics["prompt_toks"] = usage.get("prompt_tokens")
    metrics["completion_toks"] = usage.get("completion_tokens")
    metrics["total_toks"] = usage.get("total_tokens")


def _record(metrics: dict) -> None:
    if not ENABLE_MONITORING:
        return
    get_monitor().record(metrics)


async def _streaming_generator(request: dict, metrics: dict, started: int):
    """스트리밍 응답 — 파이프라인 이벤트 + Ollama 토큰."""
    try:
        # Step 5 — Refine
        original = _last_user_message(request)
        if ENABLE_QUERY_REFINEMENT and original:
            yield _sse_event("pipeline", step="refine", status="start")
            await _refine_query(request, metrics)
            yield _sse_event(
                "pipeline", step="refine", status="done",
                original=original,
                refined=metrics.get("refined"),
                changed=metrics.get("refined_changed", False),
            )
            query = metrics.get("refined") or original
        else:
            query = original
            metrics["original"] = original
            yield _sse_event("pipeline", step="refine", status="done", changed=False)

        # Step 2 — Cache
        cache = get_cache()
        cached = cache.lookup(query) if query else None
        cache_hit = cached is not None
        metrics["cache_hit"] = cache_hit
        yield _sse_event("pipeline", step="cache", status="done", hit=cache_hit)

        # 캐시 히트 — 즉시 응답
        if cache_hit and cached is not None:
            try:
                cached_content = cached["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                cached_content = ""
            chunk = {
                "choices": [{
                    "delta": {"role": "assistant", "content": cached_content},
                    "finish_reason": "stop",
                }]
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            _extract_usage(cached, metrics)
            return

        # Step 3 — RAG
        context = _build_context(query or "", metrics)
        yield _sse_event(
            "pipeline", step="rag", status="done",
            chunks=metrics.get("rag_chunks", 0),
        )

        # Step 6 — Compress
        context = await _compress_context(query or "", context, metrics)
        yield _sse_event(
            "pipeline", step="compress", status="done",
            before=metrics.get("ctx_before"),
            after=metrics.get("ctx_after"),
        )

        # Step 4 — Template
        _apply_template(request, context)
        yield _sse_event("pipeline", step="template", status="done")

        # Step 7 — Route
        await _select_model(query, request, metrics)
        yield _sse_event(
            "pipeline", step="route", status="done",
            tier=metrics.get("tier"),
            model=metrics.get("model"),
        )

        # Ollama 스트림 forward
        async for line in ollama.chat_completion_stream(request):
            yield line
    finally:
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """OpenAI 호환 채팅 엔드포인트."""
    metrics: dict = {}
    started = now_ms()

    if request.get("stream"):
        return StreamingResponse(
            _streaming_generator(request, metrics, started),
            media_type="text/event-stream",
        )

    # 비스트리밍 — 기존 로직 그대로
    try:
        query = await _refine_query(request, metrics)
        cache = get_cache()
        if query:
            cached = cache.lookup(query)
            if cached is not None:
                metrics["cache_hit"] = True
                _extract_usage(cached, metrics)
                metrics["latency_ms"] = now_ms() - started
                _record(metrics)
                return cached
        context = _build_context(query or "", metrics)
        context = await _compress_context(query or "", context, metrics)
        _apply_template(request, context)
        await _select_model(query, request, metrics)
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
