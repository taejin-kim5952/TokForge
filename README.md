# TokForge — Agent Middleware

> **AI 프롬프트를 최적화해 토큰 사용량을 줄이는 Agent Middleware**

![Version](https://img.shields.io/badge/version-0.1-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**LLM 호출을 자동으로 최적화하는 로컬 미들웨어.**
AI 클라이언트와 모델 사이에서 요청을 가로채 캐시·검색·정제 파이프라인을 거치게 합니다.
결과적으로 토큰 비용은 줄고 응답 품질은 보존됩니다.

---

## 🎯 미션

> **프롬프트를 최적화하여 토큰을 절감하고 답변 정확도를 높이며,
> 흐름과 통계 시각화로 지속 개선한다.**

---

## 🔄 처리 파이프라인

```
[사용자 질문]
   ↓
1. 정제          gemma4:e4b 로 오타·중복 제거, 의도 명확화
   ↓
2. 규격화        정해진 템플릿에 맞춰 형식 통일 ([Role][Q][Output] 등)
   ↓
3. 의미 캐시     같은/비슷한 질문이면 즉시 응답 (API 호출 X)
   ↓
4. RAG 검색      회사 가이드 / 문서 컨텍스트 자동 추가
   ↓
5. 압축          핵심만 남기고 토큰 줄이기
   ↓
6. 모델 라우팅   복잡도 따라 백엔드 자동 선택 (Ollama / OpenAI / Anthropic / Gemini)
   ↓
7. API 호출
   ↓
8. 응답 + 모니터링 기록 (토큰·비용·지연시간 누적)
   ↓
[사용자]
```

---

## ✅ 현재 진행 상황

| 단계 | 기능 | 상태 | 구현 방식 |
|---|---|---|---|
| 1 | 기본 프록시 | ✅ 완료 | 직접 구현 (FastAPI + httpx) |
| 2 | 의미 캐시 | ✅ 완료 | 직접 구현 (sentence-transformers + FAISS) |
| 3 | RAG 컨텍스트 주입 | ✅ 완료 | **LangChain** (FAISS + HuggingFace) |
| 4 | 프롬프트 템플릿 (규격화) | ⏳ 예정 | LangChain (ChatPromptTemplate) |
| 5 | 질문 정제 (gemma4:latest) | ✅ 완료 | **LangChain** (PromptTemplate) |
| 6 | 컨텍스트 압축 | ✅ 완료 | **LangChain** (PromptTemplate) |
| 7 | 모델 자동 라우팅 | ✅ 완료 | **LangChain** (PromptTemplate) |
| 8 | 비용/품질 모니터링 | ✅ 완료 | **자체 구현** (SQLite + 집계 API) |

> **설계 원칙**: Step 1~2 는 학습 목적의 직접 구현, Step 3 부터는 LangChain 도입.
> Step 1~2 의 직접 구현은 임베딩·FAISS·코사인 유사도 원리를 손에 익히는 학습 자산으로 보존.

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
- ⏳ 4️⃣ [Step 4 — 프롬프트 템플릿](docs/step04_템플릿.md)
- ✅ 5️⃣ [Step 5 — 질문 정제](docs/step05_정제.md) (LangChain)
- ✅ 6️⃣ [Step 6 — 컨텍스트 압축](docs/step06_압축.md) (LangChain)
- ✅ 7️⃣ [Step 7 — 모델 자동 라우팅](docs/step07_라우팅.md) (LangChain)
- ✅ 8️⃣ [Step 8 — 비용/품질 모니터링](docs/step08_모니터링.md) (자체 구현)

---

## 📜 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 참고.

저장소: https://github.com/taejin-kim5952/TokForge
