"""Agent memory API — view/edit/clear (item 9, D14/D9).

- GET    /api/agents/{id}/memory   조회(없으면 빈 문자열)
- PUT    /api/agents/{id}/memory   upsert
- DELETE /api/agents/{id}/memory   삭제

에이전트별 마크다운 스크래치패드. task 후 auto-append(item 10)와 동일 행을 유저가 settings에서
관리한다.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import TenantScope, tenant_scope
from app.db import get_db
from app.models import AgentMemory
from app.ownership import load_owned_agent
from app.schemas import MemoryOut, MemoryPut

router = APIRouter(prefix="/api", tags=["memory"])


@router.get("/agents/{agent_id}/memory", response_model=MemoryOut)
def get_memory(
    agent_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> MemoryOut:
    agent = load_owned_agent(db, scope, agent_id)
    mem = db.get(AgentMemory, agent.id)
    return MemoryOut(agent_id=agent.id, content_md=mem.content_md if mem else "")


@router.put("/agents/{agent_id}/memory", response_model=MemoryOut)
def put_memory(
    agent_id: uuid.UUID,
    body: MemoryPut,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> MemoryOut:
    agent = load_owned_agent(db, scope, agent_id)
    mem = db.get(AgentMemory, agent.id)
    if mem is None:
        mem = AgentMemory(agent_id=agent.id, content_md=body.content_md)
        db.add(mem)
    else:
        mem.content_md = body.content_md
    db.commit()
    return MemoryOut(agent_id=agent.id, content_md=body.content_md)


@router.delete("/agents/{agent_id}/memory", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    agent_id: uuid.UUID,
    scope: TenantScope = Depends(tenant_scope),
    db: Session = Depends(get_db),
) -> None:
    agent = load_owned_agent(db, scope, agent_id)
    mem = db.get(AgentMemory, agent.id)
    if mem is not None:
        db.delete(mem)
        db.commit()
