"""TaskService tests (item 8) — LIVE Postgres.

7상태 전이표(합법/불법), 5 디스패치 게이트(단독+조합), stop(두 상태에서), continue를
실제 DB 행으로 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Config, Goal, Project, Team, Task
from app.services import task_service as ts
from app.services.config_store import load_config
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def scratch(db):
    """user/project/team/agent 1세트 생성 후 정리(cascade)."""
    uid = f"ts_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="ts")
    db.add(proj)
    db.flush()
    team = Team(project_id=proj.id, template_key="planning", name="Planning")
    db.add(team)
    db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="PM", role_instructions="x", model_tier="strong", slot=0)
    db.add(agent)
    db.commit()
    yield uid, proj, team, agent
    db.delete(db.get(Project, proj.id))
    db.commit()


def _task(db, uid, proj, agent, status="queued", **kw):
    t = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent, instructions="t", origin="chat", **kw)
    db.flush()
    if status != "queued":
        t.status = status  # 테스트 셋업용 직접 설정(전이표 우회).
    db.commit()
    return t


# --- 전이표 ---


def test_legal_transitions():
    assert ts.is_legal("queued", "working")
    assert ts.is_legal("queued", "failed")
    assert ts.is_legal("working", "done")
    assert ts.is_legal("working", "blocked")
    assert ts.is_legal("working", "needs-input")
    assert ts.is_legal("blocked", "queued")
    assert ts.is_legal("needs-input", "queued")


@pytest.mark.parametrize("old,new", [
    ("queued", "done"),       # 디스패치 없이 완료 불가
    ("queued", "blocked"),
    ("done", "working"),      # terminal에서 못 나감
    ("failed", "queued"),
    ("blocked", "working"),   # continue는 queued 경유
    ("working", "queued"),
])
def test_illegal_transitions(old, new):
    assert not ts.is_legal(old, new)


def test_transition_rejects_illegal(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent, status="done")
    with pytest.raises(ts.IllegalTransition):
        ts.transition(db, t, "working")
    db.rollback()


# --- 디스패치 게이트 ---


def test_dispatch_ok_when_clear(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent)
    assert ts.dispatch_blockers(db, t) == []
    assert ts.try_dispatch(db, t) is True
    db.commit()
    assert db.get(Task, t.id).status == "working"


def test_gate_project_paused(db, scratch):
    uid, proj, team, agent = scratch
    proj.paused = True
    db.commit()
    t = _task(db, uid, proj, agent)
    assert "project_paused" in ts.dispatch_blockers(db, t)
    assert ts.try_dispatch(db, t) is False
    db.rollback()


def test_gate_agent_busy(db, scratch):
    uid, proj, team, agent = scratch
    _task(db, uid, proj, agent, status="working")  # 이미 working
    t2 = _task(db, uid, proj, agent)
    assert "agent_busy" in ts.dispatch_blockers(db, t2)


def test_gate_concurrency_cap(db, scratch):
    uid, proj, team, agent = scratch
    # cap=3 가정 — 다른 에이전트 3개를 working으로.
    for i in range(3):
        a = Agent(team_id=team.id, project_id=proj.id, name=f"A{i}", role_instructions="x", model_tier="medium", slot=i + 1)
        db.add(a)
        db.flush()
        _task(db, uid, proj, a, status="working")
    t = _task(db, uid, proj, agent)
    assert "concurrency_cap" in ts.dispatch_blockers(db, t)


def test_gate_daily_cost_cap(db, scratch):
    uid, proj, team, agent = scratch
    cfg = load_config(db)
    # 오늘 비용을 cap 이상으로 만든 task 하나.
    big = _task(db, uid, proj, agent, status="done")
    big.est_cost_usd = cfg.daily_cost_cap_usd + 1
    db.commit()
    t = _task(db, uid, proj, agent)
    assert "daily_cost_cap" in ts.dispatch_blockers(db, t)


def test_gate_goal_chain_budget(db, scratch):
    uid, proj, team, agent = scratch
    goal = Goal(project_id=proj.id, title="g")
    db.add(goal)
    db.flush()
    cfg = load_config(db)
    # budget+1 개의 task를 goal에 묶는다.
    for _ in range(cfg.goal_chain_budget + 1):
        _task(db, uid, proj, agent, status="done", goal_id=goal.id)
    t = _task(db, uid, proj, agent, goal_id=goal.id)
    assert "goal_chain_budget" in ts.dispatch_blockers(db, t)


def test_gates_combine(db, scratch):
    uid, proj, team, agent = scratch
    proj.paused = True
    db.commit()
    _task(db, uid, proj, agent, status="working")
    t = _task(db, uid, proj, agent)
    blockers = ts.dispatch_blockers(db, t)
    assert {"project_paused", "agent_busy"} <= set(blockers)


# --- stop / continue ---


def test_stop_working_task(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent, status="working")
    ts.stop(db, t)
    db.commit()
    row = db.get(Task, t.id)
    assert row.status == "failed" and row.stopped is True


def test_stop_queued_task(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent)  # queued
    ts.stop(db, t)
    db.commit()
    row = db.get(Task, t.id)
    assert row.status == "failed" and row.stopped is True


def test_stop_waiting_task(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent, status="needs-input")
    ts.stop(db, t)
    db.commit()
    assert db.get(Task, t.id).status == "failed"


def test_stop_terminal_noop(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent, status="done")
    ts.stop(db, t)
    db.commit()
    assert db.get(Task, t.id).status == "done"  # 무변경


def test_continue_reenqueues(db, scratch):
    uid, proj, team, agent = scratch
    t = _task(db, uid, proj, agent, status="needs-input")
    t.awaiting_prompt = "which option?"
    db.commit()
    ts.request_continue(db, t, "option B", via="panel")
    db.commit()
    row = db.get(Task, t.id)
    assert row.status == "queued"
    assert row.attempt == 1
    assert row.awaiting_prompt is None
    assert row.continuations[-1]["text"] == "option B"
    assert row.continuations[-1]["via"] == "panel"
