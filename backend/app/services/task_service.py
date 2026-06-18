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
    """상태 바꾸기(검문소) — 작업의 상태를 바꿀 때 반드시 거치는 단 하나의 통로.

    무슨 일을 하나: 작업 상태(queued/working/done 등)를 바꾸려는 모든 시도가 여기를 지난다.
        전이표(_LEGAL)에 없는 불법 변경(예: 이미 끝난 done → working)이면 거부(예외)하고,
        합법이면 상태를 바꾸고 로그를 남긴다. "상태 변경은 무조건 이 함수로만" = 버그 예방의 핵심.
    누가 부르나: try_dispatch, stop, request_continue, 그리고 worker_core의 작업 처리 곳곳.
    처리 순서: 1) 현재→새 상태가 합법인지 검사 2) 불법이면 IllegalTransition 예외
        3) 합법이면 상태 + 함께 넘어온 컬럼(result_markdown 등)을 갱신 4) 로그.
    연결: 합법 전이표는 이 파일 위쪽 _LEGAL. 커밋(DB 확정)은 호출한 쪽 책임.
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
    """디스패치 게이트(5단계 안전장치) — 지금 이 작업을 시작해도 되는지 막는 이유들을 모아 돌려준다.

    무슨 일을 하나: 대기(queued) 작업을 실제로 돌리기 전, 5가지 조건을 검사한다. 하나라도
        걸리면 그 이름을 목록에 담는다. 빈 목록이면 = 지금 시작해도 OK. 비용 폭주·과부하를 막는 곳.
    5가지 게이트(= 돈/리소스 안전장치):
        ① project_paused   : 프로젝트가 일시정지 상태면 차단(사용자가 멈춤 버튼 누른 경우).
        ② agent_busy       : 그 에이전트가 이미 다른 일을 하는 중이면 차단(한 명당 한 번에 1건).
        ③ concurrency_cap  : 이 사용자가 동시에 돌리는 작업 수가 상한을 넘으면 차단.
        ④ daily_cost_cap   : 오늘 쓴 LLM 비용이 하루 한도를 넘으면 차단(요금 폭탄 방지).
        ⑤ goal_chain_budget: 한 목표에 딸린 작업이 너무 많이 불어나면 차단(무한 증식 방지).
    누가 부르나: try_dispatch가 디스패치 직전에. (관측/디버깅용으론 직접 호출도 가능)
    연결: 한도 값들(cap/budget)은 config 테이블에서 → load_config (backend/app/services/config_store.py).
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
    """작업 시작 시도 — 5게이트를 통과하면 '대기 → 작업중'으로 바꾸고 출발시킨다.

    무슨 일을 하나: 대기 작업을 집어 게이트(dispatch_blockers)를 통과하면 working으로 바꾼다.
        통과 못 하면 그대로 두고 False(나중에 다시 시도됨).
    누가 부르나: 백그라운드 워커가 작업을 꺼낼 때 — process_task (backend/app/services/worker_core.py).
    처리 순서:
        1. 그 작업 행을 잠근다(FOR UPDATE — 같은 작업을 두 워커가 동시에 집는 경쟁 상태 방지).
        2. 아직 queued인지 확인(이미 누가 가져갔으면 False).
        3. dispatch_blockers로 5게이트 재검사 → 걸리면 False.
        4. 다 통과하면 transition으로 working 전이 → True.
    연결: 게이트 본체 → 위 dispatch_blockers. 상태 변경 → 위 transition.
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
    """작업 멈추기 — 사용자가 'Stop'을 눌렀을 때 진행 중인 작업을 강제 종료한다.

    무슨 일을 하나: 작업을 failed로 만들되, 에러로 인한 실패와 구분하려고 stopped=True 표시를 단다.
        이 표시가 있으면 다음 단계로 일이 전파(handoff)되지 않는다(멈췄는데 뒷일이 굴러가면 안 되므로).
    누가 부르나: POST /api/tasks/{id}/stop — backend/app/routers/tasks.py.
    처리 순서: 이미 끝난(done/failed) 작업이면 그대로 둔다. 대기/작업중이면 failed + stopped 표시.
        dev 작업이면 kill_hook으로 샌드박스에서 돌던 명령도 실제로 죽인다.
    연결: 멈춤 호출 입구 → backend/app/routers/tasks.py.
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
    """이어서 하기 — 질문하느라 멈춘 작업에 사용자의 답을 붙이고 다시 대기열에 올린다.

    무슨 일을 하나: blocked/needs-input(입력 대기) 작업을 다시 queued로 돌리면서, 사용자가 준
        입력(답)을 continuations 목록에 쌓는다. 다음에 워커가 이 작업을 다시 돌릴 때, 쌓인 입력이
        프롬프트에 함께 들어가 에이전트가 "이어서" 일하게 된다. (작업을 처음부터 재실행하되,
        그동안의 부분 결과 + 추가 입력을 프롬프트에 넣어주는 방식 = §14)
    누가 부르나: resume_task 도구(orchestrator) 또는 POST /api/tasks/{id}/continue(tasks.py).
    연결: 쌓인 입력을 프롬프트에 넣는 곳 → assemble_prompt (backend/app/services/prompt.py).
    """
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
    """작업 만들기 — 에이전트에게 줄 새 작업 1건을 '대기(queued)' 상태로 만든다.

    무슨 일을 하나: tasks 테이블에 작업 1줄을 추가한다. 어떤 엔진(crew=글쓰기형 / agent_sdk=코딩형)으로
        돌릴지는 그 에이전트가 속한 팀 종류를 보고 미리 박아둔다(나중에 빠르게 조회하려고 = 비정규화).
    누가 부르나: 두 곳 — 사용자 지시(dispatch_task in orchestrator.py)와 자동 전파(_spawn in graph_engine.py).
    연결: 만든 작업을 실제 처리 → process_task (backend/app/services/worker_core.py).
    """
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
