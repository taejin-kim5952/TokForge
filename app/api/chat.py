"""채팅 엔드포인트 — Continue.dev 가 호출하는 메인 API.

흐름: 정제(5) → 캐시(2) → RAG(3) → 압축(6) → 템플릿(4) → 라우팅(7) → Ollama
모니터링(8) 은 각 단계의 변화를 dict 로 수집해 응답 직전 SQLite 기록.

스트리밍 모드에서는 OpenAI 표준 SSE 청크 앞에 커스텀
'pipeline' 이벤트를 인터리브해 보내 프론트엔드 시각화를 지원한다.
('event' 필드가 있는 청크는 OpenAI 호환 클라이언트가 무시하므로 호환성 유지)
"""

import json
import uuid
from copy import deepcopy

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import (
    COMPRESSOR_MODEL,
    ENABLE_CONTEXT_COMPRESSION,
    ENABLE_MODEL_ROUTING,
    ENABLE_MONITORING,
    ENABLE_PROMPT_TEMPLATE,
    ENABLE_QUERY_REFINEMENT,
    REFINER_MODEL,
)
from app.llm import ollama
from app.observability.langfuse_client import (
    get_langfuse,
    is_enabled as langfuse_enabled,
    observe,
    update_current_observation,
)
from app.services.cache import get_cache
from app.services.compressor import get_compressor
from app.services.monitor import get_monitor, now_ms
from app.services.pricing import baseline_cost, estimate_cost
from app.services.prompt import get_template_service
from app.services.rag import get_rag
from app.services.refiner import get_refiner
from app.services.router import get_router as get_model_router

router = APIRouter()


def _pipeline_enabled(request: dict, key: str, default_flag: bool) -> bool:
    """클라이언트가 pipeline.<key> 를 보내면 (config 와 AND), 안 보내면 config 만."""
    opts = request.get("pipeline") or {}
    if key in opts:
        return bool(opts[key]) and default_flag
    return default_flag


def _strip_pipeline_field(request: dict) -> None:
    """Ollama 가 모르는 필드 — forward 전에 제거."""
    request.pop("pipeline", None)


def _strip_compare_mode(request: dict) -> bool:
    """compare_mode 플래그 추출 + 제거."""
    return bool(request.pop("compare_mode", False))


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
    if not _pipeline_enabled(request, "refine", ENABLE_QUERY_REFINEMENT):
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


def _build_context(request: dict, query: str, metrics: dict) -> str:
    if not query or not _pipeline_enabled(request, "rag", True):
        metrics["rag_chunks"] = 0
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


async def _compress_context(request: dict, query: str, context: str, metrics: dict) -> str:
    if not _pipeline_enabled(request, "compress", ENABLE_CONTEXT_COMPRESSION) or not context:
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
    if _pipeline_enabled(request, "template", ENABLE_PROMPT_TEMPLATE):
        user_messages = request.get("messages", [])
        request["messages"] = get_template_service().apply(user_messages, rag_context or None)
    else:
        if rag_context:
            _inject_context_legacy(request, rag_context)


async def _select_model(query: str | None, request: dict, metrics: dict) -> None:
    if not _pipeline_enabled(request, "route", ENABLE_MODEL_ROUTING):
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
    # 명시적 langfuse span — yield 자동 wrap 회피 (base64 에러 원인)
    span_ctx = None
    if langfuse_enabled():
        try:
            span_ctx = get_langfuse().start_as_current_span(
                name="chat.stream",
                input={
                    "model": request.get("model"),
                    "messages": request.get("messages"),
                    "stream": True,
                    "pipeline": request.get("pipeline"),
                },
            )
            span_ctx.__enter__()
        except Exception as e:
            print(f"[LANGFUSE STREAM SPAN ERROR] {e}", flush=True)
            span_ctx = None

    try:
        # Step 5 — Refine
        original = _last_user_message(request)
        if ENABLE_QUERY_REFINEMENT and original:
            yield _sse_event("pipeline", step="refine", status="start")
            refine_start = now_ms()
            await _refine_query(request, metrics)
            metrics["refine_ms"] = now_ms() - refine_start
            metrics["refine_model"] = REFINER_MODEL
            yield _sse_event(
                "pipeline", step="refine", status="done",
                original=original,
                refined=metrics.get("refined"),
                changed=metrics.get("refined_changed", False),
                duration_ms=metrics["refine_ms"],
                model=REFINER_MODEL,
            )
            query = metrics.get("refined") or original
        else:
            query = original
            metrics["original"] = original
            metrics["refine_ms"] = 0
            yield _sse_event(
                "pipeline", step="refine", status="done",
                changed=False, duration_ms=0,
            )

        # Step 2 — Cache
        cache = get_cache()
        cache_on = _pipeline_enabled(request, "cache", True)
        cache_start = now_ms()
        cached = cache.lookup(query) if (query and cache_on) else None
        metrics["cache_ms"] = now_ms() - cache_start
        cache_hit = cached is not None
        metrics["cache_hit"] = cache_hit
        yield _sse_event(
            "pipeline", step="cache", status="done",
            hit=cache_hit, enabled=cache_on,
            duration_ms=metrics["cache_ms"],
        )

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
        rag_start = now_ms()
        context = _build_context(request, query or "", metrics)
        metrics["rag_ms"] = now_ms() - rag_start
        yield _sse_event(
            "pipeline", step="rag", status="done",
            chunks=metrics.get("rag_chunks", 0),
            duration_ms=metrics["rag_ms"],
        )

        # Step 6 — Compress
        compress_start = now_ms()
        context = await _compress_context(request, query or "", context, metrics)
        metrics["compress_ms"] = now_ms() - compress_start
        metrics["compress_model"] = COMPRESSOR_MODEL
        yield _sse_event(
            "pipeline", step="compress", status="done",
            before=metrics.get("ctx_before"),
            after=metrics.get("ctx_after"),
            duration_ms=metrics["compress_ms"],
            model=COMPRESSOR_MODEL,
        )

        # Step 4 — Template
        template_start = now_ms()
        _apply_template(request, context)
        metrics["template_ms"] = now_ms() - template_start
        yield _sse_event(
            "pipeline", step="template", status="done",
            duration_ms=metrics["template_ms"],
        )

        # Step 7 — Route
        route_start = now_ms()
        await _select_model(query, request, metrics)
        metrics["route_ms"] = now_ms() - route_start
        yield _sse_event(
            "pipeline", step="route", status="done",
            tier=metrics.get("tier"),
            model=metrics.get("model"),
            duration_ms=metrics["route_ms"],
        )

        # Ollama 스트림 forward — 토큰을 누적해 끝에서 캐시에 저장
        _strip_pipeline_field(request)
        accumulated = ""
        async for line in ollama.chat_completion_stream(request):
            yield line
            payload = line.strip()
            if payload.startswith("data: "):
                payload = payload[6:].strip()
                if payload and payload != "[DONE]":
                    try:
                        obj = json.loads(payload)
                        chunk = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if chunk:
                            accumulated += chunk
                    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
                        pass

        # 캐시 저장 (스트리밍 응답을 OpenAI 비스트리밍 형식으로 wrap)
        if accumulated and query and cache_on:
            cache.save(query, {
                "choices": [{
                    "message": {"role": "assistant", "content": accumulated},
                    "finish_reason": "stop",
                }]
            })
    finally:
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        _attach_trace_metadata(metrics)

        # Langfuse span 종료 — output 부착 후 명시적 __exit__
        if span_ctx is not None:
            final_output = (locals().get('accumulated') or '')[:2000]
            # v3 패턴: span 객체에 직접 update
            updated = False
            try:
                span_ctx.update(output=final_output)
                updated = True
            except Exception:
                pass
            # fallback: 모듈 함수
            if not updated:
                try:
                    update_current_observation(output=final_output)
                except Exception:
                    pass
            try:
                span_ctx.__exit__(None, None, None)
            except Exception:
                pass


@observe(name="chat.nonstream")
async def _handle_nonstream(request: dict, metrics: dict, started: int) -> dict:
    """비스트리밍 chat 처리 — chat_completions 와 _compare_handler 가 공유."""
    try:
        query = await _refine_query(request, metrics)
        cache = get_cache()
        cache_on = _pipeline_enabled(request, "cache", True)
        if query and cache_on:
            cached = cache.lookup(query)
            if cached is not None:
                metrics["cache_hit"] = True
                _extract_usage(cached, metrics)
                metrics["latency_ms"] = now_ms() - started
                _record(metrics)
                _attach_trace_metadata(metrics)
                return cached

        context = _build_context(request, query or "", metrics)
        context = await _compress_context(request, query or "", context, metrics)
        _apply_template(request, context)
        await _select_model(query, request, metrics)
        _strip_pipeline_field(request)
        response = await ollama.chat_completion(request)
        if query and cache_on:
            cache.save(query, response)
        _extract_usage(response, metrics)
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        _attach_trace_metadata(metrics)
        return response
    except Exception as e:
        metrics["error"] = repr(e)
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        _attach_trace_metadata(metrics)
        raise


def _attach_trace_metadata(metrics: dict) -> None:
    """현재 Langfuse trace 에 TokForge 특화 메타데이터·태그 부착.

    Compare 모드의 raw 호출은 *덮어쓰기* 방지 위해 skip.
    """
    if metrics.get("mode") == "compare-raw":
        return
    ctx_before = metrics.get("ctx_before") or 0
    ctx_after = metrics.get("ctx_after") or 0
    compression_ratio = round(ctx_after / ctx_before, 3) if ctx_before > 0 else None
    update_current_observation(
        metadata={
            "cache_hit": metrics.get("cache_hit", False),
            "refined_changed": metrics.get("refined_changed", False),
            "rag_chunks": metrics.get("rag_chunks", 0),
            "ctx_before": ctx_before,
            "ctx_after": ctx_after,
            "compression_ratio": compression_ratio,
            "tier": metrics.get("tier"),
            "model": metrics.get("model"),
            "total_tokens": metrics.get("total_toks"),
            "latency_ms": metrics.get("latency_ms"),
            "compare_id": metrics.get("compare_id"),
            "mode": metrics.get("mode"),
            "tags": [
                f"cache:{'hit' if metrics.get('cache_hit') else 'miss'}",
                f"tier:{metrics.get('tier') or 'none'}",
                f"mode:{metrics.get('mode') or 'tokforge'}",
            ],
        },
    )


_RAW_PIPELINE = {
    "refine": False, "cache": False, "rag": False,
    "compress": False, "template": False, "route": False,
}


async def _compare_handler(request: dict) -> dict:
    """compare_mode: True 시 같은 query 를 두 번 처리해서 비교 결과 묶어 반환."""
    compare_id = str(uuid.uuid4())

    # Call 1: pipeline 정상 (chip 토글대로)
    p_request = deepcopy(request)
    p_request["stream"] = False
    p_metrics: dict = {"compare_id": compare_id, "mode": "compare-pipe"}
    p_response = await _handle_nonstream(p_request, p_metrics, now_ms())

    # Call 2: raw (pipeline 모두 false → cache lookup·save 자동 skip)
    r_request = deepcopy(request)
    r_request["stream"] = False
    r_request["pipeline"] = dict(_RAW_PIPELINE)
    r_metrics: dict = {"compare_id": compare_id, "mode": "compare-raw"}
    r_response = await _handle_nonstream(r_request, r_metrics, now_ms())

    # Cost 환산 + savings
    p_usage = p_response.get("usage") or {}
    r_usage = r_response.get("usage") or {}
    p_in, p_out = p_usage.get("prompt_tokens", 0), p_usage.get("completion_tokens", 0)
    r_in, r_out = r_usage.get("prompt_tokens", 0), r_usage.get("completion_tokens", 0)
    p_cost = estimate_cost(p_in, p_out)
    r_cost = estimate_cost(r_in, r_out)
    bp = baseline_cost(p_in, p_out)
    br = baseline_cost(r_in, r_out)

    return {
        "compare_id": compare_id,
        "pipeline": {**p_response, "cost": p_cost},
        "raw": {**r_response, "cost": r_cost},
        "savings": {
            "usd": round(br["usd"] - bp["usd"], 8),
            "krw": round(br["krw"] - bp["krw"], 4),
            "baseline_model": "claude_haiku",
        },
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """OpenAI 호환 채팅 엔드포인트."""
    # Compare 모드 — 두 번 처리해서 묶어 반환
    if _strip_compare_mode(request):
        return await _compare_handler(request)

    metrics: dict = {}
    started = now_ms()

    if request.get("stream"):
        return StreamingResponse(
            _streaming_generator(request, metrics, started),
            media_type="text/event-stream",
        )

    return await _handle_nonstream(request, metrics, started)
