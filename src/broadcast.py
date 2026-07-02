"""Subscriber delivery via Resend Broadcasts.

The owner's copy and the subscribers' copy are rendered by the SAME function
(`emailer.render_html`) and sent through the SAME provider (Resend), so both
inboxes get a byte-for-byte identical newsletter — same hero, same cards, same
dark-mode styling. The only differences are intentional:

  * subscribers get the PUBLIC issue (private sections stripped, fail-closed on
    any leak — same guarantee as the archive), and
  * subscribers get a managed one-click unsubscribe footer
    (``{{{RESEND_UNSUBSCRIBE_URL}}}``, expanded by Resend per-recipient).

Delivery is a two-step Resend flow: create a broadcast bound to the audience,
then send it. No-op (returns False) when RESEND_AUDIENCE_ID is unset. Fail-open:
the owner email is the guaranteed deliverable, so any Broadcast error is logged
and swallowed — it never aborts the run.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from .config import Config

log = logging.getLogger("aigenos.broadcast")

BROADCASTS_API = "https://api.resend.com/broadcasts"


def _headers(cfg: Config) -> dict:
    return {
        "Authorization": f"Bearer {cfg.resend_api_key}",
        "Content-Type": "application/json",
    }


def send_subscribers(
    cfg: Config,
    body_fragment: str,
    now: datetime,
    private_ids: list[str] | None = None,
    sentinels: list[str] | None = None,
) -> bool:
    """Send today's issue to every Resend audience contact. No-op without an API
    key + RESEND_AUDIENCE_ID. Subscribers get the PUBLIC version: private sections
    are stripped here and we fail closed (skip the send) if any private sentinel
    survives."""
    if not (cfg.resend_api_key and cfg.resend_audience_id):
        return False

    from .archive import strip_private_sections
    from .emailer import (
        feedback_block,
        footer_links,
        render_html,
        subject_line,
    )

    public = strip_private_sections(
        body_fragment, list(private_ids or []), list(sentinels or [])
    )
    leaks = [kw for kw in (sentinels or []) if kw.lower() in public.lower()]
    if leaks:
        log.error(
            "Resend broadcast SKIPPED — private content may have leaked "
            "(sentinel still present: %s)", leaks,
        )
        return False

    html = render_html(
        public,
        now,
        footer=footer_links(cfg, now, include_unsubscribe=True),
        logo_url=getattr(cfg, "logo_url", ""),
        logo_url_dark=getattr(cfg, "logo_url_dark", ""),
        hero_image_url=getattr(cfg, "hero_image_url", ""),
        feedback=feedback_block(cfg, now),
    )
    return _create_and_send(cfg, subject_line(now), html)


def _create_and_send(cfg: Config, subject: str, html: str) -> bool:
    """Create a broadcast for the audience, then send it. Returns True only if
    both calls succeed. Never raises."""
    payload = {
        "audience_id": cfg.resend_audience_id,
        "from": cfg.email_from,
        "subject": subject,
        "name": subject,
        "html": html,
    }
    if getattr(cfg, "reply_to", ""):
        payload["reply_to"] = cfg.reply_to
    try:
        r = requests.post(BROADCASTS_API, json=payload, headers=_headers(cfg), timeout=30)
        if r.status_code >= 300:
            log.warning("Resend broadcast create failed (%s): %s", r.status_code, r.text[:300])
            return False
        broadcast_id = (r.json() or {}).get("id")
        if not broadcast_id:
            log.warning("Resend broadcast create returned no id: %s", r.text[:200])
            return False

        s = requests.post(
            f"{BROADCASTS_API}/{broadcast_id}/send",
            json={},
            headers=_headers(cfg),
            timeout=30,
        )
        if s.status_code >= 300:
            log.warning("Resend broadcast send failed (%s): %s", s.status_code, s.text[:300])
            return False
        log.info("issue sent to Resend subscribers (broadcast %s)", broadcast_id)
        return True
    except requests.RequestException as exc:
        log.warning("Resend broadcast error: %s", exc)
        return False
