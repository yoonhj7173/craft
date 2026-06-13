"""TaskService — 7상태 전이표 + 5 디스패치 게이트 + stop/continue (item 8).

tech-design §13. tasks.status가 단일 권위. 저장되는 task는 queued에서 시작하고 idle은
API 유도값(저장 안 함). 모든 상태 쓰기는 transition()을 거쳐 합법성 검사 + 로깅된다.

전이표(합법):
  queued    → working | failed
  working   → done | failed | blocked | needs-input
  blocked   → queued        (continue)
  needs-input → queued      (continue)
  done, failed = terminal

디스패치 게이트(원자적, 순서대로 — queued→working 허용 판단):
  ① project not paused (D16)
  ② agent not busy (D17, 한 번에 1개)
  ③ concurrency cap (유저 working 수 < cap)
  ④ daily cost cap (오늘 비용 < cap)
  ⑤ goal chain budget (goal task 수 < budget)

stop: queued/working → failed + stopped=True(전파 억제 belt) + engine kill hook(dev는 item 18).
continue: blocked/needs-input → queued + attempt+1 + continuation append (재큐잉, §14).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Agent, Task
from app.services.config_store import GuardConfig, load_config

log = logging.getLogger("app.task_service")

# 활성(미종결) 상태 — 에이전트 busy 판정 + remove 게이트.
ACTIVE = ("queued", "working", "blocked", "needs-input")
TERMINAL = ("done", "failed")

# 합법 전이표.
_LEGAL: dict[str, set[str]] = {
    "queued": {"working", "failed"},
    "working": {"done", "failed", "blocked", "needs-input"},
    "blocked": {"queued"},
    "needs-input": {"queued"},
    "done": set(),
    "failed": set(),
}


class IllegalTransition(Exception):
    """전이표에 없는 상태 전이 시도."""


def is_legal(old: str, new: str) -> bool:
    return new in _LEGAL.get(old, set())


def transition(db: Session, task: Task, new_status: str, **fields) -> Task:
    """상태 전이를 검증·적용·로깅한다. 불법이면 IllegalTransition.

    fields로 함께 갱신할 컬럼(result_markdown, error_summary, awaiting_prompt 등)을 받는다.
    커밋은 호출부 책임(트랜잭션 경계 제어).
    """
    old = task.status
    if not is_legal(old, new_status):
        log.warning("illegal transition", extra={"task_id": str(task.id), "old": old, "new": new_status})
        raise IllegalTransition(f"{old} → {new_status}")
    task.status = new_status
    for k, v in fields.items():
        setattr(task, k, v)
    log.info("task transition", extra={"task_id": str(task.id), "old": old, "new": new_status})
    return task


# --- 디스패치 게이트 ---


def dispatch_blockers(db: Session, task: Task, cfg: GuardConfig | None = None) -> list[str]:
    """queued task를 지금 디스패치할 수 없게 막는 게이트 이름 목록(빈 리스트=가능).

    순서대로 평가하되 전부 모아 반환(디버깅/관측). try_dispatch는 첫 게이트에서 멈춰도 동일.
    """
    if cfg is None:
        cfg = load_config(db)
    from app.models import Project, Goal  # 지연 import(순환 방지)

    blockers: list[str] = []

    # ① project paused
    project = db.get(Project, task.project_id)
    if project is not None and project.paused:
        blockers.append("project_paused")

    # ② agent busy — 같은 에이전트의 다른 working task가 있으면 busy.
    busy = (
        db.query(Task.id)
        .filter(Task.agent_id == task.agent_id, Task.id != task.id, Task.status == "working")
        .first()
    )
    if busy is not None:
        blockers.append("agent_busy")

    # ③ concurrency cap — 유저 working 수.
    working_count = (
        db.query(func.count(Task.id))
        .filter(Task.user_id == task.user_id, Task.status == "working")
        .scalar()
    )
    if working_count >= cfg.concurrency_cap:
        blockers.append("concurrency_cap")

    # ④ daily cost cap — 오늘(UTC) 유저 비용 합.
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_cost = (
        db.query(func.coalesce(func.sum(Task.est_cost_usd), 0))
        .filter(Task.user_id == task.user_id, Task.created_at >= start_of_day)
        .scalar()
    )
    if float(today_cost) >= cfg.daily_cost_cap_usd:
        blockers.append("daily_cost_cap")

    # ⑤ goal chain budget — goal에 묶인 task 수.
    if task.goal_id is not None:
        goal_count = (
            db.query(func.count(Task.id)).filter(Task.goal_id == task.goal_id).scalar()
        )
        if goal_count > cfg.goal_chain_budget:
            blockers.append("goal_chain_budget")

    return blockers


def try_dispatch(db: Session, task: Task) -> bool:
    """게이트 통과 시 queued→working으로 원자적 디스패치. 성공 True / 막히면 False.

    경쟁 상황(동시 디스패치가 cap 초과)을 막기 위해 task 행을 FOR UPDATE로 잠그고 게이트를
    재평가한다. 커밋은 호출부.
    """
    locked = (
        db.query(Task).filter(Task.id == task.id).with_for_update().one()
    )
    if locked.status != "queued":
        return False
    if dispatch_blockers(db, locked):
        return False
    transition(db, locked, "working")
    return True


# --- stop / continue ---


def stop(db: Session, task: Task, *, kill_hook=None) -> Task:
    """Stop(D16) — queued/working면 failed + stopped=True. 이미 종결이면 무변경.

    kill_hook(engine-aware): dev task의 샌드박스 명령 종료(item 18에서 주입). 여기선 호출만.
    """
    if task.status in TERMINAL:
        return task
    if task.status in ("blocked", "needs-input"):
        # 대기 중인 task도 멈출 수 있다(전이표상 직접 failed는 불가하므로 별도 처리).
        task.status = "failed"
        task.stopped = True
        task.error_summary = "Stopped by user"
        log.info("task stopped (waiting)", extra={"task_id": str(task.id)})
        return task
    if kill_hook is not None and task.engine == "agent_sdk":
        kill_hook(task)
    transition(db, task, "failed", stopped=True, error_summary="Stopped by user")
    return task


def request_continue(db: Session, task: Task, input_text: str, via: str) -> Task:
    """blocked/needs-input → queued 재큐잉(§14). attempt+1 + continuation append."""
    if task.status not in ("blocked", "needs-input"):
        raise IllegalTransition(f"cannot continue from {task.status}")
    continuations = list(task.continuations or [])
    continuations.append(
        {"at": datetime.now(timezone.utc).isoformat(), "via": via, "text": input_text}
    )
    transition(
        db,
        task,
        "queued",
        attempt=task.attempt + 1,
        continuations=continuations,
        awaiting_prompt=None,
    )
    return task


# --- create ---


def create_task(
    db: Session,
    *,
    user_id: str,
    project_id: uuid.UUID,
    agent: Agent,
    instructions: str,
    origin: str,
    goal_id: uuid.UUID | None = None,
    input_payload: str | None = None,
    parent_task_id: uuid.UUID | None = None,
    edge_id: uuid.UUID | None = None,
) -> Task:
    """새 task를 queued로 생성한다. engine은 agent의 팀 템플릿에서 비정규화(D43)."""
    from app.models import Team, TeamTemplate

    team = db.get(Team, agent.team_id)
    tmpl = db.get(TeamTemplate, team.template_key) if team else None
    engine = tmpl.engine if tmpl else "crew"

    task = Task(
        user_id=user_id,
        project_id=project_id,
        agent_id=agent.id,
        goal_id=goal_id,
        origin=origin,
        engine=engine,
        status="queued",
        instructions=instructions,
        input_payload=input_payload,
        parent_task_id=parent_task_id,
        edge_id=edge_id,
    )
    db.add(task)
    return task
