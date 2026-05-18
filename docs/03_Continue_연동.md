# 3. Continue.dev 연결 설정

> VSCode + Continue.dev 가 TokForge 를 통해 Ollama(또는 외부 API) 를 호출하도록 설정.

## 사전 준비

| 항목 | 확인 |
|---|---|
| VSCode 설치 | `code --version` |
| Continue 확장 | VSCode 마켓플레이스에서 "Continue" 설치 |
| TokForge 서버 실행 | `http://localhost:8000/healthz` 접속 → `ok` |
| Ollama 실행 + 모델 | `ollama list` 에서 `gemma4:e2b` 보임 |

> **인증 무관:** `/v1/chat/completions` 엔드포인트는 현재 인증 없이 호출 가능. Continue는 OAuth 로그인 없이 그대로 사용할 수 있습니다. (운영 진입 시 API Key 또는 토큰 추가 검토)

---

## 1. config.yaml 위치

| OS | 경로 |
|---|---|
| Windows | `%USERPROFILE%\.continue\config.yaml` |
| macOS / Linux | `~/.continue/config.yaml` |

**Windows 빠른 접근**:
```powershell
notepad $env:USERPROFILE\.continue\config.yaml
```

→ 파일이 없으면 Continue 가 첫 실행 시 자동 생성. VSCode 에서 Continue 패널을 한 번이라도 열어보세요.

---

## 2. TokForge 항목 추가

`models:` 섹션 아래에 추가:

```yaml
models:
  - name: TokForge
    provider: openai
    model: gemma4:e2b
    apiBase: http://127.0.0.1:8000/v1
    apiKey: local
    roles:
      - chat
```

### 각 필드 의미

| 필드 | 값 | 설명 |
|---|---|---|
| `name` | `TokForge` | Continue UI 의 모델 선택창에 표시될 이름 (자유) |
| `provider` | `openai` | TokForge 가 OpenAI 호환 API 라서 |
| `model` | `gemma4:e2b` | 표시용 (실제 모델은 [config.py](../app/config.py) 의 `DEFAULT_MODEL` 이 결정) |
| `apiBase` | `http://127.0.0.1:8000/v1` | TokForge 서버 주소 |
| `apiKey` | `local` | 로컬용 더미 (TokForge 는 키 검증 안 함) |
| `roles` | `[chat]` | 채팅 전용 (자동완성·임베딩 등은 별도 항목으로 추가) |

⚠️ `apiBase` 끝에 **`/v1`** 가 있어야 함. Continue 가 자동으로 `/chat/completions` 를 붙임 → `http://127.0.0.1:8000/v1/chat/completions` 호출.

---

## 3. 적용

1. config.yaml 저장
2. VSCode 의 Continue 패널 새로고침 (또는 VSCode 재시작)
3. 채팅창 상단 모델 선택에서 **TokForge** 선택

---

## 4. 동작 확인

Continue 채팅창에 "안녕" 입력 → 응답이 오면 OK.

**서버 로그 동시 확인** (uvicorn 터미널):
```
INFO: 127.0.0.1:xxxxx - "POST /v1/chat/completions HTTP/1.1" 200 OK
```

→ 200 OK 가 보이면 TokForge 가 요청을 정상 수신·처리한 것.

---

## 5. 자동완성·임베딩도 TokForge 로 보내려면 (선택)

```yaml
models:
  - name: TokForge
    provider: openai
    model: gemma4:e2b
    apiBase: http://127.0.0.1:8000/v1
    apiKey: local
    roles:
      - chat
      - autocomplete   # 코드 자동완성도 TokForge 경유
      - edit           # /edit 명령도 TokForge 경유
```

⚠️ 자동완성은 매 키 입력마다 호출이 발생 → TokForge 의 캐시·라우팅 기능에 부담. 처음에는 `chat` 만 권장.

---

## 트러블슈팅

### Continue 채팅창에 응답이 안 표시되는데 서버 로그는 200 OK

증상: `POST /v1/chat/completions 200 OK` 는 뜨지만 Continue UI 가 빈 응답.

가능한 원인 + 해결:

#### A. 스트리밍 응답 형식 불일치

기본 Continue 는 SSE 스트리밍을 기대. TokForge 의 스트리밍 출력이 OpenAI 형식과 미세 차이가 있을 수 있음.

→ **임시 우회**: 비스트리밍 강제.

```yaml
models:
  - name: TokForge
    provider: openai
    ...
    defaultCompletionOptions:
      stream: false
```

→ TokForge 가 비스트리밍 분기를 타게 됨 (캐시 적용 + 응답 정상 표시).

#### B. 모델명 불일치

Continue 가 `model` 필드 값을 그대로 백엔드에 전달하는데, Ollama 가 그 모델을 모르면 에러.

→ 해결: TokForge 의 [ollama.py](../app/llm/ollama.py) 가 `model` 을 강제로 덮어쓰므로 이 문제는 발생 안 함. 만약 그대로 전달하도록 바꿨다면 Continue 의 `model` 과 `ollama list` 의 모델명이 정확히 일치해야 함.

#### C. CORS

브라우저 기반 도구가 호출하면 CORS 가 필요. Continue 는 VSCode 내부 호출이라 CORS 영향 없음 → 원인 가능성 낮음.

### `apiBase` 응답이 없음 / Connection refused

→ TokForge 서버 미실행. `python -m uvicorn main:app --reload` 확인.

### `127.0.0.1` vs `localhost`

거의 동일하지만 일부 환경(IPv6 우선)에서 차이. **`127.0.0.1` 권장**.

### Continue 가 옛 캐시된 설정으로 동작

→ VSCode 완전 재시작. (Reload Window 만으로 안 될 때가 있음)

---

## (참고) 외부 API 로 전환 (Step 7 — 모델 라우팅 후)

현재는 Ollama 한 곳만 호출하지만, Step 7 완료 후엔 한 항목으로 OpenAI/Anthropic/Gemini 까지 자동 라우팅:

```yaml
- name: TokForge
  provider: openai
  apiBase: http://127.0.0.1:8000/v1
  apiKey: local
  roles: [chat]
```

→ Continue 입장에서는 똑같은 TokForge 1개. TokForge 내부에서 질문 복잡도 보고 백엔드 결정.

---

## 다음 문서

- 📁 [4. 디렉터리 구조](04_디렉터리_구조.md)
- 🔧 [5. 핵심 모듈 상세](05_핵심_모듈.md)
- 1️⃣ [Step 1 — 기본 프록시](step01_기본프록시.md)
