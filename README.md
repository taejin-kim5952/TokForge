# TokForge — Agent Middleware

> **프로젝트마다 맞춤화되는 AI 컨텍스트 최적화 미들웨어**

![Version](https://img.shields.io/badge/version-0.1-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**LLM 호출을 자동으로 최적화하는 미들웨어.**
AI 클라이언트와 모델 사이에서 요청을 가로채 정제·캐시·검색·압축·라우팅 파이프라인을 거치게 합니다.
프로젝트별로 따로 튜닝 가능하며, 결과 답변 품질과 토큰 효율을 동시에 끌어올립니다.

---

## 🎯 미션

> **프로젝트마다 다른 컨텍스트 전략으로 답변 품질을 높이고 토큰을 절감하며,
> 흐름과 통계 시각화로 지속 개선한다.**

---

## 🔄 처리 파이프라인 (TokForgeAI)

```
[사용자 질문]  (+ 선택: project_id)
   ↓
1. 정제          gemma3:1b 로 오타·중복 제거, 의도 명확화
   ↓
2. 의미 캐시     같은/비슷한 질문이면 즉시 응답 (API 호출 X)
   ↓
3. RAG 검색      프로젝트별 등록 문서에서 chunks 검색 (project_id 지정 시 해당 프로젝트만)
   ↓
4. 압축          핵심만 남기고 토큰 줄이기
   ↓
5. 템플릿        정해진 system 프롬프트로 형식 통일 ([Role][Q][Output] 등)
   ↓
6. 모델 라우팅   복잡도 따라 답변 모델 자동 선택 (simple/medium/complex)
   ↓
7. Ollama / Azure OpenAI 호출
   ↓
8. 응답 + 모니터링 기록 (토큰·비용·지연시간 누적)
   ↓
[사용자]
```

- `project_id`가 있으면 **해당 프로젝트 RAG 인덱스만** 사용 (글로벌·다른 프로젝트 문서로 폴백하지 않음).
- 각 단계의 프롬프트는 **DB에 버전 저장 + Admin UI에서 재기동 없이 교체** 가능.

---

## 📂 프로젝트 기능 (웹 UI)

프론트 [`TokForge.io`](../TokForge.io) — `/projects/:projectId` **ProjectBoard**

| 메뉴 | 기능 |
|------|------|
| **프로젝트 개요** | 9개 필드 직접 편집 + 「지금 저장」 / AI 채팅 / 대화 목록 / 내용정리 |
| **RAG 문서** | PDF·Word·PPT·Excel·텍스트 업로드, 목록, 다운로드, 삭제 |
| **WBS** | 이슈 보드 (상태별 필터) |
| 기타 메뉴 | 요구사항·기능정의 등 (폼 placeholder, 준비 중) |

### RAG 문서 (프로젝트별)

- **저장**: DB `project_rag_files` + 원본 `storage/rag_files/project_{id}/` + 벡터 `storage/rag_index/project_{id}/`
- **지원 형식**: `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.xlsm`
- **API**: `GET/POST/DELETE /projects/{id}/rag/files`, `GET .../download`
- **채팅 연동**: TokForgeAI(`project_id`) + 프로젝트 개요 AI — 공통 [`rag_context.py`](app/services/rag_context.py)

### 프로젝트 개요

- **문서**: `GET/PUT /projects/{id}/overview` → `project_documents` (JSON)
- **AI**: `POST /projects/{id}/ai/overview` — Ollama 또는 Azure(DeepSeek), RAG + 폼 컨텍스트 주입
- **수동 편집**: 자동 저장 없음 — 사용자가 「지금 저장」 클릭

상세: [개발내용/13-project-rag-overview.md](../개발내용/13-project-rag-overview.md)

---

## ✅ 현재 진행 상황

### 코어 파이프라인

| 단계 | 기능 | 상태 | 구현 방식 |
|---|---|---|---|
| 1 | 기본 프록시 | ✅ 완료 | 직접 구현 (FastAPI + httpx) |
| 2 | 의미 캐시 | ✅ 완료 | 직접 구현 (sentence-transformers + FAISS) |
| 3 | RAG 컨텍스트 주입 | ✅ 완료 | **LangChain** (FAISS + HuggingFace) |
| 4 | 프롬프트 템플릿 | ✅ 완료 | **LangChain** (ChatPromptTemplate) |
| 5 | 질문 정제 (gemma3:1b) | ✅ 완료 | **LangChain** (PromptTemplate) |
| 6 | 컨텍스트 압축 | ✅ 완료 | **LangChain** (PromptTemplate) |
| 7 | 모델 자동 라우팅 | ✅ 완료 | **LangChain** (PromptTemplate) |
| 8 | 비용/품질 모니터링 | ✅ 완료 | **자체 구현** (SQLite + 집계 API) |
| 9 | 관찰성 (Langfuse) | ✅ 완료 (선택) | Langfuse trace (`LANGFUSE_ENABLED`) |

> **설계 원칙**: Step 1~2 는 학습 목적의 직접 구현, Step 3 부터는 LangChain 도입.

### 운영·프로젝트 기능

| 영역 | 상태 | 구현 |
|---|---|---|
| 프롬프트 버전 관리 | ✅ 완료 | SQLite + Admin UI (4종 × N 버전, 무재기동 교체) |
| Google OAuth 로그인 | ✅ 완료 | Authlib + PKCE + 불투명 세션 토큰 |
| 사용자별 프로젝트 CRUD | ✅ 완료 | SQL `owner_user_id` 격리 보장 |
| **프로젝트 RAG 문서** | ✅ 완료 | 업로드·목록·다운로드·프로젝트별 FAISS 격리 |
| **프로젝트 개요 (폼+AI)** | ✅ 완료 | 9필드 수동 저장 + AI 채팅 + RAG 연동 |
| Admin Dashboard | ✅ 완료 | Ollama 상태 / 메트릭 / 프롬프트·RAG 관리 |
| 채팅 스트리밍 (SSE) | ✅ 완료 | OpenAI 호환 + 커스텀 pipeline 이벤트 |
| `/admin` 인증 보호 | ⏳ 미완 | 현재 public — 운영 진입 전 필수 |
| 프로젝트별 prompt 격리 | ⏳ 다음 | `prompts.project_id` 컬럼 추가 예정 |
| 백엔드 운영 배포 | ⏳ 미완 | 현재 로컬 PC + ngrok |

---

## 🛠️ 빠른 실행

```powershell
# 의존성 설치 (Microsoft Store Python은 PYTHONNOUSERSITE=1 필수)
.\.venv\Scripts\Activate.ps1
$env:PYTHONNOUSERSITE = "1"
python -m pip install --no-cache-dir -r requirements.txt

# .env 작성 (Google OAuth 키 필요)
Copy-Item .env.example .env
# 편집기로 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 등 채우기

# 기동 (document_repo, rag_file_repo 스키마 자동 생성)
python -m uvicorn main:app --reload --port 8000
```

프론트 (별도 터미널):

```powershell
cd ..\TokForge.io
npm install
npm run dev
```

→ API: http://localhost:8000/docs · UI: http://localhost:5173

상세 셋업: [개발내용/01-quick-start.md](../개발내용/01-quick-start.md)

---

## 📁 디렉토리 구조 (요약)

```
TokForge/
├── main.py                    ← FastAPI 진입점
├── app/
│   ├── config.py              ← 모든 설정 + .env 로드
│   ├── db.py                  ← SQLite 공통 connection
│   ├── api/
│   │   ├── auth.py            ← OAuth + /me
│   │   ├── projects.py        ← 프로젝트 CRUD
│   │   ├── project_rag.py     ← 프로젝트 RAG 파일 API
│   │   ├── project_ai/        ← 개요·대화·organize
│   │   ├── admin.py           ← /admin/status, prompts, RAG
│   │   ├── chat.py            ← /v1/chat/completions (8단계)
│   │   ├── conversations.py   ← TokForgeAI 대화
│   │   └── deps.py            ← CurrentUser, OwnedProject
│   ├── services/
│   │   ├── user_repo.py, session_repo.py, project_repo.py
│   │   ├── document_repo.py   ← project_documents (개요 등)
│   │   ├── rag_file_repo.py   ← project_rag_files 메타
│   │   ├── rag_service.py     ← 업로드·삭제·원본 저장
│   │   ├── rag_document_extract.py  ← PDF/Office 텍스트 추출
│   │   ├── rag_context.py     ← RAG 검색 (TokForgeAI + 개요 AI)
│   │   ├── conversation_repo.py
│   │   ├── prompt_repo.py, refiner.py, compressor.py, router.py
│   │   ├── cache.py, rag.py, monitor.py
│   └── llm/ollama.py          ← Ollama + Azure OpenAI
├── storage/
│   ├── monitor.db             ← SQLite (users, projects, documents, rag_files, …)
│   ├── rag_files/             ← RAG 원본 파일
│   └── rag_index/             ← FAISS 인덱스 (global, project_{id})
├── docs/                      ← 단계별 학습 노트
├── .env / .env.example
└── requirements.txt           ← pypdf, python-docx, python-pptx, openpyxl 포함
```

DDL 참고: [`../테이블스크립트.txt`](../테이블스크립트.txt)

자세한 모듈별 역할: [개발내용/03-backend.md](../개발내용/03-backend.md) · [13-project-rag-overview.md](../개발내용/13-project-rag-overview.md)

---

## 📚 목차

### 🎯 시작하기
- 📖 [1. 프로젝트 개요](docs/01_프로젝트_개요.md) — 목적·핵심 기능·아키텍처
- 🚀 [2. 실행 방법](docs/02_실행_방법.md) — 설치·실행·진단·종료
- 🔌 [3. Continue.dev 연결 설정](docs/03_Continue_연동.md) — VSCode 연동

### 🏗️ 코드 구조
- 📁 [4. 디렉터리 구조](docs/04_디렉터리_구조.md) — 전체 파일 트리
- 🔧 [5. 핵심 모듈 상세](docs/05_핵심_모듈.md) — 컴포넌트별 동작 원리
- 💾 [6. DB 스키마](docs/06_DB_스키마.md) — 캐시·통계·기록 테이블

### 🌐 API/통합
- 📡 [7. API 엔드포인트](docs/07_API_엔드포인트.md) — REST API 레퍼런스
- 📦 [8. 의존성 목록](docs/08_의존성.md) — 라이브러리/외부 도구

### 🛠️ 개발/운영
- 🔌 [9. 확장 개발 가이드](docs/09_확장_가이드.md) — 새 백엔드/단계 추가
- ⚠️ [10. 알려진 이슈](docs/10_이슈_및_미완성.md) — 트러블슈팅
- 📋 [11. 변경 이력](docs/11_변경_이력.md) — 단계별 작업 기록

### 🚧 단계별 개발
- ✅ 1️⃣ [Step 1 — 기본 프록시](docs/step01_기본프록시.md)
- ✅ 2️⃣ [Step 2 — 의미 캐시](docs/step02_의미캐시.md)
- ✅ 3️⃣ [Step 3 — RAG 컨텍스트 주입](docs/step03_RAG.md) (LangChain)
- ✅ 4️⃣ [Step 4 — 프롬프트 템플릿](docs/step04_템플릿.md)
- ✅ 5️⃣ [Step 5 — 질문 정제](docs/step05_정제.md) (LangChain)
- ✅ 6️⃣ [Step 6 — 컨텍스트 압축](docs/step06_압축.md) (LangChain)
- ✅ 7️⃣ [Step 7 — 모델 자동 라우팅](docs/step07_라우팅.md) (LangChain)
- ✅ 8️⃣ [Step 8 — 비용/품질 모니터링](docs/step08_모니터링.md) (자체 구현)

### 📖 인수인계 / 운영 가이드
- 🤝 [개발 인수인계 문서 모음](../개발내용/README.md) — 백엔드/프론트/배포/트러블슈팅 상세
- 📎 [13. 프로젝트 RAG + 개요](../개발내용/13-project-rag-overview.md) — 최신 기능 (2026-05-24)

---

## 📜 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 참고.

저장소: https://github.com/taejin-kim5952/TokForge
