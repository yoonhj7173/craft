"""Orchestrator chat API (item 13, D3).

- POST /api/projects/{id}/chat          freeform 메시지 → 오케스트레이터 1턴 → {reply, actions}
- GET  /api/projects/{id}/chat/history  대화 히스토리(시간순)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import TenantScope, require_user, tenant_scope
from app.db import get_db
from app.models import OrchestratorMessage
from app.ownership import load_owned_project
from app.services.orchestrator import run_chat

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: str


class ChatOut(BaseModel):
    reply: str
    actions: list


class ChatMessageOut(BaseModel):
    role: str
    content: str


@router.post("/projects/{project_id}/chat", response_model=ChatOut)
def chat(
    project_id: uuid.UUID,
    body: ChatIn,
    user_id: str = Depends(require_user),
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> ChatOut:
    load_owned_project(db, scope, project_id)
    result = run_chat(db, project_id, user_id, body.message)
    return ChatOut(reply=result["reply"], actions=result["actions"])


@router.get("/projects/{project_id}/chat/history", response_model=list[ChatMessageOut])
def history(
    project_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> list[ChatMessageOut]:
    project = load_owned_project(db, scope, project_id)
    rows = (
        db.query(OrchestratorMessage)
        .filter(OrchestratorMessage.project_id == project.id)
        .order_by(OrchestratorMessage.created_at)
        .all()
    )
    return [ChatMessageOut(role=r.role, content=r.content) for r in rows]
