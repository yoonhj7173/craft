"""Dev-runner — 샌드박스 안에서 도는 코딩 에이전트 루프(item 16, D30/D31).

dev/design task 1건마다 새 에이전트 세션을 워크스페이스(SandboxProvider) 안에서 돌린다:
bash/file 도구로 코드를 쓰고 명령을 실행하며, 모든 명령+exit code를 tasks.verification으로
기록한다("working as expected" 증적, D31). 센티넬: AWAITING_INPUT → needs-input,
APPROVED(리뷰어) → GraphEngine이 루프 종료(D19). per-command + per-task(기본 30분) 타임아웃.

LLM "brain"은 주입 가능(테스트=스크립트). 프로덕션은 Claude Agent SDK / LiteLLM 툴루프를
이 인터페이스 뒤에 꽂는다(루프/도구/검증은 동일). re-enqueue 철학 유지 — 세션은 매번 새로
시작하고 워크스페이스가 구체 상태를 들고 있다(§14).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from app.crews.base import detect_needs_input
from app.services.orchestrator import LLMResponse, ToolCall  # 정규화된 응답 재사용
from app.services.sandbox import SandboxProvider, SandboxTimeout

log = logging.getLogger("app.dev_runner")

MAX_STEPS = 40
DEFAULT_TASK_TIMEOUT_SEC = 30 * 60
PER_COMMAND_TIMEOUT_SEC = 300
_SUMMARY_CAP = 2000

# dev 에이전트 도구(샌드박스에서 실행).
DEV_TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a shell command in the workspace and get exit code + output.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a file in the workspace (creates parent dirs).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    }},
]

_WORKSPACE_CONVENTIONS = (
    "# Workspace conventions\n"
    "You are working inside a sandbox. Use the bash/write_file/read_file tools to build and "
    "verify real software. Verify by RUNNING — a passing build is not success; the feature must "
    "work as expected. When you start a dev server, run it in the background. When you are done "
    "and everything works, give a short final summary. If you are a reviewer and the work meets "
    "the bar, include the word APPROVED. If you cannot proceed without information only the user "
    "can give, reply with a single line 'AWAITING_INPUT: <question>'."
)


@dataclass
class DevOutcome:
    status: str                 # done | needs-input | failed
    output: str = ""
    awaiting_prompt: str | None = None
    error_summary: str | None = None
    verification: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def _exec_tool(provider: SandboxProvider, sandbox_id: str, call: ToolCall, verification: list) -> dict:
    """도구 1개를 샌드박스에서 실행. bash는 verification에 명령 로그를 남긴다."""
    name, args = call.name, call.args
    if name == "bash":
        cmd = args.get("cmd", "")
        try:
            res = provider.exec(sandbox_id, cmd, timeout=PER_COMMAND_TIMEOUT_SEC)
            summary = (res.stdout + res.stderr)[:_SUMMARY_CAP]
            verification.append({"cmd": cmd, "exit_code": res.exit_code, "summary": summary})
            return {"exit_code": res.exit_code, "stdout": res.stdout[:_SUMMARY_CAP], "stderr": res.stderr[:_SUMMARY_CAP]}
        except SandboxTimeout:
            # per-command 타임아웃 → 깔끔히 종료된 것으로 기록하고 에이전트에 알린다.
            verification.append({"cmd": cmd, "exit_code": -1, "summary": "command timed out (killed)"})
            return {"exit_code": -1, "error": "command timed out and was killed"}
    if name == "write_file":
        provider.write_file(sandbox_id, args["path"], args.get("content", "").encode("utf-8"))
        return {"ok": True}
    if name == "read_file":
        try:
            return {"content": provider.read_file(sandbox_id, args["path"]).decode("utf-8", errors="replace")}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    return {"error": f"unknown tool {name}"}


def run_dev_task(
    task_prompt: str,
    provider: SandboxProvider,
    sandbox_id: str,
    *,
    client,
    role_instructions: str = "",
    task_timeout_sec: int = DEFAULT_TASK_TIMEOUT_SEC,
) -> DevOutcome:
    """dev/design task를 샌드박스에서 실행한다(워크스페이스 핸들은 호출부=item 18이 보장)."""
    system = (role_instructions.strip() + "\n\n" + _WORKSPACE_CONVENTIONS).strip()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task_prompt},
    ]
    verification: list = []
    tokens_in = tokens_out = 0
    start = time.time()

    for _ in range(MAX_STEPS):
        if time.time() - start > task_timeout_sec:
            return DevOutcome(status="failed", error_summary="dev task exceeded time budget",
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out)
        try:
            resp: LLMResponse = client.complete(messages, DEV_TOOLS)
        except Exception as exc:  # noqa: BLE001
            return DevOutcome(status="failed", error_summary=f"agent error: {exc}",
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out)
        tokens_in += resp.tokens_in
        tokens_out += resp.tokens_out

        if resp.tool_calls:
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                    for c in resp.tool_calls
                ],
            })
            for c in resp.tool_calls:
                result = _exec_tool(provider, sandbox_id, c, verification)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)[:_SUMMARY_CAP]})
            continue

        output = resp.content or ""
        question = detect_needs_input(output)
        if question is not None:
            return DevOutcome(status="needs-input", output=output, awaiting_prompt=question,
                              verification=verification, tokens_in=tokens_in, tokens_out=tokens_out)
        return DevOutcome(status="done", output=output, verification=verification,
                          tokens_in=tokens_in, tokens_out=tokens_out)

    return DevOutcome(status="failed", error_summary=f"dev task exceeded {MAX_STEPS} steps",
                      verification=verification, tokens_in=tokens_in, tokens_out=tokens_out)
