# 7. API 엔드포인트

> Swagger UI: `http://localhost:8000/docs` (실시간 호출 가능). 이 문서는 카탈로그 + 사용 예시.

## 그룹 한눈에

| 그룹 | prefix | 인증 | 단계/기능 |
|---|---|---|---|
| **default** | (없음) | 무 | health, models |
| **chat** | `/v1` | 무 (현재) | OpenAI 호환 채팅 |
| **cache** | `/v1/cache` | 무 | 의미 캐시 (Step 2) |
| **rag** | `/v1/rag` | 무 | RAG 문서 (Step 3) |
| **prompt** | `/prompt` | 무 | 프롬프트 템플릿 preview (Step 4) |
| **refiner** | `/refiner` | 무 | 정제 단독 호출 (Step 5) |
| **compressor** | `/compressor` | 무 | 압축 단독 호출 (Step 6) |
| **router** | `/router` | 무 | 라우팅 단독 호출 (Step 7) |
| **monitor** | `/monitor` | 무 | 모니터링 통계 (Step 8) |
| **admin** | `/admin` | **무 (운영 진입 전 보호 필요)** | 시스템 상태 + 프롬프트 관리 |
| **auth** | (혼합) | 무 → 인증 발급 | Google OAuth + /me + /logout |
| **projects** | `/projects` | ✅ 필수 | 사용자 프로젝트 CRUD |

---

## 1. default — 기본

### `GET /healthz`

서버 + Ollama 연결 상태.

```bash
curl http://localhost:8000/healthz
```

```json
{ "status": "ok", "ollama": "connected" }
```

### `POST /v1/chat/completions`

**OpenAI 호환** 채팅 + TokForge 8단계 파이프라인.

#### 요청

```json
{
  "messages": [
    {"role": "user", "content": "안녕"}
  ],
  "stream": false,
  "pipeline": {                  // TokForge 전용 (선택)
    "refine": true,
    "cache": true,
    "rag": true,
    "compress": true,
    "template": true,
    "route": true
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `messages` | `list[dict]` | 대화 히스토리 |
| `stream` | `bool` | true 면 SSE 스트리밍 |
| `model` | `str` | 라우팅이 켜져 있으면 자동 덮어씀 (`pipeline.route=false`로 보존 가능) |
| `temperature` | `float` | Ollama에 그대로 전달 |
| `pipeline` | `dict` | 단계별 토글 (TokForge 전용) |

#### 응답 (비스트리밍)

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gemma4:e2b",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "안녕하세요!"},
    "finish_reason": "stop"
  }],
  "usage": { ... }
}
```

#### 응답 (스트리밍)

OpenAI 표준 SSE 청크 + 커스텀 `pipeline` 이벤트 (`event` 필드 있는 청크는 OpenAI 호환 클라이언트가 무시).

#### 동작 흐름

상세는 [step01-step08 학습 노트](step01_기본프록시.md) 또는 [개발내용/07-pipeline.md](../../개발내용/07-pipeline.md):

```
요청 → 정제 → 캐시 lookup → (hit이면 즉시 반환)
            → RAG → 압축 → 템플릿 → 라우팅 → Ollama → 캐시 save → 응답
```

### `GET /v1/models`

OpenAI 호환 모델 목록 (Continue가 모델 선택창에 사용).

```json
{
  "object": "list",
  "data": [
    {"id": "gemma4:e2b", "object": "model", ...},
    {"id": "gemma4:latest", "object": "model", ...}
  ]
}
```

### `GET /v1/models/current`

TokForge 자체 진단용.

```json
{ "model": "gemma4:e2b" }
```

---

## 2. cache — 의미 캐시 (Step 2)

### `GET /v1/cache/stats`

```json
{ "total_cached": 5, "index_size": 5, "threshold": 0.9 }
```

| 필드 | 의미 |
|---|---|
| `total_cached` | SQLite row 수 |
| `index_size` | FAISS 벡터 수 (= total_cached) |
| `threshold` | 히트 유사도 컷오프 |

⚠️ `total_cached ≠ index_size` 이면 SQLite ↔ FAISS 동기화 깨짐. `storage/` 정리 후 재구축.

---

## 3. rag — 검색 증강 (Step 3)

### `POST /v1/rag/upload`

`multipart/form-data` 의 `file` 필드. TXT/MD 만.

```bash
curl -X POST http://localhost:8000/v1/rag/upload -F "file=@docs.txt"
```

응답: `{"filename": "...", "size_bytes": ..., "chunks_created": ...}`

### `GET /v1/rag/search?q=...&k=5`

디버깅용 — 질문으로 chunk top-k 검색.

### `GET /v1/rag/stats`

```json
{
  "total_chunks": 12,
  "total_sources": 3,
  "index_size": 12,
  "chunk_size": 500,
  "chunk_overlap": 50
}
```

---

## 4. prompt / refiner / compressor / router — 단계 단독 호출 (디버깅용)

각 단계를 개별 호출 가능. 디버깅·테스트에 유용.

```bash
# 정제만
curl -X POST http://localhost:8000/refiner -d '{"query":"안녕"}'

# 압축만
curl -X POST http://localhost:8000/compressor \
  -d '{"query":"...", "context":"..."}'

# 라우팅만 (복잡도 분류)
curl -X POST http://localhost:8000/router \
  -d '{"query":"complex architecture question"}'
```

상세는 각 step 학습 노트 참조.

---

## 5. monitor — 모니터링 (Step 8)

### `GET /monitor/stats`

전체 통계.

```json
{
  "total_requests": 42,
  "cache_hits": 8,
  "cache_hit_rate": 0.19,
  "refined_count": 38,
  "refined_rate": 0.90,
  "avg_latency_ms": 1820,
  "error_count": 0,
  "avg_refine_ms": 150,
  "avg_cache_ms": 45,
  "avg_rag_ms": 80,
  "avg_compress_ms": 720,
  "avg_template_ms": 2,
  "avg_route_ms": 450
}
```

### `GET /monitor/recent?limit=10`

최근 N개 요청 상세 (Admin Dashboard "최근 요청" 테이블 소스).

---

## 6. admin — 관리자

⚠️ **현재 인증 없음 (public).** 운영 진입 전 PrivateRoute + admin role 필수.

### `GET /admin/status`

시스템 상태 한 번에.

```json
{
  "ollama": {
    "url": "http://localhost:11434",
    "connected": true,
    "models": ["gemma3:1b", "gemma4:e2b", "gemma4:latest"]
  },
  "models_in_use": {
    "refiner": "gemma3:1b",
    "compressor": "gemma4:latest",
    "router": "gemma4:latest",
    "default": "gemma4:e2b"
  },
  "stages_enabled": {
    "refine": true,
    "compress": true,
    "template": true,
    "route": true,
    "monitoring": true
  },
  "stats": { ... }
}
```

### `GET /admin/prompts` — 4종 프롬프트 요약

```json
{
  "kinds": [
    {"kind": "refiner",    "active_version": 2, "total_versions": 3},
    {"kind": "classifier", "active_version": 1, "total_versions": 1},
    {"kind": "compressor", "active_version": 1, "total_versions": 1},
    {"kind": "system",     "active_version": 1, "total_versions": 1}
  ]
}
```

### `GET /admin/prompts/{kind}` — 특정 kind의 모든 버전

```json
{
  "kind": "refiner",
  "versions": [
    {"id": 5, "version": 3, "is_active": 0, "created_at": "...", "note": "더 짧게", "body_length": 320},
    {"id": 4, "version": 2, "is_active": 1, "created_at": "...", "note": "v2 한국어 강화", "body_length": 380},
    {"id": 1, "version": 1, "is_active": 0, "created_at": "...", "note": "seeded", "body_length": 425}
  ]
}
```

### `GET /admin/prompts/{kind}/{version}` — 특정 버전 본문 포함

```json
{
  "id": 4,
  "kind": "refiner",
  "version": 2,
  "body": "You are a query refiner. ...",
  "is_active": 1,
  "created_at": "...",
  "note": "v2 한국어 강화"
}
```

### `POST /admin/prompts/{kind}` — 새 버전 생성

요청:
```json
{
  "body": "You are a query refiner. ...",
  "note": "v3 더 짧게"
}
```

응답 (201):
```json
{ "id": 6, "version": 3 }
```

→ 새 버전은 `is_active=0`. 별도 activate 호출 필요.

### `POST /admin/prompts/{kind}/{version}/activate`

지정 버전 활성화 (같은 kind 다른 버전은 자동 비활성).

```json
{ "ok": true }
```

### `DELETE /admin/prompts/{kind}/{version}`

⚠️ **활성 버전은 삭제 거부** (400). 다른 버전 먼저 활성화 후 삭제.

상세는 [개발내용/08-prompt-management.md](../../개발내용/08-prompt-management.md).

---

## 7. auth — Google OAuth + 세션

### `GET /auth/google/login?return_to=/projects`

OAuth 시작. PKCE state 발급 후 Google authorize 화면으로 302.

브라우저로 직접 접근 (curl 부적합 — redirect dance).

### `GET /auth/google/callback?code=...&state=...`

Google이 호출. 토큰 교환 + 사용자 upsert + 세션 발급 + 프론트로 redirect.

응답: 302 with `Set-Cookie: tf_session=...`

### `POST /auth/logout`

세션 삭제 + 쿠키 정리. 멱등.

```bash
curl -X POST -b "tf_session=xxx" http://localhost:8000/auth/logout
# → {"ok": true}
```

### `GET /me`

현재 인증된 사용자 정보. **인증 필요**.

```bash
curl -b "tf_session=xxx" http://localhost:8000/me
```

```json
{
  "id": 1,
  "email": "user@gmail.com",
  "name": "김태진",
  "picture_url": "https://lh3.googleusercontent.com/...",
  "created_at": "2026-05-18T12:30:56...",
  "last_login_at": "2026-05-18T12:30:56..."
}
```

| 상태 | HTTP | 응답 |
|---|---|---|
| 인증됨 | 200 | user JSON |
| 미인증 / 만료 | 401 | `{"detail": "not authenticated" 또는 "session expired"}` |

상세 OAuth 흐름: [개발내용/06-authentication.md](../../개발내용/06-authentication.md).

---

## 8. projects — 사용자 프로젝트 (Step Auth/Projects 단계)

**모두 인증 필수** (`CurrentUser` dependency). 격리 보장 — 본인 프로젝트만 보임/조작.

### `GET /projects`

본인 프로젝트 목록 (최신순).

```json
{
  "projects": [
    {"id": 2, "name": "rag-bot", "description": "...", "created_at": "...", "updated_at": "..."},
    {"id": 1, "name": "summarizer", "description": null, "created_at": "...", "updated_at": "..."}
  ]
}
```

### `POST /projects`

새 프로젝트 생성.

요청:
```json
{
  "name": "new-project",
  "description": "(선택) 짧은 설명"
}
```

응답 (201):
```json
{ "id": 3, "name": "new-project", "description": "...", "created_at": "...", "updated_at": "..." }
```

| 에러 | HTTP | 사유 |
|---|---|---|
| 빈 name | 422 | Pydantic 검증 |
| 같은 user에 같은 이름 | 409 | UNIQUE(owner_user_id, name) |

### `DELETE /projects/{project_id}`

본인 프로젝트 삭제.

```json
{ "ok": true }
```

| 에러 | HTTP | 사유 |
|---|---|---|
| 존재 안 함 또는 남의 것 | **404** | 존재 자체 은닉 (보안) |

---

## 인증 방식

| 방식 | 위치 | 용도 |
|---|---|---|
| HTTP-only cookie | `tf_session=...` | 모든 인증 필수 엔드포인트 (`/me`, `/projects/*`) |
| `credentials: 'include'` | fetch 옵션 | 프론트가 cross-origin 호출 시 |

CORS 설정 (`main.py`): `allow_credentials=True` + 명시적 origin 목록. `allow_origins=["*"]` 금지 (credentials와 충돌).

---

## CORS

허용 origin (`main.py`):
- `http://localhost:5173` (Vite dev)
- `https://tokforge-frontend.blackrock-...azurecontainerapps.io`
- `https://www.tokforge.ai.kr`

브라우저 외 도구 (Continue, curl)는 CORS 영향 없음.

---

## 단계별 활성화 토글 (전역)

`app/config.py`:

```python
ENABLE_QUERY_REFINEMENT = True
ENABLE_CONTEXT_COMPRESSION = True
ENABLE_MODEL_ROUTING = True
ENABLE_PROMPT_TEMPLATE = True
ENABLE_MONITORING = True
```

각 단계의 요청별 토글은 `pipeline.<key>` (chat 요청 body).

---

## 다음 문서

- 📦 [8. 의존성 목록](08_의존성.md)
- 🔧 [5. 핵심 모듈 상세](05_핵심_모듈.md)
- ⚠️ [10. 알려진 이슈](10_이슈_및_미완성.md)
- 🤝 [개발내용/06-authentication.md](../../개발내용/06-authentication.md) — OAuth 흐름 상세
- 🤝 [개발내용/08-prompt-management.md](../../개발내용/08-prompt-management.md) — Prompt 시스템 상세
