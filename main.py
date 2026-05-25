"""TokForge 진입점 — FastAPI 앱 + 라우터 등록."""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    auth,
    cache,
    chat,
    compressor,
    conversations,
    health,
    models,
    monitor,
    projects,
    prompt,
    rag,
    refiner,
    router as router_api,
    wbs,
    project_ai,
    project_admin,
    project_rag,
)

from app import db
from app.services import prompt_repo


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s"
)


app = FastAPI(
    title="TokForge",
    description="AI 프롬프트를 최적화해 토큰 사용량을 줄이는 Agent Middleware",
    version="0.1.0",
)


db.init_all_schemas()
prompt_repo.seed_if_empty()


# CORS — Vite dev server (localhost:5173) 에서의 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://tokforge-frontend.blackrock-5366afe3.koreacentral.azurecontainerapps.io",
        "https://www.tokforge.ai.kr",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id", "X-Assistant-Message-Id"],
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
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(project_admin.router)
app.include_router(project_rag.router)
app.include_router(conversations.router)
app.include_router(wbs.router)
app.include_router(project_ai.router)
