"""Event publishing — project:{id} Redis 채널로 SSE 이벤트 + notification 행 생성(item 12).

세 종류 이벤트를 같은 채널로 publish하고, SSE 라우터(GET /sse)가 그대로 중계한다:
- task_status : task 상태 전이마다.
- notification: 종결/대기(done/blocked/needs-input/failed)에서 notification 행 + 이벤트.
- usage      : 토큰/비용 델타(카운터/팝오버).

publish 실패는 무시(관측 채널이지 권위 상태가 아니다 — 권위는 DB).
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.db import redis_client
from app.models import Agent, Notification, Task

log = logging.getLogger("app.events")


def _channel(project_id) -> str:
    return f"project:{project_id}"


def _publish(project_id, payload: dict) -> None:
    try:
        redis_client.publish(_channel(project_id), json.dumps(payload))
    except Exception:  # noqa: BLE001
        log.warning("event publish failed", extra={"project_id": str(project_id)})


def emit_status(task: Task) -> None:
    """task_status 이벤트."""
    _publish(task.project_id, {
        "type": "task_status",
        "task_id": str(task.id),
        "agent_id": str(task.agent_id),
        "status": task.status,
    })


def emit_usage(project_id, agent_id, tokens_in: int, tokens_out: int, cost: float) -> None:
    _publish(project_id, {
        "type": "usage",
        "agent_id": str(agent_id),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
    })


# 종결/대기 상태 → 사용자에게 알릴 notification 매핑.
_NOTIFY_STATUSES = {"done", "blocked", "needs-input", "failed"}


def emit_terminal_notification(db: Session, task: Task) -> None:
    """task가 종결/대기 상태면 notification 행 생성 + 이벤트 publish(D5/D23).

    호출부가 커밋한다(전이와 같은 트랜잭션). 메시지는 에이전트명 + 상태로 구성.
    """
    if task.status not in _NOTIFY_STATUSES:
        return
    agent = db.get(Agent, task.agent_id)
    name = agent.name if agent else "Agent"
    msgs = {
        "done": f"{name} finished",
        "failed": f"{name} failed" + (" (stopped)" if task.stopped else ""),
        "needs-input": f"{name} needs your input",
        "blocked": f"{name} is blocked",
    }
    notif = Notification(
        user_id=task.user_id, project_id=task.project_id, agent_id=task.agent_id,
        task_id=task.id, type=task.status, message=msgs.get(task.status, name),
    )
    db.add(notif)
    db.flush()
    _publish(task.project_id, {
        "type": "notification",
        "notification_id": str(notif.id),
        "agent_id": str(task.agent_id),
        "notif_type": task.status,
        "message": notif.message,
    })
