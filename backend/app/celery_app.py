"""Celery app — 비동기 task 실행 + reaper beat (item 10).

broker/backend = Redis(settings.redis_url). 실행 자체는 worker_core.process_task가 하고
여기선 Celery 태스크로 감싸 세션 수명/재시도 경계를 둔다. 디스패치는 enqueue_task로.

run: celery -A app.celery_app worker --beat (개발). 테스트는 process_task를 직접 호출하거나
task_always_eager로 동기 실행한다.
"""

from __future__ import annotations

import uuid

from celery import Celery

from app.config import settings
from app.db import SessionLocal
from app.services.worker_core import process_task, reap_stale_tasks

celery_app = Celery(
    "cursorpm",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "reap-stale-tasks": {
            "task": "app.celery_app.reap_stale",
            "schedule": 60.0,  # 매 60초 stale working task 회수.
        },
    },
)


@celery_app.task(name="app.celery_app.run_task")
def run_task(task_id: str) -> str:
    """워커가 집어 실행하는 작업 1건 — 큐에서 꺼낸 작업을 실제 처리 함수로 넘긴다.

    PM 한 줄: API는 작업을 '큐에 던지기만' 하고 즉시 응답한다(사용자를 안 기다리게). 그러면 별도
        백그라운드 프로세스(Celery 워커)가 이 함수를 실행해 진짜 일을 한다. = 비동기 처리(@Async 비슷).
    무슨 일을 하나: DB 세션을 열고 process_task로 작업을 처리한 뒤 닫는다.
    연결: 실제 처리 로직 → process_task (backend/app/services/worker_core.py). 큐에 넣기 → 아래 enqueue_task.
    """
    db = SessionLocal()
    try:
        return process_task(db, uuid.UUID(task_id))
    finally:
        db.close()


@celery_app.task(name="app.celery_app.reap_stale")
def reap_stale() -> int:
    db = SessionLocal()
    try:
        return reap_stale_tasks(db)
    finally:
        db.close()


def enqueue_task(task_id: uuid.UUID) -> None:
    """작업 큐에 넣기 — "이 작업 처리해줘"라고 백그라운드 워커 큐에 작업 번호를 올린다.

    무슨 일을 하나: 작업을 즉시 실행하지 않고 Redis 큐에 등록만 한다. 워커가 알아서 꺼내 run_task로 처리한다.
    누가 부르나: 작업이 만들어지는 모든 곳 — 지휘자 dispatch_task(orchestrator.py), 자동 전파(graph_engine.py),
        입력 재개(tasks.py). 연결: 큐에서 꺼내 실행 → 위 run_task.
    """
    run_task.delay(str(task_id))
