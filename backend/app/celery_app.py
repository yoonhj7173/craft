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
    """queued task 1건을 처리한다. 결과 상태 문자열 반환."""
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
    """task를 워커 큐에 넣는다(디스패처/그래프엔진/오케스트레이터가 호출)."""
    run_task.delay(str(task_id))
