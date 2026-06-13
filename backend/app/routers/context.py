"""Context file API — upload/list/delete (item 9, D14).

- POST   /api/projects/{id}/context   파일 업로드(txt/md/pdf 허용 + 텍스트 추출)
- GET    /api/projects/{id}/context   목록
- DELETE /api/context/{id}            삭제

추출 텍스트는 프롬프트 조립(item 10)이 풀텍스트로 주입한다. 원본은 FileStore에 보관.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import ContextFile, Project
from app.ownership import load_owned_project
from app.schemas import ContextFileOut
from app.services.extract import extract
from app.services.filestore import filestore

router = APIRouter(prefix="/api", tags=["context"])

MAX_CONTEXT_BYTES = 10 * 1024 * 1024  # 10MB 상한.


@router.post(
    "/projects/{project_id}/context",
    response_model=ContextFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_context(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ContextFileOut:
    project = load_owned_project(db, scope, project_id)
    data = await file.read()
    if len(data) > MAX_CONTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10MB)")

    # 허용 타입 검사 + 텍스트 추출(허용 외 400).
    extracted, mime = extract(file.filename or "upload", data)

    row = ContextFile(
        project_id=project.id,
        filename=file.filename or "upload",
        mime=mime,
        size_bytes=len(data),
        extracted_text=extracted,
    )
    # 원본 보관: 텍스트류는 text 컬럼, pdf는 bytea.
    if mime == "application/pdf":
        filestore.put_bytes(row, data, mime=mime)
    else:
        filestore.put_text(row, data.decode("utf-8", errors="replace"), mime=mime)
    row.extracted_text = extracted  # put_* 가 size를 덮으므로 마지막에 재설정.
    row.size_bytes = len(data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ContextFileOut.model_validate(row)


@router.get("/projects/{project_id}/context", response_model=list[ContextFileOut])
def list_context(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[ContextFileOut]:
    project = load_owned_project(db, scope, project_id)
    rows = (
        db.query(ContextFile)
        .filter(ContextFile.project_id == project.id)
        .order_by(ContextFile.created_at.desc())
        .all()
    )
    return [ContextFileOut.model_validate(r) for r in rows]


@router.delete("/context/{context_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_context(
    context_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    row = db.get(ContextFile, context_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Context file not found")
    project = db.get(Project, row.project_id)
    if project is None or not scope.owns(project):
        raise HTTPException(status_code=404, detail="Context file not found")
    db.delete(row)
    db.commit()
