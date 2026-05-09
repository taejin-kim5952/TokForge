# Step 3 — RAG (Retrieval-Augmented Generation)

> **상태**: 🔄 진행 중 (백엔드 완료, chat 통합 미진행, 동작 테스트 일부)
>
> 진행 일자: 2026-05-09

## 목표

질문이 들어오면 **관련 문서 chunk 를 자동 검색** 하여 LLM 컨텍스트로 주입한다.

```
질문: "회사 휴가 정책 알려줘"
        ↓
RAG 검색: "회사규정.txt" 중 휴가 관련 chunk 5개
        ↓
LLM 호출: context + question
        ↓
정확한 답변 (학습 데이터 외 지식도 응답 가능)
```

## Step 2 (캐시) 와의 차이

| | 의미 캐시 (Step 2) | RAG (Step 3) |
|---|---|---|
| 저장 대상 | 질문 ↔ 응답 쌍 | 문서 chunk |
| 목적 | 같은 질문 재호출 방지 | 새 질문에 외부 지식 주입 |
| LLM 호출 | 안 함 (히트 시) | 항상 (단 더 정확) |
| 검색 결과 | top-1 + 임계값 | top-k (k=5), 임계값 없음 |

→ 캐시는 "비슷한 게 있어야 동작", RAG 는 "항상 가장 비슷한 N개 반환".

## 흐름 (계획)

```
[Continue.dev 질문]
    ↓
TokForge: 마지막 user 메시지 추출
    ↓
캐시 확인 (Step 2)
    ↓ (캐시 미스 시)
RAG 검색 → top-k chunk
    ↓
프롬프트 조립:
  system: "다음 문서를 참고하여 답하세요\n\n{chunks}"
  user: 원본 질문
    ↓
Ollama 호출
    ↓
응답 → 캐시 저장 → 사용자
```

## 디렉터리 변화

```
app/
  api/
    rag.py          🆕 업로드/검색/통계 API
  services/
    rag.py          🆕 RAGStore 클래스 + chunk_text()
storage/
  rag.db            🆕 SQLite (chunk 텍스트 + source)
  rag.faiss         🆕 FAISS (chunk 벡터)
```

## 청킹 (Chunking)

긴 문서를 그대로 임베딩하면 **모델 입력 한도(128 토큰)** 를 초과해 정보가 잘린다. 따라서 작은 조각으로 분할.

```python
CHUNK_SIZE = 500       # 한 chunk 의 글자 수
CHUNK_OVERLAP = 50     # chunk 간 겹침 (문맥 유지)
TOP_K = 5              # 검색 시 상위 몇 개를 가져올지

def chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks
```

### CHUNK_SIZE 트레이드오프

| 값 | 장점 | 단점 |
|---|---|---|
| 너무 작음 (~100) | 정밀 매칭 | 의미 단위 깨짐 |
| 적당 (300~800) ⭐ | 의미 + 정밀도 균형 | — |
| 너무 큼 (3000+) | 풍부한 정보 | 임베딩 입력 한도 초과 → 앞부분만 인식 |

⚠️ `CHUNK_SIZE` 는 **저장 시점에 결정**. 한 번 인덱싱하면 변경 시 **전체 재인덱싱** 필요.

### DB 파티션 비유

| DB 파티션 | RAG 청킹 |
|---|---|
| 큰 테이블 → 작은 파티션 분할 | 큰 문서 → 여러 chunk 분할 |
| 파티션 키로 분할 | 글자 수로 분할 |
| 관련 파티션만 스캔 → 빠름 | 관련 chunk 만 LLM 에 전달 → 토큰 절약 |

## 핵심 코드

### [app/services/rag.py](../app/services/rag.py)

```python
class RAGStore:
    def add_document(self, source: str, text: str) -> int:
        chunks = chunk_text(text)
        conn = sqlite3.connect(DB_PATH)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO chunks (source, content) VALUES (?, ?)",
                (source, chunk),
            )
            vec = self._embed(chunk)
            self.index.add(vec)
        conn.commit()
        conn.close()
        self._save_index()
        return len(chunks)

    def search(self, query: str, k: int = TOP_K) -> list[dict]:
        if self.index.ntotal == 0:
            return []
        vec = self._embed(query)
        distances, indices = self.index.search(vec, k=min(k, self.index.ntotal))
        # SQLite 에서 chunk 본문 + 출처 결합해 반환
        ...
```

### [app/api/rag.py](../app/api/rag.py)

```python
ALLOWED_EXTENSIONS = {".txt", ".md"}

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    # 확장자 / UTF-8 / 빈 파일 검증
    # 파일 → 텍스트 → add_document() → chunk 수 반환
    ...

@router.get("/search")
def search_documents(q: str, k: int = 5):
    return {"query": q, "count": len(results), "results": results}

@router.get("/stats")
def rag_stats():
    return get_rag().stats()
```

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/v1/rag/upload` | TXT/MD 파일 업로드 |
| GET  | `/v1/rag/search?q=...&k=5` | 디버깅용 검색 |
| GET  | `/v1/rag/stats` | 통계 (chunk 수, source 수) |

## 동작 확인 (Swagger UI)

1. `http://localhost:8000/docs` 접속
2. `POST /v1/rag/upload` → `test_company.txt` (UTF-8) 업로드
   → `{"chunks_created": N}`
3. `GET /v1/rag/search?q=휴가 며칠`
   → top-k chunk 반환 (정확도 score 포함)
4. `GET /v1/rag/stats`
   → `total_chunks == index_size` 확인 (동기화)

## 남은 작업

- [ ] [chat.py](../app/api/chat.py) 에 RAG 통합
  - 캐시 미스 후, RAG 검색 결과를 system 프롬프트에 주입
  - "참고 문서:\n{chunks}\n\n위 내용을 바탕으로 답변해주세요"
- [ ] 통합 동작 테스트 (문서 업로드 → 그 내용에 대한 질문 → 컨텍스트 기반 답변)
- [ ] (선택) RAG 사용 여부 토글 옵션

## 향후 확장 (이번 단계 범위 밖)

- PDF / DOCX / 웹 URL 지원
- 임베딩 모델 교체 (`bge-m3` 등 — 입력 한도 8192 토큰)
- 메타데이터 필터링 (예: 특정 source 만 검색)
- parent-child chunk (작은 chunk 로 검색, 큰 parent 를 LLM 에 전달)

## 다음 단계

[Step 4 — 프롬프트 템플릿](step04_템플릿.md)
