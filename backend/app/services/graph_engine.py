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
    """다음 작업 만들기(전파 일꾼) — 연결선을 따라 받을 쪽 에이전트에게 새 작업을 만들어준다.

    무슨 일을 하나: 같은 (부모작업, 엣지) 조합으로 이미 만든 적 있으면 건너뛰고(중복 방지 = dedup),
        아니면 받을 에이전트에게 작업을 queued로 생성한다. 누가 부르나: propagate / _on_reviewer_done.
    """
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
    """검토 반복 처리 — 리뷰어가 검토를 끝냈을 때 '통과/수정요청'에 따라 다음을 정한다.

    무슨 일을 하나: review_loop(검토 반복) 연결에서, 리뷰어 작업이 끝나면 그 결과를 본다.
        - 'APPROVED'(통과) 단어가 있으면 → 루프 종료. 리뷰어에게 또 다른 handoff가 있으면 그쪽으로 진행.
        - 통과 아님 & 아직 라운드 남음 → 원작성자(A)에게 '리뷰 피드백 반영해 수정' 작업을 돌려준다.
        - 통과 아님 & 최대 라운드 소진 → "N번 안에 통과 못 함" 알림하고 멈춘다.
    누가 부르나: propagate가 끝난 작업이 리뷰 작업이었을 때.
    연결: 작업 생성 → 이 파일 _spawn. 최대 횟수(max_iterations)는 엣지에 저장됨.
    """
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
    """자동 전파(이어달리기) — 작업이 끝나면 연결선(엣지)을 따라 다음 에이전트에게 일을 넘긴다.

    이것이 "사용자가 일일이 시키지 않아도 회사가 알아서 굴러가는" 핵심이다. 사용자가 맵에서
    A→B로 선을 그어두면, A가 끝나는 순간 B의 작업이 자동으로 생긴다.

    무슨 일을 하나: 방금 done이 된 작업을 보고, 그 에이전트의 출력 연결선을 따라 다음 작업을 만든다.
    누가 부르나: 작업 완료 마무리 — _finalize_done (backend/app/services/worker_core.py).
    처리 순서(전파 규칙):
        1. 억제: 사용자가 멈춘 작업(stopped)이거나 프로젝트가 일시정지면 아무것도 안 함.
        2. 예산 초과: 한 목표의 작업이 너무 많이 불었으면 중단 + 알림(무한 증식 방지).
        3. 일회성 우회(override): 지휘자가 "이번만 다른 사람에게" 지정했으면 그쪽으로 1건.
        4. 연결선(엣지) 종류로 분기:
           - 연결선 없음 → 여기가 마지막. 최종 결과물(Final output)로 끝.
           - handoff(넘기기) → 다음 에이전트에게 'A의 결과'를 입력으로 주는 작업 생성.
           - review_loop(검토 반복) → 리뷰어에게 검토 작업을 생성(리뷰 결과는 _on_reviewer_done이 처리).
    연결: 검토 반복 프로토콜 → 이 파일 _on_reviewer_done. 실제 작업 생성 → 이 파일 _spawn.
        반환한 자식 id들을 worker_core가 큐에 올려 다시 process_task로 돌린다.
    """
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
