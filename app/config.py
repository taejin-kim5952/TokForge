"""TokForge 설정값.

환경변수 우선, 없으면 아래 상수 사용 (.env 파일 자동 로드).
"""

import os
from dotenv import load_dotenv

load_dotenv()


# Ollama 연결 정보
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"

# Azure OpenAI 연결 정보
AZURE_OPENAI_BASE_URL = os.environ.get("AZURE_OPENAI_BASE_URL", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_MODEL = os.environ.get("AZURE_OPENAI_MODEL", "")


# Step 9 — Langfuse 관찰성
LANGFUSE_ENABLED = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

# 모델 식별자 — 여러 곳에서 참조되므로 한 곳에서 정의
_GEMMA4_SMALL = "gemma4:e2b"
_GEMMA4_LARGE = "gemma4:latest"
_GEMMA3_TINY  = "gemma3:1b"

# 기본 모델 (라우팅 OFF 또는 분류 실패 시 폴백)
DEFAULT_MODEL = _GEMMA4_SMALL

# Step 4 — 프롬프트 템플릿 적용 여부 (False 면 기존 동작 그대로)
ENABLE_PROMPT_TEMPLATE = True

# Step 5 — 질문 정제 (작은 LLM 으로 오타·중복 제거, 의도 명확화)
ENABLE_QUERY_REFINEMENT = True
REFINER_MODEL = _GEMMA3_TINY

# Step 6 — 컨텍스트 압축 (RAG 결과를 LLM 으로 핵심만 추출)
ENABLE_CONTEXT_COMPRESSION = True
COMPRESSOR_MODEL = _GEMMA4_LARGE

# 프로젝트 개요 정리(organize) 전용 모델 — 구조화 안정성 위해 큰 모델 권장
OVERVIEW_ORGANIZER_MODEL = os.environ.get("OVERVIEW_ORGANIZER_MODEL", _GEMMA4_LARGE)

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


# ────────────── Auth (Google OAuth + 세션) ──────────────
ENV = os.environ.get("ENV", "dev")  # "dev" | "prod"

# Google OAuth — credentials은 .env에서 주입
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/auth/google/callback",
)

# 세션 쿠키
SESSION_COOKIE_NAME = "tf_session"
SESSION_TTL_DAYS = 30
SESSION_REFRESH_THRESHOLD_DAYS = 7  # 만료까지 N일 이하 남으면 자동 연장

# 프론트(www.tokforge.ai.kr) ≠ API(ngrok 등) 일 때 크로스 사이트 쿠키 필요
def _api_is_public_https() -> bool:
    uri = GOOGLE_REDIRECT_URI
    return uri.startswith("https://") and "localhost" not in uri and "127.0.0.1" not in uri


_SESSION_CROSS_SITE_ENV = os.environ.get("SESSION_CROSS_SITE", "").lower()
SESSION_CROSS_SITE = _SESSION_CROSS_SITE_ENV in ("1", "true", "yes") or (
    _SESSION_CROSS_SITE_ENV not in ("0", "false", "no") and _api_is_public_https()
)
COOKIE_SAMESITE: str = "none" if SESSION_CROSS_SITE else "lax"
# SameSite=None 은 브라우저가 Secure 필수
COOKIE_SECURE = SESSION_CROSS_SITE or ENV == "prod"

# 프론트엔드 origin 허용 목록 — return_to 검증에 사용 (open-redirect 차단)
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "https://tokforge-frontend.blackrock-5366afe3.koreacentral.azurecontainerapps.io",
    "https://www.tokforge.ai.kr",
]

# 개발 편의 — 설정 시 OAuth 없이 그 user_id로 인증된 것처럼 동작 (운영에서 절대 사용 X)
DEV_USER_ID = os.environ.get("DEV_USER_ID")  # str or None

# 공개 데모 프로젝트 — 로그인 없이 /projects/{id}/… API 접근 (admin·DELETE 제외)
_demo_raw = os.environ.get("DEMO_PROJECT_ID", "4").strip()
DEMO_PROJECT_ID: int | None = int(_demo_raw) if _demo_raw.isdigit() else None
