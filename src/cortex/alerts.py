"""Out-of-band failure alerting for unattended (cron-triggered) syncs.

When a sync runs from a button press, Rob sees the result in the UI. When it
runs from a Railway cron job at 6am, nobody is watching — a silent failure
violates the project's "fail visibly" rule. This module posts a short message
to a webhook (Discord- or Slack-compatible) so unattended failures surface.

No-op when ``CORTEX_ALERT_WEBHOOK`` is unset, so local/dev runs stay quiet.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _webhook_url() -> str | None:
    return os.environ.get("CORTEX_ALERT_WEBHOOK") or None


def _payload(text: str) -> dict[str, str]:
    """Discord uses ``content``; Slack/Mattermost use ``text``. Send both so a
    single env var works regardless of which provider the URL points at."""
    return {"content": text, "text": text}


def send_alert(text: str) -> bool:
    """Post ``text`` to the configured webhook. Returns True if delivered.

    Never raises — alerting must not be able to crash a sync. A failed alert is
    logged at WARNING (the sync result itself is already persisted to the DB).
    """
    url = _webhook_url()
    if not url:
        return False
    try:
        resp = httpx.post(url, json=_payload(text), timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("alert: webhook delivery failed — %s", exc)
        return False


def alert_sync_failure(failures: dict[str, str]) -> bool:
    """Alert that one or more sync steps failed. ``failures`` is {source: detail}."""
    if not failures:
        return False
    lines = ["⚠️ CORTEX sync failures:"]
    lines += [f"• {src}: {detail}" for src, detail in failures.items()]
    return send_alert("\n".join(lines))
