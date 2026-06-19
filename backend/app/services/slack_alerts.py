"""운영 알림 → Slack Incoming Webhook. `SLACK_ALERT_WEBHOOK_URL` 미설정 시 no-op.

채널 라우팅은 Webhook URL이 결정한다(URL이 특정 채널에 묶임 → #proj-pondas).
알림 자체가 실패해도 본 요청/작업을 깨뜨리지 않도록 모든 에러를 삼킨다(best-effort).

누가 쓰나: main.py 전역 예외핸들러(처리 안 된 500), worker_core 시스템 실패, (추후) Stripe 웹훅.
참고 구현: ai-partner/lib/alerts/slack.ts (Swoony). 여기선 동기 httpx로 — 워커(sync)·핸들러 양쪽에서 호출.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("app.slack")


def send_slack_alert(title: str, detail: str | None = None) -> None:
    """prod 운영 알림을 Slack으로 보낸다. 키 없으면 조용히 no-op, 실패는 삼킨다."""
    url = settings.slack_alert_webhook_url
    if not url:
        return  # opt-in: 미설정이면 아무것도 안 함
    text = f"🚨 *pondas* — {title}"
    if detail:
        text += f"\n```{detail[:1500]}```"
    try:
        httpx.post(url, json={"text": text}, timeout=3.0)
    except Exception:  # noqa: BLE001 — 알림 실패는 본 흐름에 영향 X
        log.warning("slack alert failed", extra={"title": title})
