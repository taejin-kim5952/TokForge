# Step 7 — 모델 자동 라우팅 (Model Auto Routing)

> **상태**: ✅ 완료
>
> 진행 일자: 2026-05-11

## 목표

질문의 복잡도를 작은 LLM 으로 판단해서 **적합한 크기의 답변 모델을 자동 선택**한다.
모든 질문에 큰 모델을 쓰는 낭비를 줄이고, 단순 질문에는 빠른 응답을 제공한다.

```
"안녕"                      → simple   → gemma4:e2b    (빠르고 가벼움)
"파이썬 함수 만드는법"        → medium   → gemma4:e2b    (균형)
"FastAPI 마이크로서비스 설계" → complex  → gemma4:latest (정확)
```

## Step 6 까지와의 차이

| | Step 6 까지 | Step 7 |
|---|---|---|
| 답변 모델 | `DEFAULT_MODEL` 고정 | **분류 결과로 동적 선택** |
| 속도 | 모든 질문 같은 속도 | 단순 질문 즉시 응답 |
| 토큰/비용 | 일률적 | 복잡도 비례 |
| 외부 API 확장성 | 어려움 | OpenAI/Anthropic 추가 자연스러움 (Step 8 이후) |

## 흐름

```
[Continue.dev 질문]
    ↓
정제 (Step 5)
    ↓
캐시 lookup (Step 2)
    ↓ (miss)
RAG (Step 3) + 압축 (Step 6) + 템플릿 (Step 4)
    ↓
ModelRouterService.route(query)   ← 새 단계
    ├── in-memory 캐시 hit → 즉시 분류 결과 반환
    └── miss → 분류 LLM 호출 → simple/medium/complex
    ↓
request["model"] = MODEL_TIERS[tier]
    ↓
Ollama 호출 (선택된 모델로)
    ↓
응답 → 캐시 저장 → 사용자
```

## 디렉터리 변화

```
app/
  api/
    chat.py        🔄 _select_model 헬퍼 추가, 흐름 끝에 라우팅 단계 삽입
    router.py      🆕 /router/classify 디버그 엔드포인트
  llm/
    ollama.py      🔄 request["model"] 있으면 그대로, 없으면 DEFAULT 폴백
  services/
    router.py      🆕 ModelRouterService + LangChain PromptTemplate
  config.py        🔄 ENABLE_MODEL_ROUTING, ROUTER_MODEL, MODEL_TIERS 추가
                      모델 식별자 상수(_GEMMA4_SMALL, _GEMMA4_LARGE) 도입
main.py            🔄 router 라우터 등록 (compressor 누락분 함께 보정)
```

## 핵심 개념 — LLM 으로 LLM 선택하기

Step 5/6 의 LLM-of-LLM 패턴이 더 진화한 형태. **하나의 LLM 호출로 어떤 LLM 을 쓸지 결정**.

```python
# 1단계: 작은 LLM 으로 분류
tier = await classifier.classify(query)   # "simple" / "medium" / "complex"

# 2단계: 분류 결과로 모델 선택
model = MODEL_TIERS[tier]                  # 매핑된 답변 모델

# 3단계: 그 모델로 답변
request["model"] = model
response = await ollama.chat_completion(request)
```

→ 모델을 **고정된 자원이 아니라 동적 선택지**로 다룸. Step 8 모니터링에서 효과 측정 후 매핑 조정 가능.

### 분류 프롬프트

```
You are a query complexity classifier. Classify the user's question into exactly one of:
- simple: greetings, basic factual queries, single-line questions
- medium: short code snippets (up to 20 lines), conceptual explanations, typical debugging
- complex: architecture or design decisions, multi-file changes, deep debugging, long generation requests

Rules:
- Output exactly one word: simple, medium, or complex
- No explanation, no punctuation, no quotes, no markdown

Question: {query}
Classification:
```

### 분류 결과 파싱 — `_parse`

LLM 이 깔끔하게 한 단어만 출력하지 않을 수 있음:
- `"simple."` (마침표 붙음)
- `'"medium"'` (따옴표 포함)
- `Classification: complex` (prefix 붙음)
- `simple\nThis is a greeting` (설명 추가)

→ `_parse()` 가 단계적으로 정리:
1. 소문자 변환
2. 따옴표·문장부호 제거
3. 첫 줄만
4. 첫 단어만

### 폴백 — 분류 실패 시

```python
if tier not in ("simple", "medium", "complex"):
    return "medium"     # 안전한 중간값
```

→ LLM 이 헛소리 출력하면 medium 으로 폴백. 그래도 `MODEL_TIERS["medium"]` 매핑이 있으니 동작 보장.

### 모델 식별자 상수화

```python
_GEMMA4_SMALL = "gemma4:e2b"
_GEMMA4_LARGE = "gemma4:latest"

DEFAULT_MODEL = _GEMMA4_SMALL
REFINER_MODEL = _GEMMA4_LARGE
COMPRESSOR_MODEL = _GEMMA4_LARGE
ROUTER_MODEL = _GEMMA4_LARGE
MODEL_TIERS = {
    "simple":  _GEMMA4_SMALL,
    "medium":  _GEMMA4_SMALL,
    "complex": _GEMMA4_LARGE,
}
```

→ 같은 모델 문자열이 5곳 이상 등장 → 상수로 추출. 모델 교체 시 한 줄만 변경.

## 핵심 코드

### [app/services/router.py](../app/services/router.py)

```python
class ModelRouterService:
    def __init__(self) -> None:
        self._template = PromptTemplate.from_template(CLASSIFIER_TEMPLATE)
        self._cache: dict[str, str] = {}

    async def route(self, query: str) -> tuple[str, str]:
        if not query.strip():
            return ("simple", MODEL_TIERS.get("simple", DEFAULT_MODEL))
        tier = await self._classify(query)
        model = MODEL_TIERS.get(tier, DEFAULT_MODEL)
        return (tier, model)

    async def _classify(self, query: str) -> str:
        cached = self._cache.get(query)
        if cached:
            return cached
        try:
            raw = await self._call_ollama(self._template.format(query=query))
        except Exception:
            return "medium"
        tier = self._parse(raw)
        if tier not in ("simple", "medium", "complex"):
            return "medium"
        self._cache[query] = tier
        return tier
```

### [app/api/chat.py](../app/api/chat.py)

```python
async def _select_model(query: str | None, request: dict) -> None:
    if not ENABLE_MODEL_ROUTING:
        return
    tier, model = await get_model_router().route(query or "")
    request["model"] = model
    print(f"[ROUTER] tier={tier} model={model}", flush=True)


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    query = await _refine_query(request)                    # Step 5
    if request.get("stream"):
        context = _build_context(query or "")
        context = await _compress_context(query or "", context)   # Step 6
        _apply_template(request, context)                          # Step 4
        await _select_model(query, request)                        # Step 7
        return StreamingResponse(...)
    # 비스트리밍 + 캐시 + 풀 파이프라인 + 라우팅
    ...
```

### [app/llm/ollama.py](../app/llm/ollama.py)

```python
def _ensure_model(request: dict) -> None:
    """request 에 model 이 없으면 DEFAULT_MODEL 설정."""
    if not request.get("model"):
        request["model"] = DEFAULT_MODEL


async def chat_completion(request: dict) -> dict:
    _ensure_model(request)
    ...
```

→ 이전엔 `request["model"] = DEFAULT_MODEL` 로 무조건 덮어썼음. 이제 라우터가 정한 모델을 존중.

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/router/classify?q=...` | 분류 결과(tier) 와 선택된 모델 반환 |

## 동작 확인

1. `http://localhost:8000/docs` → `/router/classify` 노출 확인
2. 분류 시연:
   - `GET /router/classify?q=안녕` → `{"tier": "simple", "model": "gemma4:e2b"}`
   - `GET /router/classify?q=fastapi 라우터 추가법` → `{"tier": "medium", ...}`
   - `GET /router/classify?q=마이크로서비스 아키텍처 설계` → `{"tier": "complex", "model": "gemma4:latest"}`
3. 실제 채팅 (VSCode + Continue.dev):
   - 서버 콘솔에 `[ROUTER] tier=... model=...` 로그
   - 단순 질문은 즉시, 복잡한 질문은 큰 모델 호출
4. 토글 OFF (`ENABLE_MODEL_ROUTING = False`) 후 재시작:
   - 항상 `DEFAULT_MODEL` 로 폴백 (Step 6 동작과 동일)

## 남은 작업

- [ ] 분류 정확도 측정 — 100개 샘플 수동 분류 vs 자동 분류 비교
- [ ] medium 티어를 차별화 (예: `qwen3.5:4b`) 후 답변 품질·속도 측정
- [ ] 외부 API (OpenAI, Anthropic) 를 새 티어로 추가 — 더 큰 위임 가능

## 향후 확장 (이번 단계 범위 밖)

- 다중 차원 분류 (복잡도 + 카테고리: 코드/설명/디버깅 등) — Step 4 다중 템플릿과 결합
- 비용 인지 라우팅 — 사용자 예산 한도 내에서 자동 다운그레이드
- 분류기 자체를 fine-tuned 작은 모델로 교체 — 정확도·속도 동시 향상
- LangChain `RunnableBranch` 도입 — 동시 다중 chain 실행 후 best 선택

## 다음 단계

[Step 8 — 비용/품질 모니터링](step08_모니터링.md)
