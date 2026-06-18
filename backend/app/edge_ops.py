"""Edge creation + validation — D25(DAG)/D38(출력 1개)/D19(loop N).

엣지 생성은 두 경로에서 일어난다: POST /edges, 그리고 에이전트 추가 시 output 동시 지정.
두 경로가 같은 규칙을 타도록 검증/생성 로직을 여기 모은다.

규칙:
- 출력 1개(D38): from_agent에 기존 outgoing 엣지 있으면 409.
- self-edge 금지, 양 끝 에이전트는 같은 project 소속.
- loop N(D19): review_loop면 max_iterations 1–10 필수, handoff면 None.
- 사이클(D25): handoff는 DAG 유지 — to에서 outgoing handoff를 따라 walk해 from에 닿으면 cycle(400).
  출력이 에이전트당 1개라 그래프는 체인+루프뿐 → walk가 선형이라 싸다. review_loop는 허용된
  양방향이므로 cycle 검사 대상이 아니다.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Edge


def _creates_handoff_cycle(
    db: Session, project_id: uuid.UUID, from_id: uuid.UUID, to_id: uuid.UUID
) -> bool:
    """to에서 outgoing handoff 체인을 따라가 from에 닿으면 True(사이클)."""
    # 프로젝트 내 from_agent_id → (to_id, type) 매핑(에이전트당 outgoing 1개, D38).
    out: dict[uuid.UUID, tuple[uuid.UUID, str]] = {
        e.from_agent_id: (e.to_agent_id, e.type)
        for e in db.query(Edge).filter(Edge.project_id == project_id).all()
    }
    cur = to_id
    seen: set[uuid.UUID] = set()
    while cur in out and cur not in seen:
        seen.add(cur)
        nxt, etype = out[cur]
        if etype != "handoff":  # review_loop는 체인을 끊는다(handoff DAG 검사 한정).
            break
        if nxt == from_id:
            return True
        cur = nxt
    return False


def validate_and_build_edge(
    db: Session,
    *,
    project_id: uuid.UUID,
    from_agent: Agent,
    to_agent_id: uuid.UUID,
    type: str,
    max_iterations: int | None,
) -> Edge:
    """연결선 만들기(검증 포함) — 에이전트 사이 연결(엣지)을 규칙대로 검사하고 만든다.

    무슨 일을 하나: 맵에서 A→B로 선을 그을 때, 잘못된 연결을 막는 규칙을 검사한 뒤 통과하면
        Edge(연결)를 만든다. 잘못되면 사용자에게 보여줄 에러(HTTPException)를 던진다.
    검사 규칙:
        - 종류는 handoff(넘기기) 또는 review_loop(검토 반복) 둘 중 하나.
        - review_loop면 반복 횟수(max_iterations) 1~10 필수.
        - 자기 자신에게 연결 금지, 두 에이전트는 같은 프로젝트 소속이어야 함.
        - 출력은 에이전트당 1개만(이미 나가는 연결이 있으면 409 거부).
        - handoff는 사이클(빙빙 도는 무한 연결) 금지 — _creates_handoff_cycle로 검사.
    누가 부르나: POST /api/edges, 그리고 에이전트 추가 시 출력 동시 지정 — backend/app/routers/edges.py, teams.py.
    연결: 사이클 검사 → 이 파일 _creates_handoff_cycle. 만들어진 연결을 따라 일이 흐름 → graph_engine.py.
    """
    if type not in ("handoff", "review_loop"):
        raise HTTPException(status_code=422, detail="type must be handoff or review_loop")

    if type == "review_loop":
        if max_iterations is None or not (1 <= max_iterations <= 10):
            raise HTTPException(status_code=422, detail="review_loop requires max_iterations 1–10")
    else:  # handoff
        max_iterations = None

    if to_agent_id == from_agent.id:
        raise HTTPException(status_code=422, detail="self-edge not allowed")

    to_agent = db.get(Agent, to_agent_id)
    if to_agent is None or to_agent.project_id != project_id:
        raise HTTPException(status_code=400, detail="target agent not in this project")

    # 출력 1개(D38): from_agent에 기존 outgoing 있으면 409.
    existing = (
        db.query(Edge).filter(Edge.from_agent_id == from_agent.id).first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="agent already has an outgoing connection")

    # 사이클(D25): handoff만.
    if type == "handoff" and _creates_handoff_cycle(db, project_id, from_agent.id, to_agent_id):
        raise HTTPException(status_code=400, detail="handoff would create a cycle")

    edge = Edge(
        project_id=project_id,
        from_agent_id=from_agent.id,
        to_agent_id=to_agent_id,
        type=type,
        max_iterations=max_iterations,
    )
    db.add(edge)
    return edge
