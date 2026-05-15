# Step 8 — 비용/품질 모니터링 (Cost/Quality Monitoring)

> **상태**: ✅ 완료 (백엔드 + JSON API, 시각화는 향후 확장)
>
> 진행 일자: 2026-05-11

## 목표

Step 1~7 의 각 단계가 **실제로 얼마나 절감·향상을 만들고 있는지** 측정·기록·노출.
"감 → 데이터" 로 전환해서 다음 개선의 방향을 객관적으로 잡는다.

```
[요청 하나가 흐를 때마다]
    ↓
정제·RAG·압축·라우팅 각 단계의 변화를 dict 에 누적
    ↓
응답 직전 SQLite (storage/monitor.db) 에 한 row 저장
    ↓
GET /monitor/recent, /monitor/stats 로 조회·집계
```

## Step 7 까지와의 차이

| | Step 7 까지 | Step 8 |
|---|---|---|
| 효과 측정 | "동작은 한다" 수준 | 단계별·요청별 지표 누적 |
| 디버깅 | 로그 grep | SQL 쿼리 + 집계 API |
| 토큰 절감 가시화 | 없음 | 평균 압축률·티어 분포로 추적 |
| 회귀 감지 | 어려움 | latency·error 추이로 즉시 발견 |

## 흐름

```
[요청 시작]
    ↓
started = now_ms()
metrics = {}
    ↓
정제 (Step 5) ────────→ metrics["original"], ["refined"], ["refined_changed"]
    ↓
캐시 lookup (Step 2) ──→ metrics["cache_hit"]  (히트 시 즉시 응답 + 기록)
    ↓ (miss)
RAG (Step 3) ─────────→ metrics["rag_chunks"], ["ctx_before"]
    ↓
압축 (Step 6) ────────→ metrics["ctx_after"]
    ↓
템플릿 (Step 4)
    ↓
라우팅 (Step 7) ──────→ metrics["tier"], ["model"]
    ↓
Ollama 호출
    ↓
응답 ────────────────→ metrics["prompt_toks"], ["completion_toks"], ["total_toks"]
    ↓
metrics["latency_ms"] = now_ms() - started
get_monitor().record(metrics)
    ↓
[응답 반환]
```

→ 예외 발생 시에도 `metrics["error"]` 에 기록하고 raise. **모든 요청이 추적된다**.

## 디렉터리 변화

```
app/
  api/
    chat.py        🔄 metrics dict 수집, _record() 호출 추가, 예외도 기록
    monitor.py     🆕 /monitor/stats, /monitor/recent 엔드포인트
  services/
    monitor.py     🆕 MonitorService (SQLite) + now_ms() 헬퍼
  config.py        🔄 ENABLE_MONITORING, MONITOR_DB_PATH 추가
main.py            🔄 monitor 라우터 등록
storage/
  monitor.db       🆕 SQLite — 첫 요청 시 자동 생성
```

## 데이터 모델

```sql
CREATE TABLE requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    original        TEXT,           -- 사용자 raw 입력
    refined         TEXT,           -- Step 5 결과
    refined_changed BOOLEAN,        -- 정제로 실제 변경이 있었나
    rag_chunks      INTEGER,        -- Step 3 hit 수
    ctx_before      INTEGER,        -- 압축 전 컨텍스트 길이
    ctx_after       INTEGER,        -- Step 6 압축 후 길이
    tier            TEXT,           -- Step 7 분류 (simple/medium/complex)
    model           TEXT,           -- 실제 호출된 모델
    prompt_toks     INTEGER,        -- 입력 토큰
    completion_toks INTEGER,        -- 출력 토큰
    total_toks      INTEGER,        -- 합계
    latency_ms      INTEGER,        -- 전체 지연시간
    cache_hit       BOOLEAN,        -- Step 2 캐시 적중
    error           TEXT            -- 실패 시 에러 repr
);
```

→ **한 row = 한 요청**. 정규화 없이 단순. 쿼리 한 줄로 모든 단계의 효과 추적 가능.

## 노출 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/monitor/recent?limit=20` | 최근 N건 상세 (단계별 변화 전체) |
| GET | `/monitor/stats` | 집계 통계 (캐시 hit율, 평균 압축률, 티어 분포 등) |

### `/monitor/stats` 응답 예시

```json
{
  "total_requests": 42,
  "cache_hits": 8,
  "cache_hit_rate": 0.190,
  "refined_count": 31,
  "refined_rate": 0.738,
  "avg_latency_ms": 1820.5,
  "avg_compression_ratio": 0.213,
  "avg_total_tokens": 412.7,
  "tier_distribution": {"simple": 12, "medium": 22, "complex": 8},
  "model_distribution": {"gemma4:e2b": 34, "gemma4:latest": 8},
  "error_count": 1
}
```

→ `avg_compression_ratio: 0.213` = **컨텍스트가 평균 21% 로 압축됨 (79% 토큰 절감)**.
→ `cache_hit_rate: 0.19` = **5건 중 1건은 LLM 호출 없이 즉시 응답**.

## 핵심 코드

### [app/services/monitor.py](../app/services/monitor.py)

```python
class MonitorService:
    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record(self, data: dict) -> None:
        """한 요청의 지표를 한 row 로 저장."""
        try:
            conn = sqlite3.connect(_DB_PATH)
            conn.execute("INSERT INTO requests ... VALUES (?, ...)", (...))
            conn.commit()
            conn.close()
        except Exception as e:
            # 모니터 실패가 실제 응답을 막으면 안 됨
            print(f"[MONITOR ERROR] {e}", flush=True)

    def stats(self) -> dict:
        """집계: total, cache_hit_rate, avg_compression, tier_dist ..."""
        ...
```

### [app/api/chat.py](../app/api/chat.py) — 측정 통합

```python
@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    metrics: dict = {}
    started = now_ms()
    try:
        query = await _refine_query(request, metrics)       # metrics 누적
        ...
        response = await ollama.chat_completion(request)
        _extract_usage(response, metrics)                    # 토큰 수
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        return response
    except Exception as e:
        metrics["error"] = repr(e)
        metrics["latency_ms"] = now_ms() - started
        _record(metrics)
        raise
```

## 핵심 설계

### 1. 흐름 침투 최소화

각 헬퍼 함수가 `metrics: dict` 를 받아 자기가 만든 변화를 직접 기록:
```python
async def _compress_context(query, context, metrics):
    ...
    metrics["ctx_after"] = len(compressed)
```

→ chat_completions 본체에 `if/else` 없이 자연스럽게 데이터 모임.

### 2. 모니터 실패가 응답을 막지 않음

```python
def record(self, data: dict) -> None:
    try:
        ...
    except Exception as e:
        print(f"[MONITOR ERROR] {e}", flush=True)
```

→ SQLite 락·디스크 풀 등 모니터 자체 문제로 **사용자 응답이 실패하면 안 됨**.

### 3. 예외 발생도 기록

```python
except Exception as e:
    metrics["error"] = repr(e)
    _record(metrics)
    raise
```

→ 에러가 나도 latency·query 같은 지표는 보존. 실패 패턴 분석 가능.

### 4. SQLite (sync) 를 async 함수 안에서 호출

`cache.py` 와 같은 패턴. 한 row insert 는 1ms 미만이라 event loop 영향 무시 가능.
정말 트래픽이 많아지면 `aiosqlite` 로 격상 가능 (이미 requirements.txt 에 있음).

## 동작 확인

1. 서버 기동 후 채팅 몇 번 호출 (Continue.dev 또는 curl)
2. `http://localhost:8000/monitor/stats` → 누적 지표 확인
3. `http://localhost:8000/monitor/recent?limit=5` → 최근 5건 상세
4. SQLite 직접 조회 (선택):
   ```bash
   sqlite3 storage/monitor.db "SELECT tier, COUNT(*), AVG(latency_ms) FROM requests GROUP BY tier"
   ```
5. 토글 OFF (`ENABLE_MONITORING = False`) → 기록 안 됨. 기존 동작은 유지.

## 남은 작업 (이번 단계 범위 밖)

- [ ] Streamlit 대시보드 (`pip install streamlit` 이미 됨)
  - 시계열 그래프, 모델 분포 파이차트, 압축률 히스토그램
  - `streamlit run app/dashboard.py` 로 실행
- [ ] 스트리밍 요청도 토큰 수집 (응답 끝까지 모은 후 기록)
- [ ] 단계별 latency 분리 — 현재는 total 만 측정, 단계별로 쪼개면 병목 파악 가능
- [ ] 비용 계산 — 외부 API (OpenAI/Anthropic) 도입 시 토큰별 단가 적용
- [ ] 에러 알람 — error_rate 임계값 초과 시 Slack/이메일 (Step 8.1 정도로)

## 향후 확장

- **LangSmith 연동**: SaaS 가 무료 tier 있음. 기존 LangChain 호출에 trace 자동 추가
- **Prometheus + Grafana**: 운영 환경에서 시계열 메트릭 표준
- **OpenTelemetry**: 분산 트레이싱 표준 — 외부 API 까지 trace 가능
- **A/B 테스트 프레임워크**: ENABLE_* 토글을 사용자별로 다르게 설정해 효과 비교

## 8단계 완성 회고

```
Step 1  ✅  기본 프록시        ── FastAPI + httpx
Step 2  ✅  의미 캐시          ── sentence-transformers + FAISS
Step 3  ✅  RAG               ── LangChain (FAISS + HuggingFace)
Step 4  ✅  프롬프트 템플릿     ── LangChain ChatPromptTemplate
Step 5  ✅  질문 정제          ── LangChain PromptTemplate + LLM
Step 6  ✅  컨텍스트 압축       ── LangChain PromptTemplate + LLM
Step 7  ✅  모델 자동 라우팅    ── LangChain PromptTemplate + dict 매핑
Step 8  ✅  모니터링           ── SQLite + 자체 집계 API
```

→ **VSCode 사용자의 코딩 워크플로 전용 최적화 게이트웨이** 가 완성됐다.
"무엇이 얼마나 절감되는지" 까지 측정 가능.

## 다음 작업 — 운영 진입

8단계 완성 후의 자연스러운 다음 단계:
1. 실 사용 데이터 1주일 수집 → 어떤 단계가 가장 효과 큰지 확인
2. 비효율 단계 토글 OFF 또는 모델 교체로 개선
3. Streamlit 대시보드 구축
4. 외부 API (OpenAI/Anthropic) 통합 — `MODEL_TIERS` 에 새 티어 추가
