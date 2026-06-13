"""SSE / Notifications / Board / Usage tests (item 12) — LIVE Postgres + Redis.

실 전이가 채널에 task_status/notification 이벤트를 싣는지(Redis 구독), board가 dispatched
goal을 반영하는지, usage 합계가 행과 일치하는지, notification CRUD를 검증한다.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from app.crews.factory import ScriptedLLM
from app.db import SessionLocal, redis_client
from app.models import Agent, Goal, Project, Task, Team
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
    uid = f"r_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="r")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="planning", name="Planning")
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="PM", role_instructions="PM", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    yield db, uid, proj.id, team.id, agent.id
    db.delete(db.get(Project, proj.id)); db.commit()
    db.close()


def _collect(pubsub, timeout=2.0):
    """timeout 동안 채널의 모든 메시지를 수집한다(이벤트 publish는 거의 즉시)."""
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.3)
        if msg and msg["type"] == "message":
            seen.append(json.loads(msg["data"]))
    return seen


# --- SSE channel events on real transition ---


def test_transition_emits_status_and_notification(env):
    db, uid, pid, tid, aid = env
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"project:{pid}")
    try:
        agent = db.get(Agent, aid)
        t = ts.create_task(db, user_id=uid, project_id=pid, agent=agent, instructions="go", origin="chat")
        db.commit()
        worker_core.process_task(db, t.id, llm=ScriptedLLM(["all done summary"]))
        # 채널에서 task_status + notification 둘 다 수신.
        all_seen = _collect(pubsub)
        types = {e.get("type") for e in all_seen}
        assert "task_status" in types
        assert "notification" in types
        assert any(e.get("type") == "task_status" and e.get("status") == "done" for e in all_seen)
        # notification 행도 생성됨.
        from app.models import Notification
        assert db.query(Notification).filter_by(project_id=pid, type="done").count() == 1
    finally:
        pubsub.close()


# --- Board ---


def test_board_mirrors_dispatched_goal(client, auth, env):
    db, uid, pid, tid, aid = env
    # goal + 2 task를 그 goal에 묶어 생성.
    goal = Goal(project_id=pid, title="Launch")
    db.add(goal); db.flush()
    agent = db.get(Agent, aid)
    for i in range(2):
        ts.create_task(db, user_id=uid, project_id=pid, agent=agent, instructions=f"step {i}", origin="chat", goal_id=goal.id)
    db.commit()

    board = client.get(f"/api/projects/{pid}/board", headers=auth(uid)).json()
    launch = next(g for g in board["goals"] if g["title"] == "Launch")
    assert len(launch["tasks"]) == 2
    assert launch["tasks"][0]["agent_name"] == "PM"


# --- Usage ---


def test_usage_sums_match_rows(client, auth, env):
    db, uid, pid, tid, aid = env
    agent = db.get(Agent, aid)
    # 토큰/비용이 든 task 2개 직접 심기.
    for ti, to, c in [(100, 50, 0.001), (200, 80, 0.002)]:
        t = ts.create_task(db, user_id=uid, project_id=pid, agent=agent, instructions="x", origin="chat")
        t.status = "done"; t.tokens_in = ti; t.tokens_out = to; t.est_cost_usd = c
    db.commit()

    usage = client.get(f"/api/projects/{pid}/usage", headers=auth(uid)).json()
    assert usage["total_tokens_in"] == 300
    assert usage["total_tokens_out"] == 130
    assert abs(usage["total_cost_usd"] - 0.003) < 1e-6
    # 에이전트별/팀별 모두 1개씩(에이전트 1명).
    assert len(usage["by_agent"]) == 1 and usage["by_agent"][0]["tokens_in"] == 300
    assert len(usage["by_team"]) == 1 and usage["by_team"][0]["tokens_out"] == 130


# --- Notifications ---


def test_notifications_list_and_read(client, auth, env):
    db, uid, pid, tid, aid = env
    from app.models import Notification
    db.add(Notification(user_id=uid, project_id=pid, agent_id=aid, type="done", message="PM finished"))
    db.commit()

    lst = client.get("/api/notifications", headers=auth(uid)).json()
    assert len(lst) >= 1 and lst[0]["read"] is False
    assert client.post("/api/notifications/read-all", headers=auth(uid)).status_code == 204
    lst2 = client.get("/api/notifications", headers=auth(uid)).json()
    assert all(n["read"] for n in lst2)


# --- SSE endpoint smoke ---


def test_sse_requires_auth(client, env):
    db, uid, pid, tid, aid = env
    assert client.get(f"/api/projects/{pid}/sse").status_code == 401
