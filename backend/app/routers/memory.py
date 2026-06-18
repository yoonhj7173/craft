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
    """에이전트 기억 저장 — 직원 한 명의 '메모장'(이전 작업에서 배운 것)을 사용자가 직접 수정한다.

    무슨 일을 하나: 에이전트별 마크다운 메모(다음 작업 프롬프트에 들어가는 기억)를 통째로 덮어쓴다.
        평소엔 작업이 끝날 때마다 시스템이 결과 요지를 자동으로 덧붙이지만(auto-append), 사용자가
        여기서 직접 정리·삭제할 수도 있다.
    누가 부르나: 설정의 에이전트 메모리 편집 화면.
    연결: 자동으로 덧붙는 곳 → _append_memory (backend/app/services/worker_core.py).
        기억이 프롬프트에 들어가는 곳 → assemble_prompt (backend/app/services/prompt.py).
    """
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
