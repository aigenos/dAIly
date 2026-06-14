"""Multi-channel delivery: Buttondown subscribers + Slack / Discord / Telegram.

Chat channels can't render a full HTML email, so we extract **The Pulse** section
(the standalone 90-second summary), convert it to plain text with inline links,
and post that plus a link to the full archived issue. Each channel is optional —
configure a webhook/token to enable it; leave blank to skip.

Buttondown is the subscriber channel: when BUTTONDOWN_API_KEY is set, each run
also sends the PUBLIC version of the issue (private sections stripped,
fail-closed on leaks) to everyone who subscribed via the landing-page form.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests

from .config import Config

log = logging.getLogger("aigenos.notifiers")


def extract_section(body_fragment: str, section_id: str) -> str:
    """Return the HTML of one <!--SECTION:id--> block (marker to next marker)."""
    m = re.search(
        r"<!--SECTION:" + re.escape(section_id) + r"-->(.*?)(?=<!--SECTION:|\Z)",
        body_fragment,
        flags=re.DOTALL,
    )
    return m.group(1) if m else ""


def html_to_text(html: str, max_bullets: int = 6) -> str:
    """Lightweight HTML→text for chat. Links become 'text (url)'; list items
    become '• ...'. Headings become their own lines. Keeps it short."""
    text = html

    # Links: <a href="u">t</a> -> "t (u)"
    text = re.sub(
        r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f"{_strip_tags(m.group(2))} ({m.group(1)})",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Headings -> blank line + text + colon
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda m: f"\n\n{_strip_tags(m.group(1))}\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", lambda m: f"\n{_strip_tags(m.group(1))}: ", text, flags=re.DOTALL | re.IGNORECASE)
    # List items -> bullets
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"\n• {_strip_tags(m.group(1))}", text, flags=re.DOTALL | re.IGNORECASE)
    # Paragraphs -> newlines
    text = re.sub(r"</?(p|ul|strong|em|blockquote)[^>]*>", "", text, flags=re.IGNORECASE)
    text = _strip_tags(text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Cap the number of bullets so chat posts stay short.
    lines = text.split("\n")
    kept, bullets = [], 0
    for ln in lines:
        if ln.strip().startswith("•"):
            bullets += 1
            if bullets > max_bullets:
                continue
        kept.append(ln)
    return "\n".join(kept).strip()


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def html_to_markdown(html: str) -> str:
    """Digest-fragment HTML → clean Markdown (links, headings, bullets, bold).
    Used for the Buttondown body, where Markdown renders reliably while raw
    styled HTML gets sanitized."""
    text = html
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(
        r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f"[{_strip_tags(m.group(2))}]({m.group(1)})",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", lambda m: f"\n\n## {_md_inline(m.group(1))}\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", lambda m: f"\n\n### {_md_inline(m.group(1))}\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: f"\n- {_md_inline(m.group(1))}", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<p[^>]*>(.*?)</p>", lambda m: f"\n\n{m.group(1).strip()}\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?(ul|ol|blockquote|div|span)[^>]*>", "", text, flags=re.IGNORECASE)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _md_inline(s: str) -> str:
    """Strip leftover tags inside a heading/bullet but keep [md](links)."""
    return re.sub(r"</?(?!a\b)[a-zA-Z][^>]*>", "", s).strip()


def build_teaser(cfg: Config, body_fragment: str, now: datetime) -> str:
    """Plain-text teaser: The Pulse + the Opportunity of the Day (the viral hook)
    + a link to the full issue if hosted."""
    header = f"🤖 dAIly — AI Digest, {now.strftime('%b %d, %Y')}"
    parts = [header]

    pulse = extract_section(body_fragment, "pulse")
    parts += ["", html_to_text(pulse) if pulse else "Today's AI digest is ready."]

    opp = extract_section(body_fragment, "opp_teaser")
    if opp:
        parts += ["", "— — —", html_to_text(opp, max_bullets=8)]

    if cfg.site_url:
        issue = f"{cfg.site_url}/digests/digest_{now.strftime('%Y%m%d')}.html"
        parts += ["", f"Full digest → {issue}"]
    return "\n".join(parts)


def _post(url: str, payload: dict, what: str) -> bool:
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code >= 300:
            log.warning("%s post failed (%s): %s", what, r.status_code, r.text[:200])
            return False
        log.info("posted digest teaser to %s", what)
        return True
    except requests.RequestException as exc:
        log.warning("%s post error: %s", what, exc)
        return False


BUTTONDOWN_API = "https://api.buttondown.com/v1/emails"


def build_buttondown_body(cfg: Config, public_fragment: str, now: datetime) -> str:
    """The newsletter body sent to subscribers.

    - teaser (default): The Pulse + Opportunity of the Day as Markdown plus a
      link to the full issue — renders reliably in Buttondown's pipeline.
    - full: the entire public fragment converted to Markdown.
    """
    issue_url = (
        f"{cfg.site_url}/digests/digest_{now.strftime('%Y%m%d')}.html"
        if cfg.site_url else ""
    )
    if cfg.buttondown_mode == "full":
        body = html_to_markdown(public_fragment)
    else:
        parts = []
        pulse = extract_section(public_fragment, "pulse")
        if pulse:
            parts.append(html_to_markdown(pulse))
        opp = extract_section(public_fragment, "opp_teaser")
        if opp:
            parts.append(html_to_markdown(opp))
        body = "\n\n---\n\n".join(parts) or html_to_markdown(public_fragment)
    if issue_url:
        body += f"\n\n---\n\n**[Read the full issue →]({issue_url})**"
    return body


def send_buttondown(
    cfg: Config,
    body_fragment: str,
    now: datetime,
    private_ids: list[str] | None = None,
    sentinels: list[str] | None = None,
) -> bool:
    """Send today's issue to all Buttondown subscribers. No-op without
    BUTTONDOWN_API_KEY. Subscribers get the PUBLIC version: private sections
    are stripped here, and we fail closed (skip the send) if any private
    sentinel survives — same guarantee as the public archive."""
    if not cfg.buttondown_api_key:
        return False
    from .archive import strip_private_sections
    from .emailer import subject_line

    public = strip_private_sections(
        body_fragment, list(private_ids or []), list(sentinels or [])
    )
    leaks = [kw for kw in (sentinels or []) if kw.lower() in public.lower()]
    if leaks:
        log.error(
            "Buttondown send SKIPPED — private content may have leaked "
            "(sentinel still present: %s)", leaks,
        )
        return False

    payload = {
        "subject": subject_line(now),
        "body": build_buttondown_body(cfg, public, now),
        # Create-and-send in one call (default would leave a draft).
        "status": "about_to_send",
    }
    try:
        r = requests.post(
            BUTTONDOWN_API,
            json=payload,
            headers={"Authorization": f"Token {cfg.buttondown_api_key}"},
            timeout=30,
        )
        if r.status_code >= 300:
            log.warning(
                "Buttondown send failed (%s): %s", r.status_code, r.text[:300]
            )
            return False
        log.info("issue sent to Buttondown subscribers")
        return True
    except requests.RequestException as exc:
        log.warning("Buttondown send error: %s", exc)
        return False


def notify_all(
    cfg: Config,
    body_fragment: str,
    now: datetime,
    private_ids: list[str] | None = None,
    sentinels: list[str] | None = None,
) -> None:
    """Post the teaser to every configured channel. No-op for unconfigured ones."""
    send_buttondown(cfg, body_fragment, now, private_ids, sentinels)
    teaser = build_teaser(cfg, body_fragment, now)

    if cfg.slack_webhook_url:
        _post(cfg.slack_webhook_url, {"text": teaser}, "Slack")
    if cfg.discord_webhook_url:
        # Discord caps content at 2000 chars.
        _post(cfg.discord_webhook_url, {"content": teaser[:1990]}, "Discord")
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        api = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
        _post(
            api,
            {
                "chat_id": cfg.telegram_chat_id,
                "text": teaser[:4000],
                "disable_web_page_preview": True,
            },
            "Telegram",
        )
