"""Subscriber delivery via Resend Broadcasts — self-configuring.

The owner's copy and the subscribers' copy are rendered by the SAME function
(`emailer.render_html`) and sent through the SAME provider (Resend), so both
inboxes get a byte-for-byte identical newsletter. The only differences are
intentional: subscribers get the PUBLIC issue (private sections stripped,
fail-closed on any leak) and a managed one-click unsubscribe
(``{{{RESEND_UNSUBSCRIBE_URL}}}``, expanded by Resend per-recipient).

ZERO-CONFIG BY DESIGN. The only thing the owner must do is verify a sending
domain in Resend (a DNS fact no platform can automate away). Everything else
resolves itself at run time, with env vars as optional overrides:

  * audience    — RESEND_AUDIENCE_ID, else the account's first audience, else
                  one named "dAIly subscribers" is created.
  * sender      — EMAIL_FROM, unless it's still the onboarding@resend.dev
                  default, in which case digest@<first-verified-domain> is used.
  * subscribers — any Buttondown list (BUTTONDOWN_API_KEY) is auto-synced into
                  the audience each run, so signups keep flowing with no manual
                  CSV export/import.

Fail-open throughout: the owner email is the guaranteed deliverable, so any
Broadcast/API error is logged and swallowed — it never aborts the run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime

import requests

from .config import Config

log = logging.getLogger("aigenos.broadcast")

RESEND_API = "https://api.resend.com"
BROADCASTS_API = f"{RESEND_API}/broadcasts"
BUTTONDOWN_SUBSCRIBERS_API = "https://api.buttondown.com/v1/subscribers"

# Merge tag Resend expands per-recipient into its managed unsubscribe link.
UNSUBSCRIBE_TAG = "{{{RESEND_UNSUBSCRIBE_URL}}}"


def _headers(cfg: Config) -> dict:
    return {
        "Authorization": f"Bearer {cfg.resend_api_key}",
        "Content-Type": "application/json",
    }


def _get(cfg: Config, path: str) -> dict | None:
    """GET a Resend endpoint; None on any failure (never raises)."""
    try:
        r = requests.get(f"{RESEND_API}{path}", headers=_headers(cfg), timeout=20)
        if r.status_code >= 300:
            log.warning("Resend GET %s failed (%s): %s", path, r.status_code, r.text[:200])
            return None
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Resend GET %s error: %s", path, exc)
        return None


def _resolve_audience(cfg: Config) -> str:
    """The audience to broadcast to: RESEND_AUDIENCE_ID override, else the
    account's first audience, else auto-create 'dAIly subscribers'."""
    if cfg.resend_audience_id:
        return cfg.resend_audience_id
    listing = _get(cfg, "/audiences")
    data = (listing or {}).get("data") or []
    if data:
        aud = data[0]
        log.info("auto-using Resend audience %r (%s)", aud.get("name"), aud.get("id"))
        return aud.get("id") or ""
    try:
        r = requests.post(
            f"{RESEND_API}/audiences",
            json={"name": "dAIly subscribers"},
            headers=_headers(cfg),
            timeout=20,
        )
        if r.status_code < 300:
            aid = (r.json() or {}).get("id", "")
            log.info("created Resend audience 'dAIly subscribers' (%s)", aid)
            return aid
        log.warning("could not create audience (%s): %s", r.status_code, r.text[:200])
    except (requests.RequestException, ValueError) as exc:
        log.warning("audience create error: %s", exc)
    return ""


def resolve_sender(cfg: Config) -> str:
    """The branded From address. EMAIL_FROM wins unless it's still on
    resend.dev (the shared onboarding sender, which cannot broadcast) — then
    derive daily@<first-verified-domain>. '' means no usable sender yet.
    Used for the subscriber broadcast AND to upgrade the owner copy's sender
    once a domain is verified (see main.run)."""
    sender = cfg.email_from
    if sender and "resend.dev" not in sender.lower():
        return sender
    domains = _get(cfg, "/domains")
    verified = [
        d.get("name") for d in (domains or {}).get("data") or []
        if d.get("status") == "verified" and d.get("name")
    ]
    if verified:
        derived = f"dAIly <daily@{verified[0]}>"
        log.info("auto-using sender %s (EMAIL_FROM not set to a custom domain)", derived)
        return derived
    log.warning(
        "no verified sending domain in Resend — subscribers skipped. Verify a "
        "domain at resend.com → Domains (the one manual step), then this "
        "auto-configures itself."
    )
    return ""


_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Buttondown subscriber types that should receive the newsletter.
_ACTIVE_TYPES = {"regular", "premium", "gifted", ""}


def sync_buttondown_contacts(cfg: Config, audience_id: str) -> int:
    """One-way sync: Buttondown subscribers → the Resend audience. Lets the free
    Buttondown signup form keep capturing subscribers while Resend does the
    sending. Idempotent (only missing contacts are added); fail-open; returns
    the number of contacts added."""
    if not (cfg.buttondown_api_key and audience_id):
        return 0

    existing: set[str] = set()
    contacts = _get(cfg, f"/audiences/{audience_id}/contacts")
    for c in (contacts or {}).get("data") or []:
        if c.get("email"):
            existing.add(c["email"].lower())

    added = 0
    url: str | None = BUTTONDOWN_SUBSCRIBERS_API
    pages = 0
    try:
        while url and pages < 10:
            pages += 1
            r = requests.get(
                url,
                headers={"Authorization": f"Token {cfg.buttondown_api_key}"},
                timeout=30,
            )
            if r.status_code >= 300:
                log.warning("Buttondown subscriber list failed (%s): %s",
                            r.status_code, r.text[:200])
                break
            payload = r.json()
            for sub in payload.get("results", []):
                email = (sub.get("email_address") or sub.get("email") or "").strip().lower()
                stype = (sub.get("subscriber_type") or sub.get("type") or "").lower()
                if not _EMAIL_RX.match(email) or email in existing:
                    continue
                if stype not in _ACTIVE_TYPES:
                    continue  # unactivated / unsubscribed / removed stay behind
                cr = requests.post(
                    f"{RESEND_API}/audiences/{audience_id}/contacts",
                    json={"email": email, "unsubscribed": False},
                    headers=_headers(cfg),
                    timeout=20,
                )
                if cr.status_code < 300 or cr.status_code == 409:
                    existing.add(email)
                    added += 1
            url = payload.get("next")
    except (requests.RequestException, ValueError) as exc:
        log.warning("Buttondown→Resend sync error: %s", exc)
    if added:
        log.info("synced %d Buttondown subscriber(s) into the Resend audience", added)
    return added


def send_subscribers(
    cfg: Config,
    body_fragment: str,
    now: datetime,
    private_ids: list[str] | None = None,
    sentinels: list[str] | None = None,
) -> bool:
    """Send today's issue to every Resend audience contact. Needs only
    RESEND_API_KEY + a verified domain — audience, sender, and Buttondown
    migration all resolve automatically (see module docstring). Subscribers get
    the PUBLIC version: private sections are stripped here and we fail closed
    (skip the send) if any private sentinel survives."""
    if not cfg.resend_api_key:
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

    sender = resolve_sender(cfg)
    if not sender:
        return False  # no verified domain yet — the one manual prerequisite
    audience_id = _resolve_audience(cfg)
    if not audience_id:
        return False

    # Pull any Buttondown signups into the audience before sending.
    sync_buttondown_contacts(cfg, audience_id)

    # Subscribers always get a working unsubscribe: fall back to Resend's
    # managed merge tag when UNSUBSCRIBE_URL isn't configured.
    sub_cfg = cfg if cfg.unsubscribe_url else replace(cfg, unsubscribe_url=UNSUBSCRIBE_TAG)

    html = render_html(
        public,
        now,
        footer=footer_links(sub_cfg, now, include_unsubscribe=True),
        logo_url=getattr(cfg, "logo_url", ""),
        logo_url_dark=getattr(cfg, "logo_url_dark", ""),
        hero_image_url=getattr(cfg, "hero_image_url", ""),
        feedback=feedback_block(cfg, now),
    )
    return _create_and_send(cfg, audience_id, sender, subject_line(now), html)


def _create_and_send(
    cfg: Config, audience_id: str, sender: str, subject: str, html: str
) -> bool:
    """Create a broadcast for the audience, then send it. Returns True only if
    both calls succeed. Never raises."""
    payload = {
        "audience_id": audience_id,
        "from": sender,
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
