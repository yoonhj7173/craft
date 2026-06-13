"""Worker core — task 1건 처리 파이프라인(engine-agnostic, item 10).

process_task(db, task_id):
  1. queued 확인 → try_dispatch(5게이트) → 막히면 queued 유지(나중 재시도).
  2. engine 라우팅:
     - crew  : 프롬프트 조립 → CrewAI 1회 실행(주입/실 LLM) → 결과 분류
               DONE→done(+output file+tokens/cost+memory) / NEEDS_INPUT→needs-input / FAILED→failed
     - agent_sdk: 아직 미구현(item 18) → failed로 스텁(BLOCKED until item 18)
  3. 토큰/비용: model_used × pricing(usage 없으면 길이 휴리스틱 폴백).
  4. usage 이벤트: Redis project:{id} 채널로 publish(SSE는 item 12에서 소비).

mocked Claude: llm 인자로 ScriptedLLM을 주입하면 라이브 키 없이 전체 경로를 검증한다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crews.base import _coerce_output, detect_needs_input
from app.crews.factory import build_agent_crew
from app.models import Agent, AgentMemory, Output, Task
from app.services import events
from app.services import task_service as ts
from app.services.config_store import cost_usd, load_config, model_for_tier
from app.services.prompt import assemble_prompt

log = logging.getLogger("app.worker")


def _tokens(crew, prompt: str, output: str) -> tuple[int, int]:
    """crew.usage_metrics에서 토큰을, 없으면 길이 휴리스틱(≈4 chars/token)으로."""
    um = getattr(crew, "usage_metrics", None)
    pin = int(getattr(um, "prompt_tokens", 0) or 0)
    pout = int(getattr(um, "completion_tokens", 0) or 0)
    if pin == 0:
        pin = max(1, len(prompt) // 4)
    if pout == 0:
        pout = max(1, len(output) // 4)
    return pin, pout


def _append_memory(db: Session, agent_id, output: str) -> None:
    """light-tier 메모리 append(D14) — 격리 실패(메모리 오류가 task를 깨지 않음).

    MVP는 결과 요지를 템플릿으로 append(light-model 요약은 추후 정교화 지점).
    """
    try:
        first = (output.strip().splitlines() or [""])[0][:200]
        mem = db.get(AgentMemory, agent_id)
        line = f"- {datetime.now(timezone.utc).date()}: {first}"
        if mem is None:
            db.add(AgentMemory(agent_id=agent_id, content_md=line))
        else:
            mem.content_md = (mem.content_md + "\n" + line).strip()
        db.flush()
    except Exception:  # noqa: BLE001 — 격리.
        log.warning("memory append failed", extra={"agent_id": str(agent_id)})
        db.rollback()


def _finish_done(db: Session, task: Task, output: str, model: str, tokens_in: int, tokens_out: int, cfg) -> list:
    """done 전이 + 아웃풋 + 메모리 + 그래프 전파를 한 트랜잭션으로 커밋. 새 child id 반환."""
    from app.services import graph_engine

    cost = cost_usd(cfg, model, tokens_in, tokens_out)
    ts.transition(
        db, task, "done",
        result_markdown=output, model_used=model,
        tokens_in=tokens_in, tokens_out=tokens_out, est_cost_usd=cost,
    )
    # 결과를 단일 마크다운 아웃풋 파일로 저장(텍스트팀).
    db.add(Output(
        project_id=task.project_id, agent_id=task.agent_id, task_id=task.id,
        path="output.md", mime="text/markdown", size_bytes=len(output.encode("utf-8")),
        content=output, content_bytes=None,
    ))
    _append_memory(db, task.agent_id, output)
    events.emit_terminal_notification(db, task)
    # 그래프 전파(완료와 같은 트랜잭션, dedup으로 재배달 안전).
    new_ids = [n for n in graph_engine.propagate(db, task) if n is not None]
    db.commit()
    events.emit_status(task)
    events.emit_usage(task.project_id, task.agent_id, tokens_in, tokens_out, cost)
    return new_ids


def process_task(db: Session, task_id: uuid.UUID, *, llm=None, enqueue=None) -> str:
    """task 1건을 처리하고 최종 상태 문자열을 반환한다(테스트/관측용).

    반환: "not_found" | "skipped:<status>" | "not_dispatched" | "done" | "needs-input" | "failed".
    llm: 주입 LLM(테스트 ScriptedLLM). None이면 tier→model로 실 crewai.LLM 생성.
    """
    task = db.get(Task, task_id)
    if task is None:
        return "not_found"
    if task.status != "queued":
        return f"skipped:{task.status}"

    # 게이트 통과 + queued→working(원자적).
    if not ts.try_dispatch(db, task):
        db.rollback()
        return "not_dispatched"
    db.commit()
    events.emit_status(task)  # working

    cfg = load_config(db)
    agent = db.get(Agent, task.agent_id)
    model = model_for_tier(cfg, agent.model_tier)

    # 엔진 라우팅.
    if task.engine == "agent_sdk":
        # item 18에서 WorkspaceService+dev-runner로 대체. 지금은 스텁.
        ts.transition(db, task, "failed", error_summary="dev/design execution engine not available yet (item 18)")
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        return "failed"

    # crew 경로.
    prompt = assemble_prompt(db, task, context_token_budget=cfg.context_token_budget)
    if llm is None:
        from crewai.llm import LLM
        llm = LLM(model=model)

    try:
        crew = build_agent_crew(llm, agent.role_instructions, prompt)
        raw = crew.kickoff(inputs={"prompt": prompt})
        output = _coerce_output(raw)
    except Exception as exc:  # noqa: BLE001 — 워커 경계.
        ts.transition(db, task, "failed", error_summary=f"{type(exc).__name__}: {exc}")
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        return "failed"

    tokens_in, tokens_out = _tokens(crew, prompt, output)
    question = detect_needs_input(output)
    if question is not None:
        cost = cost_usd(cfg, model, tokens_in, tokens_out)
        ts.transition(
            db, task, "needs-input",
            awaiting_prompt=question, result_markdown=output, model_used=model,
            tokens_in=tokens_in, tokens_out=tokens_out, est_cost_usd=cost,
        )
        events.emit_terminal_notification(db, task)
        db.commit()
        events.emit_status(task)
        events.emit_usage(task.project_id, task.agent_id, tokens_in, tokens_out, cost)
        return "needs-input"

    new_ids = _finish_done(db, task, output, model, tokens_in, tokens_out, cfg)
    # 다운스트림 child를 워커 큐에 넣는다(커밋 후). 기본은 Celery, 테스트는 collector 주입.
    if new_ids:
        if enqueue is None:
            from app.celery_app import enqueue_task as enqueue
        for nid in new_ids:
            enqueue(nid)
    return "done"


def reap_stale_tasks(db: Session, older_than_sec: int = 600) -> int:
    """heartbeat(updated_at)이 오래된 working task를 failed로(워커 크래시 복구, §15).

    반환: reap된 task 수. 전파는 절반만 발화되지 않음(failed는 핸드오프 안 함).
    """
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_sec)
    stale = (
        db.query(Task)
        .filter(Task.status == "working", Task.updated_at < cutoff)
        .all()
    )
    n = 0
    for task in stale:
        task.status = "failed"
        task.error_summary = "Worker timed out (reaped)"
        n += 1
    if n:
        db.commit()
    return n
