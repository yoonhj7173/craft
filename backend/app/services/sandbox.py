"""SandboxProvider — 코드 실행 격리 추상화(item 14, D29/D31).

tech-design §10. 인터페이스 하나로 실행 환경을 추상화해 락인을 차단한다. 두 구현:

- **E2BSandboxProvider** (프로덕션): E2B Firecracker microVM. LLM이 짠 코드는 여기서만 실행되고
  제품 백엔드에서는 절대 직접 실행되지 않는다(D29). egress는 패키지 레지스트리 허용리스트만(D31).
  E2B_API_KEY가 필요하다. SDK는 지연 import(키 없는 환경에서도 모듈 로드 가능).

- **LocalSandboxProvider** (개발/테스트 전용 — 격리 없음, 프로덕션 금지): 샌드박스를 호스트의
  임시 디렉터리로 모사해 subprocess로 명령을 실행한다. 어댑터 계약을 키 없이 검증하고 상위
  레이어(WorkspaceService/dev-runner/verification, item 15-18)를 만들기 위한 것. 신뢰된 테스트
  코드만 돌린다. **신뢰할 수 없는 LLM 코드를 절대 이 프로바이더로 실행하지 말 것.**

런타임 이미지: node22-playwright / python312 (D31). Local은 호스트 런타임을 쓰므로 무시한다.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger("app.sandbox")


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class FileEntry:
    path: str       # 샌드박스 루트 기준 상대 경로
    is_dir: bool
    size: int
    mtime: float


class SandboxTimeout(Exception):
    """exec가 timeout으로 강제 종료됨."""


class SandboxProvider(Protocol):
    def create(self, project_id, runtime_image: str) -> str: ...
    def pause(self, sandbox_id: str) -> None: ...
    def resume(self, sandbox_id: str) -> None: ...
    def destroy(self, sandbox_id: str) -> None: ...
    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult: ...
    def read_file(self, sandbox_id: str, path: str) -> bytes: ...
    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None: ...
    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]: ...


# 출력 수집 시 무시할 디렉터리(node_modules 등, D31/item 17).
IGNORE_DIRS = {"node_modules", ".next", ".git", "venv", ".venv", "__pycache__", "dist", "build", ".pytest_cache"}


class LocalSandboxProvider:
    """⚠️ 개발/테스트 전용 — 격리 없음. 임시 디렉터리 + subprocess. 프로덕션 금지."""

    def __init__(self):
        self._dirs: dict[str, Path] = {}

    def create(self, project_id, runtime_image: str = "local") -> str:
        sid = f"local_{uuid.uuid4().hex[:12]}"
        d = Path(tempfile.mkdtemp(prefix=f"sbx_{sid}_"))
        self._dirs[sid] = d
        log.info("local sandbox created", extra={"sandbox_id": sid})
        return sid

    def _dir(self, sandbox_id: str) -> Path:
        d = self._dirs.get(sandbox_id)
        if d is None or not d.exists():
            raise KeyError(f"unknown sandbox {sandbox_id}")
        return d

    def pause(self, sandbox_id: str) -> None:
        # 상태가 디스크에 있으므로 no-op(파일시스템이 보존됨).
        self._dir(sandbox_id)

    def resume(self, sandbox_id: str) -> None:
        self._dir(sandbox_id)

    def destroy(self, sandbox_id: str) -> None:
        d = self._dirs.pop(sandbox_id, None)
        if d and d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult:
        d = self._dir(sandbox_id)
        run_env = {**os.environ, **(env or {})}
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(d), env=run_env,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeout(f"command timed out after {timeout}s: {cmd}") from exc
        return ExecResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        return (self._dir(sandbox_id) / path).read_bytes()

    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        target = self._dir(sandbox_id) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]:
        root = self._dir(sandbox_id).resolve()  # macOS /var→/private/var 심링크 정합.
        base = (root / path).resolve()
        entries: list[FileEntry] = []
        for p in base.rglob("*"):
            if any(part in IGNORE_DIRS for part in p.relative_to(root).parts):
                continue
            st = p.stat()
            entries.append(FileEntry(
                path=str(p.relative_to(root)), is_dir=p.is_dir(),
                size=st.st_size, mtime=st.st_mtime,
            ))
        return entries


class E2BSandboxProvider:
    """프로덕션 — E2B Firecracker microVM(D29). E2B_API_KEY 필요. SDK 지연 import.

    라이브 검증(item 14 verify)은 키가 있어야 가능. 인터페이스는 LocalSandboxProvider로
    계약 테스트되며, 프로덕션에서 이 어댑터로 교체된다.
    """

    RUNTIME_TEMPLATES = {
        "node22-playwright": "node22-playwright",  # Node 22 + Playwright 사전설치(D31).
        "python312": "python312",                  # Python 3.12.
    }

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("E2B_API_KEY")
        if not self._api_key:
            raise RuntimeError("E2B_API_KEY required for E2BSandboxProvider")
        self._handles: dict[str, object] = {}

    def _sdk(self):
        from e2b import Sandbox  # 지연 import.
        return Sandbox

    def create(self, project_id, runtime_image: str) -> str:
        Sandbox = self._sdk()
        template = self.RUNTIME_TEMPLATES.get(runtime_image, "python312")
        sbx = Sandbox(template=template, api_key=self._api_key)
        sid = sbx.sandbox_id
        self._handles[sid] = sbx
        return sid

    def _h(self, sandbox_id: str):
        h = self._handles.get(sandbox_id)
        if h is None:
            Sandbox = self._sdk()
            h = Sandbox.connect(sandbox_id, api_key=self._api_key)
            self._handles[sandbox_id] = h
        return h

    def pause(self, sandbox_id: str) -> None:
        self._h(sandbox_id).pause()

    def resume(self, sandbox_id: str) -> None:
        Sandbox = self._sdk()
        self._handles[sandbox_id] = Sandbox.resume(sandbox_id, api_key=self._api_key)

    def destroy(self, sandbox_id: str) -> None:
        h = self._handles.pop(sandbox_id, None)
        if h is not None:
            h.kill()

    def exec(self, sandbox_id: str, cmd: str, *, timeout: int = 120, env: dict | None = None) -> ExecResult:
        h = self._h(sandbox_id)
        res = h.commands.run(cmd, timeout=timeout, envs=env or {})
        return ExecResult(exit_code=res.exit_code, stdout=res.stdout, stderr=res.stderr)

    def read_file(self, sandbox_id: str, path: str) -> bytes:
        data = self._h(sandbox_id).files.read(path)
        return data.encode("utf-8") if isinstance(data, str) else data

    def write_file(self, sandbox_id: str, path: str, content: bytes) -> None:
        self._h(sandbox_id).files.write(path, content)

    def file_tree(self, sandbox_id: str, path: str = ".") -> list[FileEntry]:
        # E2B files.list는 단일 디렉터리 — 재귀는 호출부/exec(find)로. 여기선 얕은 목록.
        entries = self._h(sandbox_id).files.list(path)
        out: list[FileEntry] = []
        for e in entries:
            out.append(FileEntry(path=e.path, is_dir=(e.type == "dir"), size=getattr(e, "size", 0), mtime=0.0))
        return out


def get_provider() -> SandboxProvider:
    """프로덕션은 E2B(키 있으면), 없으면 Local(dev/test)로 폴백."""
    if os.environ.get("E2B_API_KEY"):
        return E2BSandboxProvider()
    log.warning("E2B_API_KEY not set — using LocalSandboxProvider (DEV/TEST ONLY, no isolation)")
    return LocalSandboxProvider()
