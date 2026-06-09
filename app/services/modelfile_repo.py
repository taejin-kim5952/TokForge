""""""

import json
import logging
from datetime import datetime, timezone

from app import db

logger = logging.getLogger(__name__)

STATUSES = ("pending", "running", "done", "failed")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_job(
    project_id: int,
    base_model: str,
    output_model: str,
    modelfile_path: str | None = None,
) -> dict:
    now = _now()
    with db.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO modelfile_jobs
                (project_id, base_model, output_model, modelfile_path,
                 status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            RETURNING id, project_id, base_model, output_model, modelfile_path,
                      status, error_message, created_at, completed_at
            """,
            (project_id, base_model, output_model, modelfile_path, now),
        ).fetchone()
        if not row:
            raise RuntimeError("failed to create modelfile job")
        return dict(row)
    
def mark_running(job_id: int, project_id: int) -> dict | None:
    return _set_status(job_id, project_id, "running")
def mark_done(job_id: int, project_id: int) -> dict | None:
    return _set_status(job_id, project_id, "done")
def mark_failed(job_id: int, project_id: int, error_message: str) -> dict | None:
    return _set_status(job_id, project_id, "failed", error_message=error_message)
def get_for_project(job_id: int, project_id: int) -> dict | None:
    with db.connection() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, base_model, output_model, modelfile_path,
                   status, error_message, created_at, completed_at
            FROM modelfile_jobs
            WHERE id = ? AND project_id = ?
            """,
            (job_id, project_id),
        ).fetchone()
        return dict(row) if row else None
def list_for_project(project_id: int, *, limit: int = 50) -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, base_model, output_model, modelfile_path,
                   status, error_message, created_at, completed_at
            FROM modelfile_jobs
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    
def _set_status(
    job_id: int,
    project_id: int,
    status: str,
    *,
    error_message: str | None = None,
    modelfile_path: str | None = None,
) -> dict | None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    completed = _now() if status in ("done", "failed") else None
    with db.connection() as conn:
        conn.execute(
            """
            UPDATE modelfile_jobs
            SET status = ?,
                error_message = ?,
                modelfile_path = COALESCE(?, modelfile_path),
                completed_at = COALESCE(?, completed_at)
            WHERE id = ? AND project_id = ?
            """,
            (
                status,
                error_message,
                modelfile_path,
                completed,
                job_id,
                project_id,
            ),
        )
    return get_for_project(job_id, project_id)