# Step 5 — 질문 정제 (Query Refinement)

> **상태**: ✅ 완료
>
> 진행 일자: 2026-05-11

## 목표

작은 LLM(`gemma4:latest`)으로 사용자 raw 질문을 **오타 정정, 중복 제거, 의도 명확화**하여
downstream 의 모든 단계(캐시·RAG·답변 LLM)가 더 정확하게 동작하게 한다.

```
사용자: "fastapi 로터 추가법"   ← 오타 + 비격식
            ↓ 정제 (gemma4:latest)
정제본: "fastapi 라우터 추가하는 방법"
            ↓
캐시 lookup · RAG 검색 · 답변 LLM 모두 정제본 사용
            ↓
[정확한 답변]
```

## Step 4 까지와의 차이

| | Step 4 까지 | Step 5 |
|---|---|---|
| RAG 검색 키 | 사용자 raw 입력 | 정제된 query |
| 캐시 키 | 사용자 raw 입력 | 정제된 query (같은 의도 → 같은 캐시 hit) |
| 답변 LLM 입력 | raw user message | 정제된 user message |
| 오타 대응 | 모델 운에 의존 | 정제 단계가 사전 교정 |

→ Step 4 가 "정책 강제", Step 5 는 "입력 정규화".

## 흐름

```
[Continue.dev 질문]
    ↓
TokForge: 마지막 user 메시지 추출
    ↓
Refiner (gemma4:latest) 호출
    ├── in-memory 캐시 hit → 즉시 반환
    └── miss → LLM 호출 → 검증 → 캐시 저장
    ↓
request.messages 의 user content 가 정제본으로 교체
    ↓
캐시 lookup (Step 2) ← 정제된 query 가 키
    ↓ (miss)
RAG 검색 (Step 3) ← 정제된 query 로 검색
    ↓
프롬프트 템플릿 (Step 4)
    ↓
Ollama (DEFAULT_MODEL) 호출
    ↓
응답 → 캐시 저장 (정제된 query → 응답) → 사용자
```

## 디렉터리 변화

```
app/
  api/
    chat.py         🔄 _refine_query 단계 추가, _build_context(query) 시그니처 변경
    refiner.py      🆕 /refiner/refine 디버그 엔드포인트
  services/
    refiner.py      🆕 QueryRefinerService + LangChain PromptTemplate
  config.py         🔄 ENABLE_QUERY_REFINEMENT, REFINER_MODEL 추가
main.py             🔄 refiner 라우터 등록
```

## 핵심 개념 — LLM-of-LLM 패턴

**같은 LLM 인프라(Ollama) 를 두 번 사용**한다.

| 호출 | 모델 | 목적 | temperature |
|---|---|---|---|
| 정제 | `REFINER_MODEL` (작은/빠른) | 결정론적 정규화 | 0.0 |
| 답변 | `DEFAULT_MODEL` (메인) | 창의적 답변 | (기본값) |

→ "LLM 의 LLM 활용" — 모델을 단순 답변 도구가 아니라 **전처리 파이프라인의 부품**으로 사용.

### 정제 프롬프트

```
You are a query refiner. Clean up the user's question for downstream LLM processing.

Rules:
- Fix typos and grammatical errors
- Remove redundancy and filler words
- Make implicit intent explicit
- Keep the same language as the original
- Return ONLY the refined question — no explanations, no prefixes
- Output should be a single line

Original: {query}
Refined:
```

### 안전장치 — 3단계 폴백

```python
try:
    raw = await self._call_ollama(prompt)
except Exception:
    return query              # 1) 네트워크/모델 에러

refined = self._clean(raw)    # 2) prefix·따옴표·다중줄 제거
if not self._is_valid(...):   # 3) 길이 비율 0.3~3.0 외면 폴백
    return query
```

→ 정제 단계 어디서 망가져도 사용자는 평상시처럼 답변 받음.

### 정상성 판단 임계값 트레이드오프

| 임계값 | 너무 엄격 | 너무 관대 |
|---|---|---|
| 길이 비율 | 정상 정제도 폴백 → 효과 없음 | 이상 출력도 통과 → 답변 망가짐 |
| 권장 | 0.3 ~ 3.0 (현재) | — |

⚠️ `gemma4:latest` 같은 큰 모델은 가끔 "Refined:" prefix 를 붙이거나 설명을 추가함.
`_clean()` 이 흔한 패턴을 제거하지만, 새 모델 도입 시 한 번 점검 필요.

## 핵심 코드

### [app/services/refiner.py](../app/services/refiner.py)

```python
class QueryRefinerService:
    def __init__(self) -> None:
        self._template = PromptTemplate.from_template(REFINER_TEMPLATE)
        self._cache: dict[str, str] = {}

    async def refine(self, query: str) -> str:
        if not query.strip():
            return query
        cached = self._cache.get(query)
        if cached:
            return cached
        try:
            raw = await self._call_ollama(self._template.format(query=query))
        except Exception:
            return query
        refined = self._clean(raw)
        if not self._is_valid(query, refined):
            return query
        self._cache[query] = refined
        return refined
```

### [app/api/chat.py](../app/api/chat.py)

```python
async def _refine_query(request: dict) -> str | None:
    if not ENABLE_QUERY_REFINEMENT:
        return _last_user_message(request)
    original = _last_user_message(request)
    refined = await get_refiner().refine(original)
    if refined != original:
        _replace_last_user_message(request, refined)
    return refined


@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    query = await _refine_query(request)            # ← Step 5
    if request.get("stream"):
        context = _build_context(query or "")
        _apply_template(request, context)
        return StreamingResponse(...)
    # 비스트리밍 + 캐시 + RAG + 템플릿 적용
    ...
```

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/refiner/refine?q=...` | 정제 결과 미리보기 (original, refined, changed) |

## 동작 확인

1. `http://localhost:8000/docs` → `/refiner/refine` 노출 확인
2. 정제 효과:
   - `GET /refiner/refine?q=python 함수 어케 만들지`
   - 응답 예: `"파이썬 함수를 정의하고 사용하는 방법을 알려주세요."`
3. 실제 채팅 (VSCode + Continue.dev):
   - 오타 섞인 질문 → 답변 정확도 향상
   - 서버 콘솔에 `[REFINER] original=... → refined=...` 로그 확인
4. 토글 OFF (`ENABLE_QUERY_REFINEMENT = False`) 후 서버 재시작:
   - 정제 단계 건너뛰고 Step 4 동작과 동일

## 남은 작업

- [ ] 정제 모델 비교 측정 (gemma4:latest vs qwen3.5:4b vs gemma3:1b — 정확도/속도)
- [ ] 정제 캐시를 SQLite 로 격상 (서버 재시작 시 유지) — Step 8 모니터링과 함께
- [ ] 정제 후 의도 보존 여부 자동 평가 (선택)

## 향후 확장 (이번 단계 범위 밖)

- 정제 + 의도 분류 동시 수행 (한 번의 LLM 호출로 둘 다)
- few-shot 예시 추가 (도메인 특화 정제 품질 ↑)
- 정제 옵션 사용자 노출 (`X-TokForge-Refine: false` 헤더로 끄기)
- 다중 모델 ensemble (작은 모델 1차 + 큰 모델 검증)

## 다음 단계

[Step 6 — 컨텍스트 압축](step06_압축.md)
