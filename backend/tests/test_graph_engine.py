"""GraphEngine tests (item 11) — LIVE Postgres, mocked Claude.

A→B→C handoff 체인, review-loop(조기 승인 / revision 후 승인 / N 소진), stop/pause 억제,
override(D21), dedup(재배달 중복 차단)을 실제 task 전파로 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

from app.crews.factory import ScriptedLLM
from app.db import SessionLocal
from app.models import Agent, Edge, Notification, Project, Task, Team
from app.services import graph_engine
from app.services import task_service as ts
from app.services import worker_core
from seed import seed


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"g_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="g")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="planning", name="Planning")  # crew
    db.add(team); db.flush()
    agents = []
    for i in range(4):
        a = Agent(team_id=team.id, project_id=proj.id, name=f"A{i}", role_instructions=f"Agent {i}", model_tier="medium", slot=i)
        db.add(a); agents.append(a)
    db.commit()
    yield db, uid, proj.id, [a.id for a in agents]
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _edge(db, pid, frm, to, type_="handoff", n=None):
    db.add(Edge(project_id=pid, from_agent_id=frm, to_agent_id=to, type=type_, max_iterations=n))
    db.commit()


def _start(db, uid, pid, agent_id, instructions="do work"):
    a = db.get(Agent, agent_id)
    t = ts.create_task(db, user_id=uid, project_id=pid, agent=a, instructions=instructions, origin="chat")
    db.commit()
    return t.id


def _drive(db, start_id, responses_by_agent):
    """queue를 collector로 구동. responses_by_agent: agent_id → list[str](에이전트별로 순서대로 소비)."""
    pools = {k: list(v) for k, v in responses_by_agent.items()}
    queue = [start_id]
    seen = []
    while queue:
        tid = queue.pop(0)
        agent_id = db.get(Task, tid).agent_id
        pool = pools.get(agent_id)
        resp = pool.pop(0) if pool else "done."
        collected: list = []
        worker_core.process_task(db, tid, llm=ScriptedLLM([resp]), enqueue=lambda x: collected.append(x))
        seen.append(tid)
        queue.extend(collected)
        if len(seen) > 30:  # 안전장치(무한루프 방지).
            break
    return seen


# --- handoff chain ---


def test_handoff_chain_a_b_c(env):
    db, uid, pid, aids = env
    a, b, c = aids[0], aids[1], aids[2]
    _edge(db, pid, a, b)
    _edge(db, pid, b, c)
    start = _start(db, uid, pid, a)
    seen = _drive(db, start, {
        a: ["Output from A"], b: ["Output from B"], c: ["Output from C"],
    })
    # 3 task가 done.
    tasks = db.query(Task).filter(Task.project_id == pid).order_by(Task.created_at).all()
    assert len(tasks) == 3
    assert all(t.status == "done" for t in tasks)
    tb = next(t for t in tasks if t.agent_id == b)
    tc = next(t for t in tasks if t.agent_id == c)
    # provenance + input_payload 전달.
    assert tb.parent_task_id == start and tb.input_payload == "Output from A" and tb.origin == "edge"
    assert tc.input_payload == "Output from B"


# --- review loop ---


def test_review_loop_approves_early(env):
    db, uid, pid, aids = env
    prod, rev = aids[0], aids[1]
    _edge(db, pid, prod, rev, type_="review_loop", n=3)
    start = _start(db, uid, pid, prod)
    _drive(db, start, {
        prod: ["Producer work v1"],
        rev: ["APPROVED — looks good"],
    })
    tasks = db.query(Task).filter(Task.project_id == pid).all()
    # 생산자 1 + 리뷰어 1 = 2, revision 없음.
    assert len(tasks) == 2
    assert all(t.status == "done" for t in tasks)
    assert not any((t.loop_state or {}).get("kind") == "revision" for t in tasks)


def test_review_loop_revision_then_approve(env):
    db, uid, pid, aids = env
    prod, rev = aids[0], aids[1]
    _edge(db, pid, prod, rev, type_="review_loop", n=3)
    start = _start(db, uid, pid, prod)
    # 리뷰어: 1라운드 미승인, 2라운드 승인.
    _drive(db, start, {
        prod: ["v1", "v2 revised"],
        rev: ["needs work: fix X", "APPROVED"],
    })
    tasks = db.query(Task).filter(Task.project_id == pid).all()
    kinds = [(t.loop_state or {}).get("kind") for t in tasks]
    assert kinds.count("review") == 2   # 두 번 리뷰
    assert kinds.count("revision") == 1  # 한 번 revision
    assert all(t.status == "done" for t in tasks)


def test_review_loop_exhausts_n(env):
    db, uid, pid, aids = env
    prod, rev = aids[0], aids[1]
    _edge(db, pid, prod, rev, type_="review_loop", n=2)
    start = _start(db, uid, pid, prod)
    _drive(db, start, {
        prod: ["v1", "v2", "v3"],
        rev: ["reject1", "reject2", "reject3"],
    })
    # N=2 소진 → loop_exhausted notification.
    notes = db.query(Notification).filter(Notification.project_id == pid, Notification.type == "loop_exhausted").all()
    assert len(notes) == 1


# --- suppression ---


def test_paused_project_suppresses_propagation(env):
    db, uid, pid, aids = env
    a, b = aids[0], aids[1]
    _edge(db, pid, a, b)
    db.get(Project, pid).paused = True
    db.commit()
    start = _start(db, uid, pid, a)
    # paused면 디스패치도 안 됨 → task가 queued로 남고 child 없음.
    worker_core.process_task(db, start, llm=ScriptedLLM(["x"]), enqueue=lambda x: None)
    assert db.query(Task).filter(Task.project_id == pid).count() == 1


def test_stopped_task_fires_nothing(env):
    db, uid, pid, aids = env
    a, b = aids[0], aids[1]
    _edge(db, pid, a, b)
    start = _start(db, uid, pid, a)
    t = db.get(Task, start)
    t.status = "done"; t.stopped = True; t.result_markdown = "x"
    db.commit()
    assert graph_engine.propagate(db, t) == []


# --- dedup ---


def test_dedup_no_double_fire(env):
    db, uid, pid, aids = env
    a, b = aids[0], aids[1]
    _edge(db, pid, a, b)
    start = _start(db, uid, pid, a)
    t = db.get(Task, start)
    t.status = "done"; t.result_markdown = "out"
    db.commit()
    first = graph_engine.propagate(db, t)
    db.commit()
    second = graph_engine.propagate(db, t)  # 재배달
    assert len([x for x in first if x]) == 1
    assert [x for x in second if x] == []  # 두 번째는 dedup으로 발화 안 함
    assert db.query(Task).filter(Task.parent_task_id == start).count() == 1


# --- override (D21) ---


def test_override_routes_once(env):
    db, uid, pid, aids = env
    a, b, c = aids[0], aids[1], aids[2]
    _edge(db, pid, a, b)  # 엣지는 b로
    start = _start(db, uid, pid, a)
    t = db.get(Task, start)
    t.status = "done"; t.result_markdown = "out"
    t.override_route = {"to_agent_id": str(c)}  # 하지만 override는 c로
    db.commit()
    ids = [x for x in graph_engine.propagate(db, t) if x]
    db.commit()
    assert len(ids) == 1
    child = db.get(Task, ids[0])
    assert child.agent_id == c  # 엣지(b) 무시, override(c)로
    assert child.edge_id is None  # override는 엣지 소비 아님(불변)
