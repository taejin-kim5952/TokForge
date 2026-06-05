"""TokForge 진입점 — FastAPI 앱 + 라우터 등록."""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.system import (
    admin,
    auth,
    health,
    models,
    monitor,
)
from app.api.llm import (
    cache,
    chat,
    classify,
    compressor,
    prompt,
    rag,
    refiner,
)
from app.api.project import (
    ai as project_ai,
    admin as project_admin_prompt,
    project_admin as project_admin_pkg,
    conversations,
    projects,
    rag as project_rag,
    wbs,
    stats as project_stats
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
    openapi_tags=[
        {"name": "admin-status", "description": "플랫폼 Admin — 시스템·Ollama 상태"},
        {"name": "admin-prompts", "description": "플랫폼 Admin — 전역 프롬프트 (refiner 등)"},
        {"name": "admin-conversations", "description": "플랫폼 Admin — 대화 이력"},
        {"name": "admin-training", "description": "플랫폼 Admin — 학습 데이터 export"},
        {"name": "admin-projects", "description": "플랫폼 Admin — 전체 프로젝트 목록"},
        {"name": "admin-rag", "description": "플랫폼 Admin — RAG 문서·검색"},
        {"name": "project-admin", "description": "프로젝트 Admin — 소유 프로젝트 설정"},
        {
            "name": "project-admin-modelfile",
            "description": (
                "프로젝트 Modelfile — Ollama Modelfile 조립·미리보기·"
                "ollama create·활성 모델(ollama_model)·생성 이력(modelfile_jobs)"
            ),
        },
        {"name": "project-rag", "description": "프로젝트 RAG — 문서 업로드·관리"},
        {"name": "project-ai", "description": "프로젝트 작업 화면 — 개요·요구사항 AI"},
    ],
)


db.init_all_schemas()
prompt_repo.seed_if_empty()


# CORS — Vite dev server (localhost:5173) 에서의 호출 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://www.tokforge.ai",
        "https://tokforge-frontend.blackrock-5366afe3.koreacentral.azurecontainerapps.io",
        "https://www.tokforge.ai.kr",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id", "X-Assistant-Message-Id", "Content-Disposition"],
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
app.include_router(classify.router)
app.include_router(monitor.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(project_admin_prompt.router)
app.include_router(project_admin_pkg.router)
app.include_router(project_rag.router)
app.include_router(conversations.router)
app.include_router(wbs.router)
app.include_router(project_ai.router)
app.include_router(project_stats.router)