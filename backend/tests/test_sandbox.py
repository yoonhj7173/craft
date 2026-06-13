"""SandboxProvider contract tests (item 14) — LocalSandboxProvider.

어댑터 계약을 키 없이 검증한다(E2B 라이브 검증은 E2B_API_KEY 필요 — 동일 계약).
create → exec → write/read → file_tree → pause/resume(상태 보존) → destroy, 그리고
hung 명령의 timeout kill을 확인한다.
"""

from __future__ import annotations

import pytest

from app.services.sandbox import LocalSandboxProvider, SandboxTimeout


@pytest.fixture
def provider():
    p = LocalSandboxProvider()
    yield p
    # 남은 샌드박스 정리.
    for sid in list(p._dirs.keys()):
        p.destroy(sid)


def test_create_exec_roundtrip(provider):
    sid = provider.create("proj", "python312")
    res = provider.exec(sid, "echo hello")
    assert res.exit_code == 0 and "hello" in res.stdout


def test_write_read_file(provider):
    sid = provider.create("proj", "python312")
    provider.write_file(sid, "src/app.py", b"print('hi')\n")
    assert provider.read_file(sid, "src/app.py") == b"print('hi')\n"
    # exec로도 보임.
    res = provider.exec(sid, "cat src/app.py")
    assert "print('hi')" in res.stdout


def test_file_tree_ignores_noise(provider):
    sid = provider.create("proj", "python312")
    provider.write_file(sid, "keep.txt", b"x")
    provider.write_file(sid, "node_modules/lib/index.js", b"junk")
    paths = {e.path for e in provider.file_tree(sid)}
    assert "keep.txt" in paths
    assert not any("node_modules" in p for p in paths)


def test_pause_resume_preserves_state(provider):
    sid = provider.create("proj", "python312")
    provider.write_file(sid, "state.txt", b"persisted")
    provider.pause(sid)
    provider.resume(sid)
    assert provider.read_file(sid, "state.txt") == b"persisted"


def test_destroy_removes(provider):
    sid = provider.create("proj", "python312")
    provider.write_file(sid, "f.txt", b"x")
    provider.destroy(sid)
    with pytest.raises(KeyError):
        provider.read_file(sid, "f.txt")


def test_hung_command_killed_by_timeout(provider):
    sid = provider.create("proj", "python312")
    with pytest.raises(SandboxTimeout):
        provider.exec(sid, "sleep 5", timeout=1)


def test_nonzero_exit_captured(provider):
    sid = provider.create("proj", "python312")
    res = provider.exec(sid, "exit 3")
    assert res.exit_code == 3
