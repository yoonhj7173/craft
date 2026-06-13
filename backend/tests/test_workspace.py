"""WorkspaceService lifecycle tests (item 15) — LIVE Postgres + LocalSandboxProvider.

lazy create → reuse, idle pause → resume, boot 실패 → error+재생성, destroy를 검증한다.
(E2B 라이브 검증은 동일 계약 + E2B_API_KEY 필요.)
"""

from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models import Agent, Project, Team
from app.services import task_service as ts
from app.services.sandbox import LocalSandboxProvider
from app.services.workspace import WorkspaceError, WorkspaceService


@pytest.fixture
def env():
    db = SessionLocal()
    uid = f"ws_{uuid.uuid4().hex[:8]}"
    proj = Project(user_id=uid, name="ws")
    db.add(proj); db.flush()
    team = Team(project_id=proj.id, template_key="development", name="Dev")  # agent_sdk
    db.add(team); db.flush()
    agent = Agent(team_id=team.id, project_id=proj.id, name="SWE", role_instructions="swe", model_tier="strong", slot=0)
    db.add(agent); db.commit()
    pid = proj.id
    yield db, uid, proj, agent
    obj = db.get(Project, pid)  # API 테스트가 이미 삭제했을 수 있음.
    if obj is not None:
        db.delete(obj); db.commit()
    db.close()


def _ws():
    return WorkspaceService(LocalSandboxProvider())


def test_lazy_create_then_reuse(env):
    db, uid, proj, agent = env
    ws = _ws()
    sid1 = ws.ensure_running(db, proj)
    assert proj.sandbox_id == sid1 and proj.sandbox_status == "running"
    sid2 = ws.ensure_running(db, proj)
    assert sid2 == sid1  # 재사용(새 생성 없음)


def test_pause_if_idle_then_resume(env):
    db, uid, proj, agent = env
    ws = _ws()
    ws.ensure_running(db, proj)
    # 진행 중 dev task 없음 → pause.
    assert ws.pause_if_idle(db, proj) is True
    assert proj.sandbox_status == "paused"
    # 다음 ensure_running → resume(같은 id).
    sid = ws.ensure_running(db, proj)
    assert proj.sandbox_status == "running" and sid == proj.sandbox_id


def test_pause_skipped_when_active_dev_task(env):
    db, uid, proj, agent = env
    ws = _ws()
    ws.ensure_running(db, proj)
    t = ts.create_task(db, user_id=uid, project_id=proj.id, agent=agent, instructions="build", origin="chat")
    t.status = "working"; db.commit()
    # 활성 dev task가 있으면 pause 안 함.
    assert ws.pause_if_idle(db, proj) is False
    assert proj.sandbox_status == "running"


def test_boot_failure_sets_error_and_recreates(env):
    db, uid, proj, agent = env

    class FlakyProvider(LocalSandboxProvider):
        def __init__(self):
            super().__init__()
            self.fail_next = True

        def create(self, project_id, runtime_image="local"):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError("boot boom")
            return super().create(project_id, runtime_image)

    ws = WorkspaceService(FlakyProvider())
    with pytest.raises(WorkspaceError):
        ws.ensure_running(db, proj)
    assert proj.sandbox_status == "error"
    # 재시도 → 성공(recreate).
    sid = ws.ensure_running(db, proj)
    assert proj.sandbox_status == "running" and sid


def test_destroy_clears_bookkeeping(env):
    db, uid, proj, agent = env
    ws = _ws()
    sid = ws.ensure_running(db, proj)
    ws.destroy(db, proj)
    db.commit()
    assert proj.sandbox_id is None and proj.sandbox_status == "none"
    # 프로바이더에서도 제거.
    assert sid not in ws.provider._dirs


def test_project_delete_destroys_sandbox(client, auth, env):
    db, uid, proj, agent = env
    # API로 워크스페이스를 띄운 뒤(싱글턴) 프로젝트 삭제 시 destroy 호출 확인.
    from app.services.workspace import workspace_service
    sid = workspace_service.ensure_running(db, proj)
    assert sid in workspace_service.provider._dirs
    pid = str(proj.id)
    assert client.delete(f"/api/projects/{pid}", headers=auth(uid)).status_code == 204
    assert sid not in workspace_service.provider._dirs  # destroy됨
