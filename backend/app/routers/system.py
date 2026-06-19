"""System endpoints — liveness (/health) and readiness (/ready).

tech-design §3 Observability, §6 System:
- /health: 프로세스가 살아있는지만 본다. 의존성 점검 없음 → 항상 빠르게 200.
- /ready: DB + Redis 실제 도달성을 점검한다. 하나라도 실패하면 503.
  (로드밸런서/오케스트레이터가 트래픽을 보낼지 결정하는 데 쓴다)
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import check_db, check_redis
from app.logging_config import get_logger

router = APIRouter(tags=["system"])
log = get_logger("app.system")


@router.get("/health")
def health() -> dict:
    """Liveness probe — 의존성 없이 200."""
    return {"status": "ok"}


@router.get("/ops-alert-selftest")
def ops_alert_selftest() -> dict:
    """[임시] Slack 알림 prod 실증 — webhook으로 1발 쏘고 실제 status를 돌려준다.

    prod에서 `{envSet:true, webhookStatus:200}` 확인용. **검증 끝나면 제거.**
    """
    url = settings.slack_alert_webhook_url
    if not url:
        return {"envSet": False, "webhookStatus": None, "body": "SLACK_ALERT_WEBHOOK_URL unset"}
    try:
        r = httpx.post(url, json={"text": "✅ pondas ops-alert self-test"}, timeout=5.0)
        return {"envSet": True, "webhookStatus": r.status_code, "body": r.text[:100]}
    except Exception as exc:  # noqa: BLE001
        return {"envSet": True, "webhookStatus": None, "body": f"{type(exc).__name__}: {exc}"}


@router.get("/ready")
def ready():
    """Readiness probe — DB와 Redis에 실제 연결해 본다.

    각 점검을 개별적으로 try하여 어느 의존성이 죽었는지 응답에 드러낸다.
    """
    checks = {"db": False, "redis": False}

    try:
        checks["db"] = check_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("readiness db check failed", extra={"error": str(exc)})

    try:
        checks["redis"] = check_redis()
    except Exception as exc:  # noqa: BLE001
        log.warning("readiness redis check failed", extra={"error": str(exc)})

    all_ready = all(checks.values())
    status = "ready" if all_ready else "not-ready"
    body = {"status": status, "checks": checks}
    # 준비 안 됐으면 503으로 명확히 표시(오케스트레이터가 트래픽 보류).
    return JSONResponse(status_code=200 if all_ready else 503, content=body)
