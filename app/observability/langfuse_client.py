"""Langfuse 클라이언트 — TokForge 의 LLM 호출을 trace.

LANGFUSE_ENABLED=false 또는 SDK 미설치 시 자동 no-op (raise 없음).
실제 키가 들어가야 cloud.langfuse.com 으로 데이터 흐름.
"""

from app.config import (
    LANGFUSE_ENABLED,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)


class _NoopLangfuse:
    """Langfuse 비활성 시 더미. 모든 속성·메서드 접근이 자기 자신을 반환 → no-op."""

    def __getattr__(self, _name):
        return _NoopLangfuse()

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


_client = None
_init_attempted = False


def get_langfuse():
    """전역 Langfuse 싱글톤 (또는 no-op 더미)."""
    global _client, _init_attempted
    if _client is not None:
        return _client
    if _init_attempted:
        return _client  # 이전 init 실패 → _NoopLangfuse 캐시됨
    _init_attempted = True

    if not LANGFUSE_ENABLED:
        _client = _NoopLangfuse()
        return _client

    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        print(f"[LANGFUSE] enabled → {LANGFUSE_HOST}", flush=True)
    except Exception as e:
        print(f"[LANGFUSE INIT ERROR] {e} — falling back to no-op", flush=True)
        _client = _NoopLangfuse()

    return _client


def is_enabled() -> bool:
    """실제 Langfuse 트레이스 전송 중인지 (key·SDK 모두 정상일 때만 True)."""
    return LANGFUSE_ENABLED and not isinstance(get_langfuse(), _NoopLangfuse)


def observe(name=None, as_type=None, capture_input=True, capture_output=True):
    """LangFuse @observe decorator 의 안전 wrap.

    - Langfuse 비활성 / SDK 없음 → 원본 함수 그대로 반환 (no-op)
    - 활성 → langfuse 의 @observe 적용
    - capture_output=False — 스트리밍 응답이 base64 로 오인되는 에러 회피용
    """
    def decorator(func):
        if not LANGFUSE_ENABLED:
            return func
        try:
            from langfuse import observe as lf_observe
            kwargs = {"name": name, "as_type": as_type,
                      "capture_input": capture_input,
                      "capture_output": capture_output}
            # 일부 langfuse 버전은 capture_* 인자 미지원 — try 후 fallback
            try:
                return lf_observe(**kwargs)(func)
            except TypeError:
                return lf_observe(name=name, as_type=as_type)(func)
        except Exception as e:
            print(f"[LANGFUSE OBSERVE ERROR] {e} — bypassing decorator", flush=True)
            return func
    return decorator


def update_current_observation(**kwargs):
    """현재 트레이스/observation 에 메타데이터·모델·usage 등 부착.

    Langfuse v2/v3 API 호환 — 여러 메서드명 fallback 시도.
    """
    if not LANGFUSE_ENABLED:
        return
    # v2 패턴 — langfuse_context
    try:
        from langfuse.decorators import langfuse_context
        langfuse_context.update_current_observation(**kwargs)
        return
    except (ImportError, AttributeError):
        pass
    # v3 패턴 — client 의 update_current_* 메서드 (이름 가능성 여러 가지)
    try:
        client = get_langfuse()
        for name in ('update_current_observation',
                     'update_current_span',
                     'update_current_generation'):
            method = getattr(client, name, None)
            if callable(method):
                method(**kwargs)
                return
    except Exception as e:
        print(f"[LANGFUSE UPDATE ERROR] {e}", flush=True)


def update_current_trace(**kwargs):
    """현재 root trace 에 메타데이터·태그·user_id 등 부착."""
    if not LANGFUSE_ENABLED:
        return
    try:
        from langfuse.decorators import langfuse_context
        langfuse_context.update_current_trace(**kwargs)
        return
    except (ImportError, AttributeError):
        pass
    try:
        client = get_langfuse()
        method = getattr(client, 'update_current_trace', None)
        if callable(method):
            method(**kwargs)
    except Exception as e:
        print(f"[LANGFUSE TRACE UPDATE ERROR] {e}", flush=True)


def flush() -> None:
    """버퍼된 trace 를 동기적으로 전송 (FastAPI shutdown 시 권장)."""
    if not LANGFUSE_ENABLED:
        return
    try:
        get_langfuse().flush()
    except Exception:
        pass
