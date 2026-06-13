"""Prompt assembly — 두 엔진 공유(tech-design §7).

순서: role_instructions → 프로젝트 컨텍스트(추출 텍스트, 토큰버짓 내) → 에이전트 메모리 →
input_payload(+provenance) → 직전 부분출력 + continuations → instructions → 프로토콜(센티넬).

컨텍스트는 풀텍스트 주입(no RAG, D14)이되 context_token_budget를 넘으면 oldest-first로
자른다(대략 4 chars≈1 token 휴리스틱). dev-runner(item 16)는 여기에 워크스페이스 컨벤션을 덧붙인다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Agent, AgentMemory, ContextFile, Task

_PROTOCOL = (
    "# Protocol\n"
    "If you have everything you need, produce the final answer.\n"
    "If and only if you cannot proceed without information only the user can give, "
    "respond with a single line exactly in the form:\n"
    "AWAITING_INPUT: <your one specific question>\n"
    "Do not guess or hallucinate missing facts."
)


def _context_block(db: Session, project_id, token_budget: int) -> str:
    """프로젝트 컨텍스트 파일들의 추출 텍스트를 버짓 내로 합친다(oldest-first 누적, 초과 시 절단)."""
    rows = (
        db.query(ContextFile)
        .filter(ContextFile.project_id == project_id)
        .order_by(ContextFile.created_at)
        .all()
    )
    char_budget = token_budget * 4  # 대략 4 chars/token.
    used = 0
    parts: list[str] = []
    for r in rows:
        text = (r.extracted_text or "").strip()
        if not text:
            continue
        remaining = char_budget - used
        if remaining <= 0:
            break
        chunk = text[:remaining]
        parts.append(f"## {r.filename}\n{chunk}")
        used += len(chunk)
    return "\n\n".join(parts)


def assemble_prompt(db: Session, task: Task, *, context_token_budget: int = 100_000) -> str:
    """task에 대한 단일 프롬프트를 조립한다(재실행 기반 연속 — §14)."""
    agent = db.get(Agent, task.agent_id)
    parts: list[str] = []

    # 1. 역할.
    if agent is not None:
        parts.append("# Your role\n" + agent.role_instructions.strip())

    # 2. 프로젝트 컨텍스트.
    ctx = _context_block(db, task.project_id, context_token_budget)
    if ctx:
        parts.append("# Project context (uploaded by the user)\n" + ctx)

    # 3. 에이전트 메모리.
    mem = db.get(AgentMemory, task.agent_id)
    if mem and mem.content_md.strip():
        parts.append("# Your memory from previous tasks\n" + mem.content_md.strip())

    # 4. 입력(엣지 전달 페이로드 + provenance).
    if task.input_payload:
        prov = " (delivered from an upstream agent)" if task.edge_id else ""
        parts.append(f"# Input{prov}\n{task.input_payload.strip()}")

    # 5. 직전 부분출력 + continuations(연속).
    if task.result_markdown:
        parts.append("# Work produced so far (your previous partial output)\n" + task.result_markdown.strip())
    for i, cont in enumerate(task.continuations or [], start=1):
        text = cont.get("text", "") if isinstance(cont, dict) else str(cont)
        parts.append(f"# User follow-up #{i}\n{text.strip()}")

    # 6. 지시.
    parts.append("# Instructions\n" + task.instructions.strip())

    # 7. 프로토콜(센티넬).
    parts.append(_PROTOCOL)

    return "\n\n".join(parts)
