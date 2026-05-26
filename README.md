# TokForge — Agent Middleware

> **프로젝트마다 전문가가 되는 AI 오케스트레이션 워크스페이스**

**🌐 서비스:** [https://www.tokforge.ai](https://www.tokforge.ai)

![Version](https://img.shields.io/badge/version-0.1-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**LLM 호출을 자동으로 최적화하는 미들웨어.**  
AI 클라이언트와 모델 사이에서 요청을 가로채 정제·캐시·검색·압축·라우팅 파이프라인을 거치게 합니다.  
프로젝트별로 맥락·프롬프트·RAG·대화를 쌓고, 메뉴별 AI로 산출물을 만든 뒤 피드백으로 그 프로젝트만의 동작으로 다듬습니다.

| 저장소 | 역할 |
|--------|------|
| **TokForge** (이 repo) | FastAPI 백엔드 — 파이프라인, DB, OAuth, 프로젝트 API |
| **[TokForge.ai](https://www.tokforge.ai)** | Vite + React 프론트 — [www.tokforge.ai](https://www.tokforge.ai) (소스 폴더: [`TokForge.io/`](../TokForge.io)) |

---

## 🎯 미션

> **프로젝트마다 다른 컨텍스트·프롬프트·RAG 전략으로 답변 품질을 높이고 토큰을 절감하며,  
> 대화·문서·버전 관리 UI로 지속 개선한다.**

---

## 🔄 처리 파이프라인 (TokForge AI — `/v1/chat/completions`)

```
[사용자 질문]  (+ 선택: project_id)
   ↓
1. 정제          gemma3:1b — 오타·중복 제거, 의도 명확화
   ↓
2. 의미 캐시     유사 질문 즉시 응답 (API 호출 생략)
   ↓
3. RAG 검색      project_id 지정 시 해당 프로젝트 인덱스만 (글로벌 폴백 없음)
   ↓
4. 압축          핵심만 남기고 토큰 절감
   ↓
5. 템플릿        system 프롬프트 형식 통일
   ↓
6. 모델 라우팅   simple / medium / complex 자동 선택
   ↓
7. Ollama / Azure OpenAI
   ↓
8. 모니터링      토큰·지연·비용 누적 (선택: Langfuse)
```

- **전역 프롬프트** 4종(`refiner`, `classifier`, `compressor`, `system`): 플랫폼 `/admin` — DB 버전 관리, 무재기동 교체.
- **프로젝트 프롬프트** 4종(`overview_chat`, `overview_organizer`, `requirements_chat`, `requirements_organizer`): `/projects/{id}/admin` — 프로젝트·kind별 격리.

---

## 📂 웹 UI 기능 요약

### 랜딩 · TokForge AI · 플랫폼 Admin

| 화면 | 경로 | 내용 |
|------|------|------|
| 랜딩 | `/` | Hero(오케스트레이션 워크스페이스), 파이프라인·아키텍처 소개 |
| TokForge AI | 모달 | 8단계 파이프라인 시각화 + SSE 스트리밍 |
| 플랫폼 Admin | `/admin` | Ollama 상태, 메트릭, **전역** 프롬프트 4종, RAG, 대화 export |
| 프로젝트 목록 | `/projects` | OAuth 사용자별 CRUD |

### ProjectBoard — `/projects/:projectId`

| 메뉴 | 상태 | 기능 |
|------|------|------|
| **프로젝트 개요** | ✅ | 9필드 폼 · 「지금 저장」 · AI 채팅 · 대화 목록 · 내용정리(organize) |
| **요구사항정의서** | ✅ | 비즈니스/시스템명 · 요구 행 테이블 · AI 채팅 · organize · 대화 목록 |
| **RAG 문서** | ✅ | PDF·Office·텍스트 업로드 · 목록 · 다운로드 · 삭제 |
| **WBS** | ✅ | 이슈 보드 · 상태 필터 |
| 기타 메뉴 | ⏳ | 기능정의·화면설계 등 placeholder |

### Project Admin — `/projects/:projectId/admin`

| 탭 | 백엔드 | 프론트 |
|----|--------|--------|
| **프롬프트** | ✅ CRUD + 활성화 | 2단 탭(개요/요구사항 AI × 채팅/내용정리) · 에디터 · 버전 표 · 새 버전 저장/되돌리기/활성화/삭제 |
| **RAG** | ⏳ (`/admin/rag/*` 미구현, 보드 `project/rag`는 동작) | UI 준비 |
| **대화·학습** | ⏳ (`/admin/conversations`, `training/export` 미구현) | UI 준비 |

상세 API 계약: [개발내용/15-project-admin-backend-guide.md](../개발내용/15-project-admin-backend-guide.md)

---

## 🧠 프로젝트 AI 채팅 (개요 / 요구사항)

HTTP body는 JSON이지만, **대화 내용은 Chat API 관례의 평문**입니다.

```json
{
  "conversation_id": "uuid | null",
  "messages": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "document_context": { },
  "model": "DeepSeek-...",
  "stream": true
}
```

서버가 Ollama에 넘길 때:

```text
[ { "role": "system", "content": "<조립된 system>" }, ...messages ]
```

**system 조립** (`_build_system_prompt`):

1. DB 활성 프롬프트 (`prompt_repo.get_active`) 또는 코드 fallback  
2. + 현재 편집 중인 문서 필드 (`document_context`)  
3. + RAG 블록 (마지막 user 질문으로 검색)

| kind | 실행 API | DB 프롬프트 연동 |
|------|----------|------------------|
| `overview_chat` | `POST /projects/{id}/ai/overview` | ✅ `get_active(..., project_id)` |
| `overview_organizer` | `POST .../ai/overview/organize` | ⚠️ `get_active` **전역만** (project_id 미전달) |
| `requirements_chat` | `POST .../ai/requirements` | ❌ 코드 `REQUIREMENTS_SYSTEM_PROMPT` |
| `requirements_organizer` | `POST .../ai/requirements/organize` | ⚠️ 전역만 |

- **대화 영속화**: `conversation_id` 없으면 생성 · 마지막 user만 DB append · assistant는 스트림 종료 시 content 확정 · 헤더 `X-Conversation-Id`, `X-Assistant-Message-Id`.
- **토큰**: 프론트가 **매 요청마다 messages 전체**를내므로 대화가 길수록 입력 토큰 증가 → 추후 N턴 제한·요약 메모리 검토.

---

## ✅ 현재 진행 상황 (2026-05-26 기준)

### 코어 파이프라인 (`/v1/chat/completions`)

| 단계 | 기능 | 상태 |
|------|------|------|
| 1 | 기본 프록시 | ✅ |
| 2 | 의미 캐시 | ✅ sentence-transformers + FAISS |
| 3 | RAG | ✅ LangChain FAISS |
| 4 | 프롬프트 템플릿 | ✅ |
| 5 | 질문 정제 | ✅ |
| 6 | 컨텍스트 압축 | ✅ |
| 7 | 모델 라우팅 | ✅ |
| 8 | 모니터링 | ✅ |
| 9 | Langfuse (선택) | ✅ |

### 인증 · 프로젝트 · 데이터

| 영역 | 상태 | 비고 |
|------|------|------|
| Google OAuth + 세션 | ✅ | Authlib, HTTP-only cookie |
| 프로젝트 CRUD · 소유권 격리 | ✅ | `OwnedProject` |
| **DB** | ✅ **PostgreSQL** | `DATABASE_URL` — README 구버전의 SQLite 설명은 폐기 |
| 프로젝트 RAG 파일 + FAISS | ✅ | `project_rag_files`, `storage/rag_*` |
| 개요·요구사항 문서 | ✅ | `project_documents` / `project_requirements` |
| 대화·메시지 | ✅ | `conversations`, `messages`, menu_key 격리 |

### 프롬프트 버전 관리

| 영역 | 상태 | 비고 |
|------|------|------|
| 전역 4종 `/admin/prompts` | ✅ | `app/api/system/admin.py` |
| 프로젝트 4종 `/projects/{id}/admin/prompts` | ✅ GET·POST·activate·DELETE |
| `prompts.project_id` | ✅ | 전역 NULL / 프로젝트 N |
| 개요 채팅에 Admin 프롬프트 반영 | ✅ | `overview_chat` + `project_id` |
| 요구사항 채팅·organizer·project_id | ⏳ | 위 표 참고 |

### API 패키지 구조 (리팩터링 완료)

```
app/api/
├── system/          # auth, admin(플랫폼), health, models, monitor
├── llm/             # chat, cache, rag, refiner, compressor, classify, prompt
├── project/         # projects, conversations, rag, wbs, admin(프로젝트)
│   └── ai/
│       ├── overview/    # overview, organize, conversations
│       └── requirements/
└── deps.py          # CurrentUser, OwnedProject
```

`main.py`에서 위 라우터 일괄 등록.

### 프론트 (TokForge.ai)

| 영역 | 상태 |
|------|------|
| 랜딩 Hero 문구 | ✅ 오케스트레이션 워크스페이스 |
| ProjectBoard 개요·요구사항·RAG·WBS | ✅ |
| Project Admin 프롬프트 UI | ✅ 2단 탭 · 버전 테이블 · 저장/되돌리기/활성화/삭제 |
| 플랫폼 Admin · i18n ko/en | ✅ |

### 미완 · 알려진 한계

| 항목 | 설명 |
|------|------|
| `/admin` 인증 | ⚠️ public — 운영 전 role 기반 보호 필요 |
| Project Admin RAG·대화 탭 API | ⏳ 프론트만, 백엔드 경로 미구현 |
| requirements_chat → DB 프롬프트 | ⏳ |
| organizer `get_active` + `project_id` | ⏳ |
| 채팅 히스토리 토큰 최적화 | ⏳ 전체 messages 전송 |
| 백엔드 Azure 상시 배포 | ⏳ 프론트 ACA 배포됨, API는 로컬+ngrok 등 |
| 자동 테스트 | ⏳ pytest 미구축 |

---

## 🛠️ 빠른 실행

### 백엔드

```powershell
cd D:\tuning\TokForge
.\.venv\Scripts\Activate.ps1
$env:PYTHONNOUSERSITE = "1"
python -m pip install -r requirements.txt

Copy-Item .env.example .env
# DATABASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OLLAMA_BASE_URL 등

python -m uvicorn main:app --reload --port 8000
```

### 프론트

```powershell
cd D:\tuning\TokForge.io   # 프론트 저장소 폴더명 (제품·도메인은 TokForge.ai)
npm install
# .env: VITE_BACKEND_URL=http://localhost:8000
npm run dev
```

→ **운영 UI:** https://www.tokforge.ai · 로컬 UI: http://localhost:5173 · API 문서: http://localhost:8000/docs

상세: [개발내용/01-quick-start.md](../개발내용/01-quick-start.md)

---

## 📁 디렉토리 구조 (요약)

```
TokForge/
├── main.py                         # FastAPI + 라우터 등록 + CORS
├── app/
│   ├── config.py
│   ├── db.py                       # PostgreSQL (DATABASE_URL)
│   ├── api/
│   │   ├── deps.py
│   │   ├── system/                 # auth, admin, health, models, monitor
│   │   ├── llm/                    # chat 파이프라인, cache, rag, …
│   │   └── project/
│   │       ├── projects.py
│   │       ├── conversations.py
│   │       ├── rag.py              # 보드용 RAG 파일 API
│   │       ├── admin.py            # 프로젝트 Admin 프롬프트 CRUD
│   │       ├── wbs.py
│   │       └── ai/
│   │           ├── overview/
│   │           └── requirements/
│   ├── services/
│   │   ├── prompt_repo.py          # 전역/프로젝트 프롬프트 버전
│   │   ├── conversation_repo.py
│   │   ├── document_repo.py
│   │   ├── project_requirements_repo.py
│   │   ├── rag_context.py, rag_service.py, …
│   └── llm/ollama.py
├── storage/                        # RAG 원본·FAISS (DB 메타는 Postgres)
├── docs/                           # Step 1~8 학습 노트
└── requirements.txt
```

---

## 📡 주요 API (참고)

| 구분 | 예시 경로 |
|------|-----------|
| 파이프라인 채팅 | `POST /v1/chat/completions` |
| 플랫폼 Admin | `GET /admin/status`, `GET/POST /admin/prompts/{kind}` |
| 프로젝트 | `GET/POST /projects`, `GET/PUT /projects/{id}/overview` |
| 개요 AI | `POST /projects/{id}/ai/overview`, `POST .../organize` |
| 요구사항 AI | `POST /projects/{id}/ai/requirements`, `GET/PUT .../requirements` |
| 프로젝트 RAG | `GET/POST/DELETE /projects/{id}/rag/files` |
| 프로젝트 Admin 프롬프트 | `GET/POST /projects/{id}/admin/prompts/...` |

전체 계약은 Swagger(`/docs`) 및 [개발내용](../개발내용/README.md) 참고.

---

## 📚 문서 목차

### 인수인계 · 최신 기능

- [개발내용 README](../개발내용/README.md) — 백엔드/프론트/배포/트러블슈팅
- [13 — 프로젝트 RAG + 개요](../개발내용/13-project-rag-overview.md)
- [15 — 프로젝트 Admin 백엔드 가이드](../개발내용/15-project-admin-backend-guide.md)
- [12 — Roadmap](../개발내용/12-roadmap.md)

### 학습용 Step 노트 (`docs/`)

- [Step 1 — 기본 프록시](docs/step01_기본프록시.md) … [Step 8 — 모니터링](docs/step08_모니터링.md)
- [프로젝트 개요](docs/01_프로젝트_개요.md) · [API 엔드포인트](docs/07_API_엔드포인트.md)

---

## 📜 라이선스

MIT License — [LICENSE](LICENSE)

저장소: https://github.com/taejin-kim5952/TokForge
