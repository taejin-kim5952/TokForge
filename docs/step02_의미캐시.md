# Step 2 — 의미 캐시 (Semantic Cache)

> **상태**: ✅ 구현 완료 (2026-05-09) / ⏳ 동작 테스트 미진행

## 목표

같거나 **의미가 비슷한 질문** 은 Ollama 호출 없이 즉시 응답한다. 단순 문자열 매칭이 아니라 **임베딩 벡터의 코사인 유사도** 로 판단.

```
"커밋 메시지 작성법"      ┐
"git commit 메시지 어떻게" ├─ 같은 의미로 인식 → 같은 답변 재사용
"커밋 메시지 어케 써"     ┘
```

## 흐름

```
요청 도착
    ↓
1. 마지막 user 메시지 추출
    ↓
2. 캐시 lookup
    ├─ 히트 (유사도 ≥ 0.90)  → 즉시 응답 (Ollama X) ✨
    └─ 미스                   ↓
3. Ollama 호출
    ↓
4. 응답을 캐시에 save
    ↓
5. 사용자에게 응답
```

⚠️ 스트리밍(`stream=true`) 요청은 캐시 우회.

## 추가된 라이브러리

```
sentence-transformers==3.0.0   # 문장 → 384차원 벡터
faiss-cpu==1.13.2              # 벡터 유사도 검색
aiosqlite==0.20.0              # (예약 — 현재는 sqlite3 동기 사용)
```

## 디렉터리 변화

```
app/
  api/
    cache.py        🆕 GET /v1/cache/stats
  services/
    cache.py        🆕 SemanticCache 클래스
storage/            🆕 (자동 생성)
  cache.db          SQLite (질문/응답 텍스트)
  cache.faiss       FAISS (질문 벡터)
```

## 핵심 설계

### 두 저장소를 분리

| 저장소 | 역할 |
|---|---|
| **SQLite** (`cache.db`) | 질문 텍스트 + 응답 dict (JSON 직렬화) |
| **FAISS** (`cache.faiss`) | 질문 임베딩 벡터 |

→ FAISS 의 row 번호와 SQLite 의 `id` 가 동기화되어, 검색 시 FAISS 가 "row N 이 가장 비슷" 이라고 알려주면 SQLite 에서 `id = N+1` 의 응답을 꺼낸다.

### 임베딩 모델

```python
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
```

다국어 지원 (한국어 OK). 입력 한도 128 토큰 ≈ 한국어 200~400자.

### 유사도 판정

```python
SIMILARITY_THRESHOLD = 0.90
```

- 코사인 유사도 0.90 이상 → 캐시 히트
- 미만 → 캐시 미스 (새로 호출 후 저장)

`faiss.IndexFlatIP` (Inner Product) + `normalize_embeddings=True` 조합으로 코사인 유사도 직접 계산.

## 핵심 코드

### [app/services/cache.py](../app/services/cache.py)

```python
class SemanticCache:
    def lookup(self, question: str) -> dict | None:
        if self.index.ntotal == 0:
            return None
        vec = self._embed(question)
        distances, indices = self.index.search(vec, k=1)
        similarity = float(distances[0][0])
        if similarity < SIMILARITY_THRESHOLD:
            return None
        row_id = int(indices[0][0]) + 1
        # SQLite 에서 응답 꺼내서 JSON 디코딩
        ...

    def save(self, question: str, answer: dict):
        # SQLite 에 JSON 직렬화 저장
        # FAISS 에 벡터 추가
        # 인덱스 파일 저장
        ...
```

### [app/api/chat.py](../app/api/chat.py) — 캐시 연결

```python
def _last_user_message(request: dict) -> str | None:
    for msg in reversed(request.get("messages", [])):
        if msg.get("role") == "user":
            return msg.get("content")
    return None

@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    if request.get("stream"):
        return StreamingResponse(...)   # 캐시 우회

    query = _last_user_message(request)
    cache = get_cache()
    if query:
        cached = cache.lookup(query)
        if cached is not None:
            return cached

    response = await ollama.chat_completion(request)
    if query:
        cache.save(query, response)
    return response
```

## 엔드포인트

| 메서드 | 경로 | 응답 |
|---|---|---|
| GET | `/v1/cache/stats` | `{total_cached, index_size, threshold}` |

## 트러블슈팅

### Windows 한글 경로 + FAISS

`D:\튜닝\TokForge\` 처럼 한글이 포함된 경로에서 `faiss.write_index(path)` 가 실패:

```
RuntimeError: ... could not open ... rag.faiss for writing: Illegal byte sequence
```

**우회**: `faiss.serialize_index()` → `bytes` → `Path.write_bytes()` 로 저장.
로드도 `Path.read_bytes()` → `faiss.deserialize_index()`.

```python
def _save_index(self):
    INDEX_PATH.write_bytes(faiss.serialize_index(self.index).tobytes())
```

## 테스트 시나리오

| 단계 | 질문 | 예상 stats | 응답 속도 |
|---|---|---|---|
| 1 | "git commit 메시지 작성법" | total_cached=1 | 느림 (Ollama) |
| 2 | "git commit 메시지 작성법" (동일) | 1 | 즉시 (캐시) |
| 3 | "Java List 사용법" | 2 | 느림 |
| 4 | "자바에서 리스트 어떻게 써" | 2 | **즉시 (의미 캐시)** ⭐ |

## 다음 단계

[Step 3 — RAG](step03_RAG.md)
