"""Modelfile 서비스 — JSON 폼 조립, ollama create 실행."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services import modelfile_repo, project_repo

logger = logging.getLogger(__name__)

MODELFILE_STORAGE = Path(__file__).parent.parent.parent / "storage" / "modelfile"

KNOWN_PARAMETERS: set[str] = {
    "temperature",
    "num_ctx",
    "top_p",
    "top_k",
    "repeat_penalty",
    "seed",
    "num_predict",
    "stop",
    "mirostat",
    "mirostat_eta",
    "mirostat_tau",
    "num_gpu",
    "num_thread",
    "tfs_z",
    "typical_p",
}


class ModelfileValidationError(Exception):
    pass


def _flatten_message(text: str) -> str:
    return " ".join(str(text or "").split())


def _append_multiline_directive(lines: list[str], directive: str, text: str) -> None:
    text = text.strip()
    if not text:
        return
    lines.append(f'{directive} """')
    lines.append(text)
    lines.append('"""')


def _merge_parameters(payload: dict[str, Any]) -> dict[str, Any]:
    params = dict(payload.get("parameters") or {})
    if payload.get("temperature") is not None:
        params.setdefault("temperature", payload["temperature"])
    if payload.get("num_ctx") is not None:
        params.setdefault("num_ctx", payload["num_ctx"])
    return params


def _collect_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for msg in payload.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip()
        content = str(msg.get("content") or "")
        if role and content.strip():
            messages.append({"role": role, "content": content})
    for ex in payload.get("examples") or []:
        if not isinstance(ex, dict):
            continue
        user = str(ex.get("user") or "").strip()
        assistant = str(ex.get("assistant") or "").strip()
        if user:
            messages.append({"role": "user", "content": user})
        if assistant:
            messages.append({"role": "assistant", "content": assistant})
    return messages


def assemble_modelfile_from_form(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if content is not None and str(content).strip():
        return str(content).strip() + "\n"

    base_model = str(payload.get("base_model") or "").strip()
    if not base_model:
        raise ModelfileValidationError("base_model is required")

    lines: list[str] = []
    lines.append(f"FROM {base_model}")
    lines.append("")

    params = _merge_parameters(payload)
    param_lines: list[str] = []
    for key, value in params.items():
        key = str(key).strip()
        if not key or value is None or value == "":
            continue
        if key == "stop":
            stops = value if isinstance(value, list) else [value]
            for stop in stops:
                stop_text = str(stop).strip()
                if stop_text:
                    param_lines.append(f"PARAMETER stop {stop_text}")
        else:
            param_lines.append(f"PARAMETER {key} {value}")

    if param_lines:
        lines.extend(param_lines)
        lines.append("")

    template = str(payload.get("template") or "").strip()
    if template:
        if "\n" in template:
            _append_multiline_directive(lines, "TEMPLATE", template)
        else:
            lines.append(f"TEMPLATE {template}")
        lines.append("")

    system = str(payload.get("system") or "").strip()
    if system:
        _append_multiline_directive(lines, "SYSTEM", system)
        lines.append("")

    adapter = str(payload.get("adapter") or "").strip()
    if adapter:
        lines.append(f"ADAPTER {adapter}")
        lines.append("")

    license_text = str(payload.get("license") or "").strip()
    if license_text:
        _append_multiline_directive(lines, "LICENSE", license_text)
        lines.append("")

    requires = str(payload.get("requires") or "").strip()
    if requires:
        lines.append(f"REQUIRES {requires}")
        lines.append("")

    messages = _collect_messages(payload)
    if messages:
        pair_count = sum(
            1
            for i in range(0, len(messages) - 1, 2)
            if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant"
        )
        if pair_count:
            lines.append(f"# example messages ({pair_count} pairs)")
        for msg in messages:
            role = msg["role"]
            text = _flatten_message(msg["content"])
            lines.append(f"MESSAGE {role} {text}")

    return "\n".join(lines).rstrip() + "\n"


def canonical_ollama_model_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ModelfileValidationError("ollama_model name is required")
    if ":" not in name:
        name = f"{name}:latest"
    return name


def _modelfile_dir(project_id: int) -> Path:
    return MODELFILE_STORAGE / f"project_{project_id}"


def _resolve_ollama_cli() -> str:
    cli = shutil.which("ollama")
    if not cli:
        raise FileNotFoundError("ollama CLI not found in PATH")
    return cli


def run_create_from_form(
    project_id: int,
    payload: dict[str, Any],
    *,
    set_active: bool = True,
) -> tuple[dict, str | None]:
    text = assemble_modelfile_from_form(payload)

    output_name = str(payload.get("output_name") or "").strip()
    if not output_name:
        raise ModelfileValidationError("output_name is required for create")

    base_model = str(payload.get("base_model") or "").strip()

    project_dir = _modelfile_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    modelfile_path = project_dir / "Modelfile"
    modelfile_path.write_text(text, encoding="utf-8")

    storage_root = Path(__file__).parent.parent.parent
    rel_path = str(modelfile_path.relative_to(storage_root))

    job = modelfile_repo.create_job(
        project_id,
        base_model,
        output_name,
        modelfile_path=rel_path,
    )
    if not job:
        raise RuntimeError("failed to create modelfile job")
    job_id = int(job["id"])
    modelfile_repo.mark_running(job_id, project_id)

    cli = _resolve_ollama_cli()
    try:
        proc = subprocess.run(
            [cli, "create", output_name, "-f", str(modelfile_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,
        )
    except subprocess.TimeoutExpired as e:
        modelfile_repo.mark_failed(job_id, project_id, "ollama create timed out")
        raise RuntimeError("ollama create timed out") from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ollama create failed").strip()
        modelfile_repo.mark_failed(job_id, project_id, err[:2000])
        raise RuntimeError(err)

    job = modelfile_repo.mark_done(job_id, project_id)
    if not job:
        raise RuntimeError("failed to update modelfile job")

    active_name: str | None = None
    if set_active:
        active_name = canonical_ollama_model_name(output_name)
        project_repo.set_ollama_model(project_id, active_name)

    logger.info(
        "modelfile create done: project_id=%s output=%s active=%s",
        project_id,
        output_name,
        active_name,
    )
    return job, active_name
