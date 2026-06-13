"""Outputs API — task-grouped trees + preview/download/zip (item 9, D4/D18/D27/D31).

- GET /api/projects/{id}/outputs        task별로 묶은 파일 목록(트리)
- GET /api/outputs/{id}                 미리보기(text/md/code → 내용, 바이너리 → null)
- GET /api/outputs/{id}/download        단일 파일 원본 다운로드
- GET /api/tasks/{id}/outputs.zip       task 트리 전체 zip

읽기 전용(D18) — 편집/버저닝/검색 없음. 내용은 FileStore 경유.
"""

from __future__ import annotations

import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import Agent, Output, Project, Task
from app.ownership import load_owned_project
from app.schemas import OutputFileOut, OutputPreviewOut, OutputTaskGroupOut
from app.services.filestore import filestore

router = APIRouter(prefix="/api", tags=["outputs"])

# 미리보기를 텍스트로 렌더할 mime 접두/집합.
_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_EXACT = {
    "application/json", "application/javascript", "application/xml",
    "application/x-python", "application/x-sh",
}


def _is_text(mime: str, row: Output) -> bool:
    if row.content is not None:
        return True
    if row.content_bytes is not None:
        return False
    return mime.startswith(_TEXT_MIME_PREFIXES) or mime in _TEXT_MIME_EXACT


def _load_owned_output(db: Session, scope: TenantScope, output_id: uuid.UUID) -> Output:
    row = db.get(Output, output_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Output not found")
    project = db.get(Project, row.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Output not found")
    return row


@router.get("/projects/{project_id}/outputs", response_model=list[OutputTaskGroupOut])
def list_outputs(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[OutputTaskGroupOut]:
    """프로젝트 아웃풋을 task별로 묶어 트리로 반환(최신 task 먼저)."""
    project = load_owned_project(db, scope, project_id)
    rows = (
        db.query(Output)
        .filter(Output.project_id == project.id)
        .order_by(Output.task_id, Output.path)
        .all()
    )
    # task_id로 그룹.
    groups: dict[uuid.UUID, list[Output]] = {}
    for r in rows:
        groups.setdefault(r.task_id, []).append(r)

    agent_names = {a.id: a.name for a in db.query(Agent).filter(Agent.project_id == project.id).all()}

    out: list[OutputTaskGroupOut] = []
    for task_id, files in groups.items():
        agent_id = files[0].agent_id
        out.append(
            OutputTaskGroupOut(
                task_id=task_id,
                agent_id=agent_id,
                agent_name=agent_names.get(agent_id, "(removed)"),
                file_count=len(files),
                files=[OutputFileOut.model_validate(f) for f in files],
            )
        )
    return out


@router.get("/outputs/{output_id}", response_model=OutputPreviewOut)
def preview_output(
    output_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> OutputPreviewOut:
    row = _load_owned_output(db, scope, output_id)
    text = _is_text(row.mime, row)
    return OutputPreviewOut(
        id=row.id,
        path=row.path,
        mime=row.mime,
        is_binary=not text,
        content=filestore.get_text(row) if text else None,
    )


@router.get("/outputs/{output_id}/download")
def download_output(
    output_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> Response:
    row = _load_owned_output(db, scope, output_id)
    data = filestore.get_bytes(row)
    filename = row.path.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=row.mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tasks/{task_id}/outputs.zip")
def download_task_zip(
    task_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """task의 아웃풋 트리 전체를 zip으로(코드 트리 다운로드, D4)."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    project = db.get(Project, task.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Task not found")

    rows = db.query(Output).filter(Output.task_id == task_id).order_by(Output.path).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No outputs for this task")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            zf.writestr(r.path, filestore.get_bytes(r))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="task-{task_id}.zip"'},
    )
