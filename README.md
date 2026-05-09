# TokForge — Agent Middleware

> **AI 프롬프트를 최적화해 토큰 사용량을 줄이는 Agent Middleware**

![Version](https://img.shields.io/badge/version-0.1-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-green)
![License](https://img.shields.io/badge/license-MIT-orange)

VSCode + Continue.dev 와 유료 AI API(OpenAI / Anthropic / Gemini) 사이에서 동작하는
로컬 미들웨어입니다. 사용자 질문을 자동으로 정제 · 압축 · 컨텍스트 보강하여,
**더 적은 토큰으로 더 정확한 답변** 을 받을 수 있게 합니다.

모든 최적화 처리는 로컬에서 실행되며, 유료 API 호출 단계에서만 외부와 통신합니다.

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
2. 의미 캐시     같은/비슷한 질문이면 즉시 응답 (API 호출 X)
   ↓
3. RAG 검색      회사 가이드 / 문서 컨텍스트 자동 추가
   ↓
4. 압축          핵심만 남기고 토큰 줄이기
   ↓
5. API 호출      OpenAI / Anthropic / Gemini
   ↓
[답변 + 비용/토큰 기록]
```

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
- 1️⃣ [Step 1 — 기본 프록시](docs/step01_기본프록시.md)
- 2️⃣ [Step 2 — 의미 캐시](docs/step02_의미캐시.md)
- 3️⃣ [Step 3 — RAG 컨텍스트 주입](docs/step03_RAG.md)
- 4️⃣ [Step 4 — 프롬프트 템플릿](docs/step04_템플릿.md)
- 5️⃣ [Step 5 — 질문 정제 (gemma4:e4b)](docs/step05_정제.md)
- 6️⃣ [Step 6 — 컨텍스트 압축](docs/step06_압축.md)
- 7️⃣ [Step 7 — 모델 자동 라우팅](docs/step07_라우팅.md)
- 8️⃣ [Step 8 — 비용/품질 모니터링](docs/step08_모니터링.md)

---

## 📜 라이선스

MIT License — 자세한 내용은 [LICENSE](LICENSE) 참고.

저장소: (GitHub URL — 추후 추가)
