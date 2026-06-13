"""WorkspaceService — 프로젝트 워크스페이스 수명주기(item 15, D29).

Track 1이 보는 유일한 실행 인터페이스(tech-design §10). SandboxProvider 위에서 프로젝트당
샌드박스 1개를 lazy 생성·재개·일시정지·파기하고 projects.sandbox_id/status를 관리한다.

- ensure_running(project): 첫 dev/design task에 lazy 생성, paused면 resume, 죽었으면 recreate.
  boot/resume 실패 → sandbox_status='error' + WorkspaceError(호출부가 task를 clean fail).
- pause_if_idle(project): 진행 중 agent_sdk task가 없으면 pause(과금 정지).
- kill_current(project): 실행 중 명령 종료(E2B 의미, Local best-effort) — Stop 훅(item 8/18).
- destroy(project): 샌드박스 파기 + 북킹 초기화(프로젝트 삭제 시).

run_dev_task / collect_outputs는 item 16/17에서 추가된다.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Project, Task
from app.services.sandbox import SandboxProvider, get_provider

log = logging.getLogger("app.workspace")

# 프로젝트 워크스페이스 런타임 이미지(Node 22 + Python 3.12 + Playwright, §10/D31).
WORKSPACE_RUNTIME = "node22-playwright"


class WorkspaceError(Exception):
    """샌드박스 boot/resume 실패 — 호출부는 task를 clean fail 시킨다."""


class WorkspaceService:
    def __init__(self, provider: SandboxProvider | None = None):
        self.provider = provider or get_provider()

    def _alive(self, sandbox_id: str) -> bool:
        try:
            self.provider.exec(sandbox_id, "true", timeout=10)
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure_running(self, db: Session, project: Project) -> str:
        """실행 중 샌드박스 id를 보장한다(생성/재개/재생성). 실패 시 WorkspaceError."""
        # 이미 running이고 살아있으면 그대로.
        if project.sandbox_id and project.sandbox_status == "running" and self._alive(project.sandbox_id):
            return project.sandbox_id

        # paused면 resume 시도.
        if project.sandbox_id and project.sandbox_status == "paused":
            try:
                self.provider.resume(project.sandbox_id)
                if self._alive(project.sandbox_id):
                    project.sandbox_status = "running"
                    db.commit()
                    return project.sandbox_id
            except Exception:  # noqa: BLE001 — resume 실패 → 재생성으로.
                log.warning("resume failed, recreating", extra={"project_id": str(project.id)})

        # 새로 생성(또는 죽은 샌드박스 재생성).
        try:
            sid = self.provider.create(project.id, WORKSPACE_RUNTIME)
        except Exception as exc:  # noqa: BLE001
            project.sandbox_status = "error"
            db.commit()
            raise WorkspaceError(f"sandbox boot failed: {exc}") from exc

        project.sandbox_id = sid
        project.sandbox_status = "running"
        db.commit()
        log.info("workspace running", extra={"project_id": str(project.id), "sandbox_id": sid})
        return sid

    def _has_active_dev_task(self, db: Session, project_id) -> bool:
        return (
            db.query(Task.id)
            .filter(
                Task.project_id == project_id,
                Task.engine == "agent_sdk",
                Task.status.in_(("queued", "working")),
            )
            .first()
            is not None
        )

    def pause_if_idle(self, db: Session, project: Project) -> bool:
        """진행 중 dev/design task가 없으면 pause(과금 정지). pause했으면 True."""
        if not project.sandbox_id or project.sandbox_status != "running":
            return False
        if self._has_active_dev_task(db, project.id):
            return False
        try:
            self.provider.pause(project.sandbox_id)
            project.sandbox_status = "paused"
            db.commit()
            return True
        except Exception:  # noqa: BLE001
            log.warning("pause failed", extra={"project_id": str(project.id)})
            return False

    def kill_current(self, db: Session, project: Project) -> None:
        """실행 중 명령 종료(Stop, D16). E2B는 명령 kill, Local은 best-effort."""
        if not project.sandbox_id:
            return
        try:
            # E2B: 실행 중 명령 인터럽트. Local: 모사 한계로 no-op.
            kill = getattr(self.provider, "kill_current", None)
            if callable(kill):
                kill(project.sandbox_id)
        except Exception:  # noqa: BLE001
            log.warning("kill_current failed", extra={"project_id": str(project.id)})

    def destroy(self, db: Session, project: Project) -> None:
        """샌드박스 파기 + 북킹 초기화(프로젝트 삭제 시)."""
        if project.sandbox_id:
            try:
                self.provider.destroy(project.sandbox_id)
            except Exception:  # noqa: BLE001
                log.warning("destroy failed", extra={"project_id": str(project.id)})
        project.sandbox_id = None
        project.sandbox_status = "none"


# 프로세스 공유 싱글턴(Local 프로바이더의 dir 매핑을 유지하기 위해 필수).
workspace_service = WorkspaceService()
