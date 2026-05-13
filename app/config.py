"""TokForge 설정값."""

# Ollama 연결 정보
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"

# 모델 식별자 — 여러 곳에서 참조되므로 한 곳에서 정의
_GEMMA4_SMALL = "gemma4:e2b"
_GEMMA4_LARGE = "gemma4:latest"

# 기본 모델 (라우팅 OFF 또는 분류 실패 시 폴백)
DEFAULT_MODEL = _GEMMA4_SMALL

# Step 4 — 프롬프트 템플릿 적용 여부 (False 면 기존 동작 그대로)
ENABLE_PROMPT_TEMPLATE = True

# Step 5 — 질문 정제 (작은 LLM 으로 오타·중복 제거, 의도 명확화)
ENABLE_QUERY_REFINEMENT = True
REFINER_MODEL = _GEMMA4_LARGE

# Step 6 — 컨텍스트 압축 (RAG 결과를 LLM 으로 핵심만 추출)
ENABLE_CONTEXT_COMPRESSION = True
COMPRESSOR_MODEL = _GEMMA4_LARGE

# Step 7 — 모델 자동 라우팅 (질문 복잡도에 따라 답변 모델 선택)
ENABLE_MODEL_ROUTING = True
ROUTER_MODEL = _GEMMA4_LARGE
MODEL_TIERS = {
    "simple":  _GEMMA4_SMALL,
    "medium":  _GEMMA4_SMALL,
    "complex": _GEMMA4_LARGE,
}

# Step 8 — 비용/품질 모니터링 (SQLite 기반 요청별 지표 기록)
ENABLE_MONITORING = True
MONITOR_DB_PATH = "storage/monitor.db"
