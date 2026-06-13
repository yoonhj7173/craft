"""GraphEngine — task done 시 그래프 전파(item 11, D6/D19/D21/D25/D38).

propagate(db, task)는 task가 막 `done`이 된 직후(같은 트랜잭션 안에서) 호출되어 다운스트림
task들을 queued로 생성하고 그 id 리스트를 반환한다(커밋/enqueue는 호출부 = worker_core).

전파 규칙:
- 억제: task.stopped 또는 project.paused면 아무것도 안 함(failed는 done이 아니라 애초에 안 옴).
- 체인 버짓: goal task 수 > budget이면 중단 + notification.
- override(D21): task.override_route가 있으면 엣지 대신 그 대상으로 1회 전달(엣지 불변).
- 출력 엣지(D38, 에이전트당 1개):
    handoff A→B  : B용 task 생성(input=A 결과, provenance).
    review_loop A→B : B(리뷰어)용 task 생성(round 1). 리뷰어가 done 되면 _on_reviewer_done.
- review 프로토콜(D19): 리뷰어 done →
    APPROVED → 루프 종료, 리뷰어(B)의 자체 handoff가 있으면 다운스트림 발화.
    미승인 & round<N → 생산자(A)에게 revision task(input=피드백+이전출력), round 유지.
    미승인 & round>=N → "N라운드 내 미승인" notification, 다운스트림 미발화.
- dedup: (parent_task_id, edge_id) 부분 유니크 → 재배달 중복 발화 차단(이미 있으면 skip).

engine-agnostic: dev task가 done에 도달하면(item 18) 동일 경로로 전파된다.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.orm import Session

from app.models import Agent, Edge, Notification, Project, Task
from app.services import task_service as ts
from app.services.config_store import load_config

log = logging.getLogger("app.graph")

_APPROVED = re.compile(r"\bAPPROVED\b")


def _outgoing(db: Session, agent_id: uuid.UUID) -> Edge | None:
    return db.query(Edge).filter(Edge.from_agent_id == agent_id).first()


def _already_fired(db: Session, parent_id: uuid.UUID, edge_id: uuid.UUID) -> bool:
    return (
        db.query(Task.id)
        .filter(Task.parent_task_id == parent_id, Task.edge_id == edge_id)
        .first()
        is not None
    )


def _spawn(
    db: Session,
    parent: Task,
    *,
    to_agent_id: uuid.UUID,
    edge_id: uuid.UUID | None,
    instructions: str,
    input_payload: str,
    loop_state: dict | None = None,
) -> uuid.UUID | None:
    """다운스트림 task를 queued로 생성. dedup으로 재배달 중복은 skip(None)."""
    if edge_id is not None and _already_fired(db, parent.id, edge_id):
        return None
    to_agent = db.get(Agent, to_agent_id)
    if to_agent is None:
        return None
    child = ts.create_task(
        db,
        user_id=parent.user_id,
        project_id=parent.project_id,
        agent=to_agent,
        instructions=instructions,
        origin="edge",
        goal_id=parent.goal_id,
        input_payload=input_payload,
        parent_task_id=parent.id,
        edge_id=edge_id,
    )
    child.loop_state = loop_state
    db.flush()
    return child.id


def _notify(db: Session, task: Task, type_: str, message: str) -> None:
    db.add(Notification(
        user_id=task.user_id, project_id=task.project_id, agent_id=task.agent_id,
        task_id=task.id, type=type_, message=message,
    ))


def _on_reviewer_done(db: Session, reviewer_task: Task, ls: dict) -> list[uuid.UUID]:
    """리뷰어 task가 done 됐을 때의 review-loop 프로토콜(D19)."""
    edge = db.get(Edge, uuid.UUID(ls["edge_id"]))
    if edge is None:
        return []
    producer_task = db.get(Task, reviewer_task.parent_task_id) if reviewer_task.parent_task_id else None
    producer_output = (producer_task.result_markdown if producer_task else "") or ""
    approved = bool(_APPROVED.search(reviewer_task.result_markdown or ""))

    if approved:
        # 루프 종료 — 리뷰어(B)의 자체 출력 엣지(handoff)가 있으면 다운스트림 발화.
        b_edge = _outgoing(db, reviewer_task.agent_id)
        if b_edge is not None and b_edge.type == "handoff":
            nid = _spawn(
                db, reviewer_task, to_agent_id=b_edge.to_agent_id, edge_id=b_edge.id,
                instructions=producer_task.instructions if producer_task else reviewer_task.instructions,
                input_payload=producer_output,
            )
            return [nid] if nid else []
        return []

    # 미승인.
    round_ = int(ls.get("round", 1))
    if round_ < (edge.max_iterations or 1):
        # 생산자(A)에게 revision — 이전 출력 + 리뷰 피드백을 input으로.
        feedback = reviewer_task.result_markdown or ""
        nid = _spawn(
            db, reviewer_task, to_agent_id=edge.from_agent_id, edge_id=edge.id,
            instructions="Revise your previous work to address the reviewer's feedback.",
            input_payload=f"# Your previous output\n{producer_output}\n\n# Reviewer feedback\n{feedback}",
            loop_state={"kind": "revision", "round": round_, "edge_id": ls["edge_id"]},
        )
        return [nid] if nid else []

    # N 소진 — 미승인 보고.
    _notify(db, reviewer_task, "loop_exhausted",
            f"Not approved within {edge.max_iterations} review rounds.")
    return []


def propagate(db: Session, task: Task) -> list[uuid.UUID]:
    """done이 된 task의 다운스트림을 생성하고 새 task id들을 반환(커밋은 호출부)."""
    if task.stopped:
        return []
    project = db.get(Project, task.project_id)
    if project is not None and project.paused:
        return []

    cfg = load_config(db)
    if task.goal_id is not None:
        from sqlalchemy import func
        goal_count = db.query(func.count(Task.id)).filter(Task.goal_id == task.goal_id).scalar()
        if goal_count > cfg.goal_chain_budget:
            _notify(db, task, "chain_budget", f"Goal halted: exceeded {cfg.goal_chain_budget}-task chain budget.")
            return []

    ls = task.loop_state or {}
    if ls.get("kind") == "review":
        return _on_reviewer_done(db, task, ls)

    # 생산자 done(원본 또는 revision). override(D21)가 있으면 엣지 대신 그 대상으로.
    if task.override_route:
        target = task.override_route.get("to_agent_id")
        if target:
            nid = _spawn(
                db, task, to_agent_id=uuid.UUID(target), edge_id=None,
                instructions=task.instructions,
                input_payload=task.result_markdown or "",
            )
            return [nid] if nid else []
        return []

    edge = _outgoing(db, task.agent_id)
    if edge is None:
        return []  # Final output(D38).

    if edge.type == "handoff":
        nid = _spawn(
            db, task, to_agent_id=edge.to_agent_id, edge_id=edge.id,
            instructions=task.instructions,
            input_payload=task.result_markdown or "",
        )
        return [nid] if nid else []

    # review_loop: 리뷰어 task 생성(원본 done → round1, revision done → round+1).
    next_round = (int(ls.get("round", 0)) + 1) if ls.get("kind") == "revision" else 1
    nid = _spawn(
        db, task, to_agent_id=edge.to_agent_id, edge_id=edge.id,
        instructions="Review the work below. Emit APPROVED if it meets the bar; otherwise give specific, actionable feedback.",
        input_payload=task.result_markdown or "",
        loop_state={"kind": "review", "round": next_round, "edge_id": str(edge.id)},
    )
    return [nid] if nid else []
