"""TokForge 진입점 — FastAPI 앱 + 라우터 등록."""

from fastapi import FastAPI

from app.api import (
    cache,
    chat,
    compressor,
    health,
    models,
    monitor,
    prompt,
    rag,
    refiner,
    router as router_api,
)

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
app.include_router(prompt.router)
app.include_router(refiner.router)
app.include_router(compressor.router)
app.include_router(router_api.router)
app.include_router(monitor.router)
