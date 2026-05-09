"""TokForge 진입점 — FastAPI 앱 + 라우터 등록."""

from fastapi import FastAPI

from app.api import health, chat, models, cache, rag

app = FastAPI(
    title="TokForge",
    description="AI 프롬프트를 최적화해 토큰 사용량을 줄이는 Agent Middleware",
    version="0.1.0",
)

# 라우터 등록
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(models.router)
app.include_router(cache.router)
app.include_router(rag.router)
