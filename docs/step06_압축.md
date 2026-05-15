# Step 6 — 컨텍스트 압축 (Context Compression)

> **상태**: ✅ 완료
>
> 진행 일자: 2026-05-11

## 목표

RAG 검색으로 가져온 청크들을 **질문과 직접 관련된 부분만 남기도록** 압축한다.
LLM 입력 토큰을 줄이고 모델의 집중도를 높여 답변 품질을 향상시킨다.

```
RAG 청크 3개 (총 1500자)
        ↓ 압축 LLM (gemma4:latest)
질문 관련 핵심만 (300자)
        ↓
[80% 토큰 절감 + LLM 집중도 ↑]
```

## Step 5 까지와의 차이

| | Step 5 까지 | Step 6 |
|---|---|---|
| RAG 결과 처리 | 가져온 청크 그대로 LLM 전달 | 질문 관련 부분만 추출 후 전달 |
| 입력 토큰 | RAG 결과 전체 | 압축본 (보통 10~30%) |
| LLM 집중도 | 무관한 문장도 같이 봄 | 핵심만 봄 → 답변 정확도 ↑ |
| 추가 비용 | 없음 | 압축 LLM 호출 1회 (캐시로 amortize) |

→ Step 5 가 "입력 정규화", Step 6 은 "노이즈 제거".

## 흐름

```
[Continue.dev 질문]
    ↓
정제 (Step 5) → 정제된 query
    ↓
캐시 lookup (Step 2)
    ↓ (miss)
RAG 검색 (Step 3) → 청크 N개 → context 문자열
    ↓
ContextCompressorService.compress(query, context)
    ├── in-memory 캐시 hit → 즉시 반환
    └── miss → LLM 호출 → 검증 → 캐시 저장
    ↓
압축된 context (또는 빈 문자열)
    ↓
프롬프트 템플릿 (Step 4)
    ↓
Ollama (DEFAULT_MODEL) 호출
    ↓
응답 → 캐시 저장 → 사용자
```

## 디렉터리 변화

```
app/
  api/
    chat.py             🔄 _compress_context 헬퍼 추가, 흐름에 압축 단계 삽입
    compressor.py       🆕 /compressor/compress 디버그 엔드포인트
  services/
    compressor.py       🆕 ContextCompressorService + LangChain PromptTemplate
  config.py             🔄 ENABLE_CONTEXT_COMPRESSION, COMPRESSOR_MODEL 추가
main.py                 🔄 compressor 라우터 등록
```

## 핵심 개념 — 단일 LLM 호출 방식

LangChain 에는 `ContextualCompressionRetriever`, `LLMChainExtractor` 등 압축 전용 추상화가 있지만, 이번 단계는 **단순 한 번의 LLM 호출**로 구현했다.

| 방식 | 장점 | 단점 |
|---|---|---|
| **단일 호출** (현재) | 단순, 빠름, 청크 간 관계 보면서 판단 | 청크 많을 때 컨텍스트 한도 위험 |
| `LLMChainExtractor` (청크별) | 병렬화 가능 | 청크 수만큼 LLM 호출 (3배 비용) |
| `EmbeddingsFilter` | LLM 호출 0회 | 의미는 정확히 못 봄 |

→ 단순 한 번의 호출이 비용·효과 균형 측면에서 MVP 에 적합.

### 압축 프롬프트

```
You are a context compressor. Given a user question and reference documents,
extract ONLY the information needed to answer the question.

Rules:
- Keep facts, code snippets, and concrete details that directly relate to the question
- Drop unrelated paragraphs entirely
- Preserve source attribution if present
- Use the same language as the reference documents
- Output the compressed context only — no explanation, no preamble
- If nothing in the documents is relevant, output exactly: (no relevant context)

Question: {query}

Reference documents:
{context}

Compressed context:
```

### 안전장치 — 3단계 폴백

```python
try:
    raw = await self._call_ollama(prompt)
except Exception:
    return context             # 1) 네트워크/모델 에러 → 원본

compressed = raw.strip()
if compressed.startswith("(no relevant context)"):
    return ""                  # 2) 관련 없음 sentinel → 빈 컨텍스트

if not self._is_valid(...):
    return context             # 3) 길이 비율 이상 → 원본 폴백
```

→ 정제(Step 5) 와 같은 3단계 안전망. 새 단계가 기존 답변을 망가뜨리지 않게.

### 정상성 임계값 (압축 vs 정제 비교)

| 단계 | min ratio | max ratio | 의도 |
|---|---|---|---|
| 정제 (Step 5) | 0.3 | 3.0 | 비슷한 길이 유지 |
| **압축 (Step 6)** | **0.05** | **1.2** | **적극적으로 줄어야 정상** |

→ max ratio 1.2 인 이유: 정상 압축이라면 절대 늘어나선 안 됨. 늘어났다면 LLM 이 설명을 추가했을 가능성 → 폴백.

### 캐시 키 설계 — SHA1 해시

```python
def _make_key(query: str, context: str) -> str:
    h = hashlib.sha1()
    h.update(query.encode("utf-8"))
    h.update(b"\x00")           # 구분자
    h.update(context.encode("utf-8"))
    return h.hexdigest()
```

- dict 키로 `(query, context)` 튜플을 직접 쓰면 context 수천 자가 메모리·비교 비용으로 누적
- SHA1 해시 = 40자 고정 → 키로 적합
- `\x00` 구분자로 `"a"+"bc"` 와 `"ab"+"c"` 충돌 방지

## 핵심 코드

### [app/services/compressor.py](../app/services/compressor.py)

```python
class ContextCompressorService:
    def __init__(self) -> None:
        self._template = PromptTemplate.from_template(COMPRESSOR_TEMPLATE)
        self._cache: dict[str, str] = {}

    async def compress(self, query: str, context: str) -> str:
        if not context.strip() or not query.strip():
            return context
        cache_key = self._make_key(query, context)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            raw = await self._call_ollama(self._template.format(query=query, context=context))
        except Exception:
            return context
        compressed = raw.strip()
        if compressed.lower().startswith("(no relevant context)"):
            self._cache[cache_key] = ""
            return ""
        if not self._is_valid(context, compressed):
            return context
        self._cache[cache_key] = compressed
        return compressed
```

### [app/api/chat.py](../app/api/chat.py)

```python
async def _compress_context(query: str, context: str) -> str:
    if not ENABLE_CONTEXT_COMPRESSION or not context:
        return context
    return await get_compressor().compress(query, context)


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    query = await _refine_query(request)                    # Step 5
    if request.get("stream"):
        context = _build_context(query or "")
        context = await _compress_context(query or "", context)  # Step 6
        _apply_template(request, context)                    # Step 4
        return StreamingResponse(...)
    # 비스트리밍 + 캐시 + 풀 파이프라인
    ...
```

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/compressor/compress?q=...&k=3` | RAG 검색 → 압축 흐름 실행 후 before/after 비교 반환 |

## 동작 확인

1. `http://localhost:8000/docs` → `/compressor/compress` 노출 확인
2. 압축 효과:
   - `GET /compressor/compress?q=fastapi 라우터`
   - 응답에 `original_chars`, `compressed_chars`, `compression_ratio` 확인
   - 비율이 0.3 미만이면 70% 이상 토큰 절감
3. 서버 콘솔에 `[COMPRESSOR] compressed N → M chars (X%)` 로그
4. 토글 OFF (`ENABLE_CONTEXT_COMPRESSION = False`) 후 서버 재시작:
   - 압축 단계 건너뛰고 Step 5 동작과 동일

## 남은 작업

- [ ] 압축 모델 변경 시 효과 비교 (gemma4:latest vs qwen3.5:4b vs gemma3:1b)
- [ ] 청크별 압축(`LLMChainExtractor`) 대안 평가 — 청크 수 많을 때 유리한지
- [ ] 압축 캐시를 SQLite 로 격상 — Step 8 모니터링과 함께
- [ ] 압축률 vs 답변 정확도 트레이드오프 측정

## 향후 확장 (이번 단계 범위 밖)

- LangChain `ContextualCompressionRetriever` + `EmbeddingsFilter` 1차 필터 + LLM 2차 추출 (계층 압축)
- 동적 압축률 — 컨텍스트 길이가 임계값 넘을 때만 압축
- 압축 품질 평가 — 압축 후에도 핵심 정보가 보존됐는지 자동 검증
- 멀티 쿼리 압축 — 대화 컨텍스트(여러 query) 를 한 번에 압축

## 다음 단계

[Step 7 — 모델 자동 라우팅](step07_라우팅.md)
