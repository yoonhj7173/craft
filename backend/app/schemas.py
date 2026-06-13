"""Pydantic request/response schemas — tech-design §6 API Contract (v3).

직렬화 경계를 둬서 ORM 컬럼 변화가 API 계약을 깨지 않도록 한다. item 6은 templates /
projects / map 계약을 담는다. teams/agents/edges 관리(item 7), tasks/board/usage(item 8–13)
스키마는 해당 라우터를 추가할 때 여기에 더해진다.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# --- Templates (GET /api/templates) — 역할 카탈로그(D41) ---


class RoleTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_key: str
    display_name: str
    default_tier: str
    is_starter: bool
    default_output_type: str | None
    default_output_target_role_key: str | None
    default_max_iterations: int | None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    description: str
    engine: str
    roles: list[RoleTemplateOut]


# --- Projects ---


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # 선택한 팀 템플릿(최소 1개). 온보딩 Flow 0 step 4.
    template_keys: list[str] = Field(min_length=1)
    # 온보딩 step 2의 표시 이름(선택). user_profiles에 upsert.
    display_name: str | None = Field(default=None, max_length=200)


class ProjectPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    paused: bool
    sandbox_status: str


# --- Map (GET /api/projects/{id}/map) ---


class AgentMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    model_tier: str
    slot: int
    status: str  # idle|queued|working|blocked|needs-input|failed (done→idle)


class TeamMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    template_key: str
    engine: str
    room_x: int
    room_y: int
    agents: list[AgentMapOut]


class EdgeMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    type: str
    max_iterations: int | None


class MapOut(BaseModel):
    project: ProjectOut
    paused: bool
    teams: list[TeamMapOut]
    edges: list[EdgeMapOut]
