"""프로젝트 Admin — Modelfile (Ollama 모델 등록·활성 모델)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.deps import CurrentUser, OwnedProject
from app.services import modelfile_repo, project_repo

from app.services.modelfile_service import (
    KNOWN_PARAMETERS,
    ModelfileValidationError,
    assemble_modelfile_from_form,
    canonical_ollama_model_name,
    run_create_from_form,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/admin/modelfile",
    tags=["project-admin-modelfile"],
)

MessageRole = Literal["user", "assistant", "system"]


class ModelfileMessage(BaseModel):
    role: MessageRole = Field(..., description="MESSAGE 역할 (user | assistant | system)")
    content: str = Field("", description="메시지 본문")


class ModelfileExample(BaseModel):
    """레거시 — messages 로 대체 권장."""

    user: str = ""
    assistant: str = ""


_MODELFILE_FORM_EXAMPLE: dict[str, Any] = {
    "base_model": "gemma4:latest",
    "output_name": "k-itad-v1",
    "parameters": {
        "temperature": 0.7,
        "num_ctx": 8192,
        "top_p": 0.9,
        "repeat_penalty": 1.1,
        "stop": ["</s>"],
    },
    "template": "",
    "system": "ITAD 시스템 프롬프트",
    "messages": [
        {"role": "user", "content": "ITAD란?"},
        {"role": "assistant", "content": "ITAD 전문가 답변"},
    ],
    "adapter": "",
    "license": "",
    "requires": "",
    "content": None,
}


class ModelfileFormPayload(BaseModel):
    """Ollama Modelfile 전 지시어 JSON 폼.

    Modelfile 텍스트 매핑:
      base_model → FROM
      parameters → PARAMETER (stop 은 문자열 배열)
      system     → SYSTEM
      template   → TEMPLATE
      adapter    → ADAPTER
      license    → LICENSE
      requires   → REQUIRES
      messages   → MESSAGE
      content    → 원문 Modelfile (지정 시 위 필드 무시)
    """

    model_config = ConfigDict(json_schema_extra={"example": _MODELFILE_FORM_EXAMPLE})

    base_model: str = Field(
        ...,
        min_length=1,
        description="FROM — 베이스 Ollama 모델 (예: gemma4:latest)",
    )
    output_name: str = Field(
        "",
        description="ollama create 출력 모델명 (create 시 필수)",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "PARAMETER 목록. 예: temperature, num_ctx, top_p, repeat_penalty, "
            "stop(문자열 배열) 등"
        ),
    )
    template: str = Field("", description="TEMPLATE — Go template 프롬프트 형식")
    system: str = Field("", description="SYSTEM — 시스템 프롬프트")
    messages: list[ModelfileMessage] = Field(
        default_factory=list,
        description="MESSAGE — 예시 대화 (user/assistant/system)",
    )
    adapter: str = Field(
        "",
        description="ADAPTER — LoRA 어댑터 경로 (GGUF/safetensors)",
    )
    license: str = Field("", description="LICENSE — 라이선스 문구")
    requires: str = Field(
        "",
        description="REQUIRES — 최소 Ollama 버전 (예: 0.5.0)",
    )
    content: str | None = Field(
        None,
        description="Modelfile 원문. 지정 시 구조화 필드 대신 이 텍스트 사용",
    )
    # 레거시 (하위 호환)
    temperature: float | None = Field(
        None,
        description="[레거시] parameters.temperature 로 병합",
    )
    num_ctx: int | None = Field(
        None,
        ge=1,
        description="[레거시] parameters.num_ctx 로 병합",
    )
    examples: list[ModelfileExample] = Field(
        default_factory=list,
        description="[레거시] messages 로 병합 (user/assistant 쌍)",
    )

    @field_validator("parameters")
    @classmethod
    def validate_parameter_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if key.strip() not in KNOWN_PARAMETERS:
                logger.warning("unknown Modelfile PARAMETER: %s", key)
        return value

    def to_service_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=False)


class ModelfileCreateRequest(ModelfileFormPayload):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {**_MODELFILE_FORM_EXAMPLE, "set_active": True},
        }
    )

    set_active: bool = Field(
        True,
        description="성공 시 projects.ollama_model 자동 설정",
    )

    @model_validator(mode="after")
    def require_output_name(self) -> ModelfileCreateRequest:
        if not self.content and not self.output_name.strip():
            raise ValueError("output_name is required for create")
        return self


class SetActiveModelfileRequest(BaseModel):
    ollama_model: str = Field(
        ...,
        min_length=1,
        description="활성으로 지정할 Ollama 모델명 (ollama list 에 표시되는 이름)",
        examples=["k-itad-v1", "gemma4:latest"],
    )


def _active_response(project_id: int) -> dict[str, Any]:
    row = project_repo.get_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return {
        "ollama_model": row.get("ollama_model"),
        "ollama_model_at": row.get("ollama_model_at"),
    }


def _get_job_or_404(project_id: int, job_id: int) -> dict[str, Any]:
    job = modelfile_repo.get_for_project(job_id, project_id)
    if not job:
        raise HTTPException(status_code=404, detail="modelfile job not found")
    return job


@router.get(
    "/schema",
    summary="Modelfile JSON 폼 스키마",
    response_description="지시어 목록·PARAMETER 키·예시 JSON",
)
def get_modelfile_schema(
    project: OwnedProject,
    user: CurrentUser,
) -> dict[str, Any]:
    """Ollama Modelfile API 요청 body 예시와 지원 PARAMETER 목록을 반환합니다.

    preview/create 호출 전 curl·Swagger 테스트용 힌트입니다.
    """
    return {
        "directives": [
            "FROM (base_model)",
            "PARAMETER (parameters)",
            "SYSTEM (system)",
            "TEMPLATE (template)",
            "ADAPTER (adapter)",
            "LICENSE (license)",
            "REQUIRES (requires)",
            "MESSAGE (messages)",
        ],
        "known_parameters": sorted(KNOWN_PARAMETERS),
        "example": {
            "base_model": "gemma4:latest",
            "output_name": "k-itad-v1",
            "parameters": {
                "temperature": 0.7,
                "num_ctx": 8192,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "seed": 42,
                "num_predict": 2048,
                "stop": ["</s>", "USER:"],
            },
            "template": "",
            "system": "ITAD 시스템 프롬프트",
            "messages": [
                {"role": "user", "content": "ITAD란 무엇인가요?"},
                {"role": "assistant", "content": "ITAD 전문가 답변"},
            ],
            "adapter": "",
            "license": "",
            "requires": "",
            "content": None,
        },
    }


@router.get(
    "/active",
    summary="활성 Ollama 모델 조회",
    response_description="ollama_model, ollama_model_at",
)
def get_active_modelfile_model(
    project: OwnedProject,
    user: CurrentUser,
) -> dict[str, Any]:
    """이 프로젝트에 연결된 활성 Ollama 모델명을 조회합니다.

    - DB `projects.ollama_model`, `ollama_model_at` 반환
    - 미설정 시 두 필드 모두 `null`
    - 인증: 프로젝트 소유자만 (`OwnedProject`)
    """
    return _active_response(project["id"])


@router.put(
    "/active",
    summary="활성 Ollama 모델 수동 설정",
    response_description="갱신된 ollama_model, ollama_model_at",
)
def set_active_modelfile_model(
    project: OwnedProject,
    user: CurrentUser,
    body: SetActiveModelfileRequest,
) -> dict[str, Any]:
    """이미 Ollama에 존재하는 모델명을 활성 모델로 지정합니다.

    `ollama create` 없이 `ollama list`에 있는 이름만 연결할 때 사용합니다.
    """
    canonical = canonical_ollama_model_name(body.ollama_model)
    row = project_repo.set_ollama_model(project["id"], canonical)
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    logger.info(
        "modelfile active set manually: project_id=%s model=%s",
        project["id"],
        body.ollama_model,
    )
    return _active_response(project["id"])


@router.delete(
    "/active",
    summary="활성 Ollama 모델 해제",
    response_description='{"ok": true}',
)
def clear_active_modelfile_model(
    project: OwnedProject,
    user: CurrentUser,
) -> dict[str, bool]:
    """프로젝트 활성 모델을 해제합니다 (`ollama_model` → null).

    Ollama에서 모델을 삭제하지는 않습니다. 채팅 시 플랫폼 기본 모델로 되돌아갑니다.
    """
    project_repo.clear_ollama_model(project["id"])
    logger.info("modelfile active cleared: project_id=%s", project["id"])
    return {"ok": True}


@router.post(
    "/preview",
    summary="Modelfile 텍스트 미리보기",
    response_description='{"modelfile": "FROM ...\\nSYSTEM ..."}',
)
def preview_modelfile(
    project: OwnedProject,
    user: CurrentUser,
    body: ModelfileFormPayload,
) -> dict[str, str]:
    """JSON 폼을 Ollama Modelfile **텍스트**로 조립합니다.

    - `content` 필드가 있으면 원문을 검증만 하고 그대로 반환
    - 파일 저장·`ollama create`는 하지 않음
    - 지원 지시어: FROM, PARAMETER, SYSTEM, TEMPLATE, ADAPTER, LICENSE, REQUIRES, MESSAGE
    """
    try:
        text = assemble_modelfile_from_form(body.to_service_payload())
        logger.info(f"text : {text} ")
    except ModelfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"modelfile": text}


@router.post(
    "/create",
    summary="Ollama 모델 생성 (ollama create)",
    response_description='{"job": {...}, "ollama_model": "..."}',
)
def create_modelfile_model(
    project: OwnedProject,
    user: CurrentUser,
    body: ModelfileCreateRequest,
) -> dict[str, Any]:
    """Modelfile 저장 후 `ollama create`를 실행하고 job 이력을 남깁니다.

    1. JSON → Modelfile 텍스트 조립
    2. `storage/modelfile/project_{id}/Modelfile` 저장
    3. `modelfile_jobs` insert (pending → running → done/failed)
    4. `ollama create {output_name} -f ...`
    5. `set_active=true`(기본)이면 `projects.ollama_model` 갱신

    서버에 Ollama CLI가 설치·실행 중이어야 합니다. 실패 시 job.status=`failed`.
    """
    try:
        job, active_name = run_create_from_form(
            project["id"],
            body.to_service_payload(),
            set_active=body.set_active,
        )
    except ModelfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.exception("modelfile create failed: project_id=%s", project["id"])
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"job": job, "ollama_model": active_name}


@router.get(
    "/jobs",
    summary="Modelfile 생성 이력 목록",
    response_description='{"jobs": [modelfile_jobs 행...]}',
)
def list_modelfile_jobs(
    project: OwnedProject,
    user: CurrentUser,
) -> dict[str, Any]:
    """`modelfile_jobs` 테이블을 최신순으로 조회합니다 (기본 50건)."""
    jobs = modelfile_repo.list_for_project(project["id"])
    return {"jobs": jobs}


@router.get(
    "/jobs/{job_id}",
    summary="Modelfile 생성 job 상세",
    response_description="modelfile_jobs 단건",
)
def get_modelfile_job(
    project: OwnedProject,
    user: CurrentUser,
    job_id: int = Path(..., description="modelfile_jobs.id"),
) -> dict[str, Any]:
    """단일 job 상태 조회. pending/running 폴링·에러 메시지 확인용."""
    return _get_job_or_404(project["id"], job_id)
