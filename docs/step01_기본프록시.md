# Step 1 — 기본 프록시

> **상태**: ✅ 완료 (2026-05-09)

## 목표

Continue.dev 와 Ollama 사이에 TokForge 미들웨어를 끼워넣어, 모든 채팅 요청이 TokForge 를 거쳐 흐르도록 한다. 이번 단계에서는 **가공 없이 그대로 중계**만 한다.

## 흐름

```
Continue.dev
    ↓ POST /v1/chat/completions
TokForge (FastAPI, 8000)
    ↓ POST /v1/chat/completions
Ollama (gemma4:e2b, 11434)
    ↓ 응답
TokForge → Continue.dev
```

## 디렉터리 구조

```
TokForge/
├── main.py                     FastAPI 앱 + 라우터 등록
├── app/
│   ├── __init__.py
│   ├── config.py               OLLAMA_BASE_URL, DEFAULT_MODEL
│   ├── api/                    HTTP 인터페이스 (Java 의 Controller)
│   │   ├── __init__.py
│   │   ├── health.py           GET /, GET /health
│   │   ├── chat.py             POST /v1/chat/completions
│   │   └── models.py           GET /v1/models, GET /v1/models/current
│   ├── llm/
│   │   ├── __init__.py
│   │   └── ollama.py           Ollama 호출 모듈
│   └── services/
│       └── __init__.py         (Step 2 부터 채워짐)
├── requirements.txt
└── .gitignore
```

## 핵심 코드

### [app/config.py](../app/config.py) — 설정값

```python
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"
DEFAULT_MODEL = "gemma4:e2b"
```

### [app/llm/ollama.py](../app/llm/ollama.py) — Ollama 호출

```python
async def chat_completion(request: dict) -> dict:
    request["model"] = DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(OLLAMA_CHAT_URL, json=request)
        return response.json()
```

비스트리밍 + 스트리밍 두 함수 제공. `model` 필드를 강제 주입하여 Continue.dev 가 어떤 모델 이름을 보내든 TokForge 의 기본 모델로 통일.

### [app/api/chat.py](../app/api/chat.py) — 채팅 라우트

```python
@router.post("/v1/chat/completions")
async def chat_completions(request: dict):
    if request.get("stream"):
        return StreamingResponse(
            ollama.chat_completion_stream(request),
            media_type="text/event-stream",
        )
    return await ollama.chat_completion(request)
```

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/` | 서버 식별 |
| GET | `/health` | 서버 + Ollama 연결 상태 |
| POST | `/v1/chat/completions` | OpenAI 호환 채팅 |
| GET | `/v1/models` | 모델 목록 |
| GET | `/v1/models/current` | 현재 설정된 모델 |

## Continue.dev 연결

`%USERPROFILE%\.continue\config.yaml`:

```yaml
- name: TokForge
  provider: openai
  model: gemma4:e2b
  apiBase: http://127.0.0.1:8000/v1
  apiKey: local
  roles:
    - chat
```

## 검증

```powershell
python -m uvicorn main:app --reload
```

→ `http://localhost:8000/docs` Swagger UI 접속 → 5개 엔드포인트 모두 표시 → Continue.dev 에서 채팅 시 정상 응답.

## 다음 단계

[Step 2 — 의미 캐시](step02_의미캐시.md)
