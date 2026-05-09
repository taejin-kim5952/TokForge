# 7. API 엔드포인트

> Swagger UI: `http://localhost:8000/docs` (실시간 호출 가능). 이 문서는 카탈로그 + 사용 예시.

## 그룹

| 그룹 | 라우터 파일 | 단계 |
|---|---|---|
| default | [api/health.py](../app/api/health.py), [api/chat.py](../app/api/chat.py), [api/models.py](../app/api/models.py) | 1 |
| cache | [api/cache.py](../app/api/cache.py) | 2 |
| rag | [api/rag.py](../app/api/rag.py) | 3 |

---

## 1. default — 기본

### `GET /`

서버 식별. 가장 가벼운 ping.

```bash
curl http://localhost:8000/
```

```json
{ "name": "TokForge", "status": "running" }
```

### `GET /health`

서버 + Ollama 연결 상태.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok", "ollama": "connected" }
```

| 필드 | 값 | 의미 |
|---|---|---|
| `status` | `ok` | TokForge 서버 정상 |
| `ollama` | `connected` / `disconnected` | Ollama 데몬 응답 여부 |

### `POST /v1/chat/completions`

**OpenAI 호환** 채팅. Continue.dev 가 호출하는 메인 API.

#### 요청

```json
{
  "messages": [
    {"role": "system", "content": "당신은 친절한 어시스턴트입니다"},
    {"role": "user", "content": "안녕"}
  ],
  "stream": false
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `messages` | `list[dict]` | 대화 히스토리 (role: `system`/`user`/`assistant`) |
| `stream` | `bool` | true 면 SSE 스트리밍 (캐시 우회) |
| `model` | `str` | 무시됨 — TokForge 가 [config.py](../app/config.py) 의 `DEFAULT_MODEL` 강제 적용 |
| `temperature` | `float` | (선택) Ollama 로 그대로 전달 |

#### 응답 (비스트리밍)

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gemma3:e2b",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "안녕하세요!"},
    "finish_reason": "stop"
  }],
  "usage": { ... }
}
```

#### 동작

```
요청
  ├─ stream=true  → Ollama 스트리밍 그대로 중계 (캐시 X)
  └─ stream=false → 캐시 lookup
                      ├─ 히트 → 즉시 응답
                      └─ 미스 → Ollama 호출 → 캐시 save → 응답
```

### `GET /v1/models`

OpenAI 호환 모델 목록 (Continue 가 모델 선택창에 사용).

```json
{
  "object": "list",
  "data": [
    {"id": "gemma3:e2b", "object": "model", ...}
  ]
}
```

### `GET /v1/models/current`

현재 실제 사용 중인 모델 (TokForge 자체 진단용).

```json
{ "model": "gemma3:e2b" }
```

---

## 2. cache — 의미 캐시 (Step 2)

### `GET /v1/cache/stats`

캐시 저장 현황.

```bash
curl http://localhost:8000/v1/cache/stats
```

```json
{
  "total_cached": 5,
  "index_size": 5,
  "threshold": 0.9
}
```

| 필드 | 의미 | 정상 |
|---|---|---|
| `total_cached` | SQLite row 수 | 채팅 횟수에 따라 증가 |
| `index_size` | FAISS 벡터 수 | `total_cached` 와 동일해야 함 |
| `threshold` | 캐시 히트 유사도 컷오프 | 항상 0.9 ([cache.py](../app/services/cache.py) 상수) |

⚠️ `total_cached ≠ index_size` 이면 SQLite ↔ FAISS 동기화 깨짐. [storage/](../storage/) 삭제 후 재구축 권장.

---

## 3. rag — 검색 증강 (Step 3)

### `POST /v1/rag/upload`

TXT/MD 파일 업로드 → 청킹 → SQLite + FAISS 저장.

#### 요청

`multipart/form-data` 의 `file` 필드.

**Swagger UI**: "Try it out" → "Choose File" → "Execute"

**curl**:
```bash
curl -X POST http://localhost:8000/v1/rag/upload \
  -F "file=@test_company.txt"
```

#### 응답

```json
{
  "filename": "test_company.txt",
  "size_bytes": 612,
  "chunks_created": 1
}
```

#### 검증 + 에러

| 케이스 | HTTP | 응답 |
|---|---|---|
| 정상 | 200 | 위와 같음 |
| 확장자 외 (`.pdf` 등) | 400 | `"지원 형식: .txt, .md ..."` |
| UTF-8 아닌 파일 | 400 | `"UTF-8 인코딩 파일만 지원합니다"` |
| 빈 파일 | 400 | `"빈 파일입니다"` |

### `GET /v1/rag/search`

질문으로 chunk 검색 (디버깅·수동 검증용).

#### 요청 파라미터

| 파라미터 | 타입 | 기본 | 설명 |
|---|---|---|---|
| `q` | str | (필수) | 검색 쿼리 |
| `k` | int | 5 | 가져올 chunk 수 |

```bash
curl "http://localhost:8000/v1/rag/search?q=휴가 며칠&k=3"
```

#### 응답

```json
{
  "query": "휴가 며칠",
  "count": 1,
  "results": [
    {
      "rank": 1,
      "score": 0.78,
      "source": "test_company.txt",
      "content": "회사 휴가 정책\n\n연차는 입사 1년차..."
    }
  ]
}
```

| 필드 | 의미 |
|---|---|
| `rank` | 1부터, 유사도 높은 순 |
| `score` | 코사인 유사도 (1.0 = 완전 일치) |
| `source` | 업로드한 파일 이름 |
| `content` | chunk 본문 (최대 [CHUNK_SIZE](../app/services/rag.py) 자) |

### `GET /v1/rag/stats`

RAG 저장 현황.

```json
{
  "total_chunks": 12,
  "total_sources": 3,
  "index_size": 12,
  "chunk_size": 500,
  "chunk_overlap": 50
}
```

| 필드 | 의미 |
|---|---|
| `total_chunks` | SQLite chunk row 수 |
| `total_sources` | 고유 파일 수 |
| `index_size` | FAISS 벡터 수 (= `total_chunks` 여야 함) |
| `chunk_size` / `chunk_overlap` | 인덱싱 시 사용된 청킹 파라미터 |

---

## 인증

**현재**: 없음. 로컬 전용으로 가정.

⚠️ 외부 노출 시(예: 회사 서버) 반드시 인증 추가. 옵션:
- API Key 헤더 검증
- mTLS
- VPN/방화벽 내부에만 노출

---

## CORS

기본 비활성. 브라우저 기반 클라이언트가 호출 시 [main.py](../main.py) 에 CORS 미들웨어 추가 필요. Continue.dev 는 VSCode 내부 호출이라 CORS 무관.

---

## 향후 추가 예정 (단계별)

| 단계 | 예상 엔드포인트 |
|---|---|
| 4 | `POST /v1/templates`, `GET /v1/templates` |
| 5 | (내부용 — 외부 API 변화 없음) |
| 6 | (내부용) |
| 7 | `GET /v1/routing/stats` |
| 8 | `GET /v1/metrics`, `GET /v1/dashboard` |

---

## 다음 문서

- 📦 [8. 의존성 목록](08_의존성.md)
- 🔧 [5. 핵심 모듈 상세](05_핵심_모듈.md)
- ⚠️ [10. 알려진 이슈](10_이슈_및_미완성.md)
