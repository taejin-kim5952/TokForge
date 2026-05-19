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

## 🔄 처리 파이프라인

```
[사용자 질문]
   ↓
1. 정제          gemma3:1b 로 오타·중복 제거, 의도 명확화
   ↓
2. 의미 캐시     같은/비슷한 질문이면 즉시 응답 (API 호출 X)
   ↓
3. RAG 검색      회사 가이드 / 문서 컨텍스트 자동 추가
   ↓
4. 압축          핵심만 남기고 토큰 줄이기
   ↓
5. 템플릿        정해진 system 프롬프트로 형식 통일 ([Role][Q][Output] 등)
   ↓
6. 모델 라우팅   복잡도 따라 답변 모델 자동 선택 (simple/medium/complex)
   ↓
7. Ollama 호출
   ↓
8. 응답 + 모니터링 기록 (토큰·비용·지연시간 누적)
   ↓
[사용자]
```

각 단계의 프롬프트는 **DB에 버전 저장 + Admin UI에서 재기동 없이 교체** 가능.

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
> Step 1~2 의 직접 구현은 임베딩·FAISS·코사인 유사도 원리를 손에 익히는 학습 자산으로 보존.

### 운영 인프라

| 영역 | 상태 | 구현 |
|---|---|---|
| 프롬프트 버전 관리 | ✅ 완료 | SQLite + Admin UI (4종 × N 버전, 무재기동 교체) |
| Google OAuth 로그인 | ✅ 완료 | Authlib + PKCE + 불투명 세션 토큰 |
| 사용자별 프로젝트 CRUD | ✅ 완료 | SQL `owner_user_id` 격리 보장 |
| Admin Dashboard | ✅ 완료 | Ollama 상태 / 모델 사용 / 단계별 메트릭 / 프롬프트 편집 |
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

# 기동
python -m uvicorn main:app --reload --port 8000
```

→ http://localhost:8000/docs (Swagger UI)

상세 셋업: [개발내용/01-quick-start.md](../개발내용/01-quick-start.md)

---

## 📁 디렉토리 구조 (요약)

```
TokForge/
├── main.py                    ← FastAPI 진입점
├── app/
│   ├── config.py              ← 모든 설정 + .env 로드
│   ├── db.py                  ← SQLite 공통 connection (PRAGMA foreign_keys=ON)
│   ├── api/                   ← HTTP 라우터
│   │   ├── auth.py            ← OAuth (Google) + /me + /logout
│   │   ├── projects.py        ← 사용자 프로젝트 CRUD
│   │   ├── admin.py           ← /admin/status, /admin/prompts/*
│   │   ├── chat.py            ← /v1/chat/completions (8단계 오케스트레이션)
│   │   ├── deps.py            ← CurrentUser dependency
│   │   └── health, cache, rag, prompt, refiner, compressor, router, models, monitor
│   ├── services/              ← Repository + 비즈니스 로직
│   │   ├── user_repo.py, session_repo.py, project_repo.py
│   │   ├── prompt_repo.py     ← 프롬프트 버전 관리
│   │   ├── refiner.py, compressor.py, router.py, prompt.py
│   │   ├── cache.py, rag.py, monitor.py, pricing.py
│   ├── llm/ollama.py          ← Ollama 클라이언트
│   └── observability/langfuse_client.py
├── storage/
│   └── monitor.db             ← 모든 SQLite 데이터 (users, sessions, projects, prompts, requests)
├── docs/                      ← 단계별 학습 노트
├── .env / .env.example
└── requirements.txt
```

자세한 모듈별 역할: [개발내용/03-backend.md](../개발내용/03-backend.md)

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

---

## 📜 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 참고.

저장소: https://github.com/taejin-kim5952/TokForge
