"""Email rendering + delivery via the Resend HTTP API.

Modern, theme-aware HTML built on a few principles:

- ``<meta name="color-scheme">`` + ``<meta name="supported-color-schemes">``
  signal we render in both light and dark.
- A ``<style>`` block carries a ``@media (prefers-color-scheme: dark)`` rule
  using LITERAL color values (no ``var()`` — Gmail and Outlook strip custom
  properties even when they keep the media query). Clients that support
  ``prefers-color-scheme`` (Apple Mail, iOS Mail, Gmail web, Outlook.com,
  Yahoo) get full theme switching.
- Every tag also carries inline light-theme styles as a fallback for clients
  that strip ``<style>`` (notably Outlook desktop). Those readers get a clean
  light-mode render — Outlook handles its own dark-mode inversion.

Aesthetic goal: floating cards, soft gradients, refined typography, generous
whitespace — "Antigravity"-style UX rendered inside an email.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

from .config import Config

log = logging.getLogger("aigenos.emailer")

RESEND_ENDPOINT = "https://api.resend.com/emails"

# ── Theme tokens ──────────────────────────────────────────────────────────────
# Light defaults are also embedded inline on each element for Outlook desktop.
# Dark overrides come from the @media (prefers-color-scheme: dark) block below.

_THEME_STYLES = """
:root {
  color-scheme: light dark;
  supported-color-schemes: light dark;
}
@media (prefers-color-scheme: dark) {
  /* Literal colors only — Gmail/Outlook strip CSS custom properties but keep
     the media query, which used to leave dark-mode readers unstyled. */
  body, .aigenos-bg { background: #0a0a14 !important; }
  .aigenos-card { background: #14141f !important; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.35) !important; }
  .aigenos-text { color: #ececf5 !important; }
  .aigenos-muted { color: #8e8ea8 !important; }
  h2.aigenos-h2 { color: #8b8cff !important; border-color: #2a2a3d !important; }
  h3.aigenos-h3 { color: #ececf5 !important; }
  p.aigenos-p, li.aigenos-li { color: #c8c8d8 !important; }
  a.aigenos-a { color: #8b8cff !important; }
  strong.aigenos-strong { color: #ececf5 !important; }
  blockquote.aigenos-bq {
    background: #1a1a26 !important;
    color: #c8c8d8 !important;
    border-color: #8b8cff !important;
  }
  .aigenos-chip {
    background: rgba(139, 140, 255, 0.14) !important;
    color: #8b8cff !important;
  }
  .aigenos-footer { color: #8e8ea8 !important; }
  .aigenos-footer a { color: #8b8cff !important; }
  .aigenos-hero-sub { color: rgba(255,255,255,0.85) !important; }
  .aigenos-src-row { background: #1a1a26 !important; border-color: #2a2a3d !important; }
  a.aigenos-src-title { color: #ececf5 !important; }
  .aigenos-src-meta { color: #8e8ea8 !important; }
}
@media (max-width: 600px) {
  .aigenos-shell { padding: 16px 10px !important; }
  .aigenos-card { padding: 18px !important; }
  .aigenos-hero { padding: 22px 22px 18px !important; }
}
"""

# ── Wrapper template ──────────────────────────────────────────────────────────
_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{title}</title>
<style>{theme}</style>
</head>
<body class="aigenos-bg" style="margin:0;padding:0;background:#f3f4f8;color-scheme:light dark;">
<div class="aigenos-shell" style="max-width:720px;margin:0 auto;padding:28px 18px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI Variable','Segoe UI',Roboto,'SF Pro Display','Helvetica Neue',Arial,sans-serif;font-feature-settings:'cv11','ss03';-webkit-font-smoothing:antialiased;">

  <!-- Hero / masthead -->
  <div class="aigenos-hero" style="background:linear-gradient(135deg,#4f46e5 0%,#7c3aed 55%,#c026d3 100%);border-radius:20px;padding:26px 28px;color:#ffffff;box-shadow:0 8px 32px rgba(79,70,229,0.25);">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="width:54px;vertical-align:middle;">
        <div style="width:52px;height:52px;border-radius:15px;background:rgba(255,255,255,0.16);text-align:center;font-size:27px;line-height:52px;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.18);">🤖</div>
      </td>
      <td style="vertical-align:middle;padding-left:14px;">
        <div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.8;font-weight:600;">by aigenos · daily ai intelligence</div>
        <div style="font-size:30px;font-weight:800;letter-spacing:-0.02em;line-height:1.05;margin-top:3px;">d<span style="color:#fcd34d;">AI</span>ly</div>
      </td>
      <td style="vertical-align:middle;text-align:right;white-space:nowrap;">
        <span style="display:inline-block;background:rgba(255,255,255,0.18);padding:6px 13px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.3px;">{date_short}</span>
      </td>
    </tr></table>
    <div class="aigenos-hero-sub" style="font-size:13.5px;opacity:.92;font-weight:500;line-height:1.5;margin-top:15px;padding-top:13px;border-top:1px solid rgba(255,255,255,0.18);">
      📅 {date} &nbsp;·&nbsp; Cutting-edge AI in ~90 seconds — the news, the must-read research, and what to build next.
    </div>
  </div>

  <!-- Body card -->
  <div class="aigenos-card" style="background:#ffffff;border-radius:20px;padding:8px 30px 26px;margin-top:18px;box-shadow:0 1px 2px rgba(20,20,42,0.04),0 8px 24px rgba(20,20,42,0.06);">
    {body}
    {cta}
  </div>

  <!-- Footer -->
  <div class="aigenos-footer" style="text-align:center;color:#6b6b85;font-size:12px;padding:22px 8px 8px;line-height:1.6;">
    <strong style="color:#6366f1;font-weight:700;">dAIly</strong> by aigenos{footer_links}{engine}
  </div>

</div>
</body>
</html>"""

# ── Inline styling for the model-produced tags ────────────────────────────────
# Inline styles are the light-mode baseline. Class names are the hook for the
# dark-mode @media block above to retarget colors via CSS.
_TAG_STYLES = {
    "<h2>": (
        '<h2 class="aigenos-h2" style="font-size:21px;margin:32px 0 10px;padding-bottom:10px;'
        'border-bottom:1px solid #e8e6f5;color:#6366f1;font-weight:700;letter-spacing:-0.01em;'
        'line-height:1.3;">'
    ),
    "<h3>": (
        '<h3 class="aigenos-h3" style="font-size:16px;margin:22px 0 6px;color:#14142a;'
        'font-weight:650;letter-spacing:-0.005em;line-height:1.35;">'
    ),
    "<p>": (
        '<p class="aigenos-p" style="margin:10px 0;font-size:15px;color:#3a3a55;'
        'line-height:1.65;">'
    ),
    "<ul>": (
        '<ul class="aigenos-ul" style="margin:10px 0 12px 0;padding-left:22px;">'
    ),
    "<li>": (
        '<li class="aigenos-li" style="margin:7px 0;font-size:15px;color:#3a3a55;'
        'line-height:1.6;">'
    ),
    "<a ": (
        '<a class="aigenos-a" style="color:#6366f1;text-decoration:none;font-weight:600;'
        'border-bottom:1px solid rgba(99,102,241,0.25);" '
    ),
    "<blockquote>": (
        '<blockquote class="aigenos-bq" style="margin:14px 0;padding:12px 18px;'
        'border-left:3px solid #6366f1;background:#faf9ff;color:#3a3a55;border-radius:0 10px 10px 0;'
        'font-size:15px;line-height:1.6;">'
    ),
    "<strong>": (
        '<strong class="aigenos-strong" style="color:#14142a;font-weight:650;">'
    ),
    "<em>": (
        '<em class="aigenos-em" style="font-style:italic;color:inherit;">'
    ),
}


def _inline_styles(body: str) -> str:
    out = body
    for tag, styled in _TAG_STYLES.items():
        if tag == "<a ":
            # Only style bare anchors (model output). Skip anchors that already
            # carry a class (e.g. the pre-styled Top Stories rows) so we don't
            # produce duplicate class/style attributes.
            out = re.sub(r"<a (?![^>]*\bclass=)", styled, out)
        else:
            out = out.replace(tag, styled)
    return out


# Match the "(90 sec read)" / "(5 min read)" suffix the model puts on each <h2>
# and turn it into a styled chip so it pops without looking like body text.
_READTIME_RX = re.compile(
    r'(<h2[^>]*>)(.*?)\s*\(([^)]*\bread\b[^)]*)\)\s*(</h2>)',
    flags=re.IGNORECASE | re.DOTALL,
)


def _enhance_read_time(body: str) -> str:
    def repl(m: re.Match) -> str:
        open_tag, label, chip, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        chip_html = (
            '<span class="aigenos-chip" style="display:inline-block;font-size:11px;'
            'font-weight:600;letter-spacing:0.4px;text-transform:uppercase;padding:4px 10px;'
            'margin-left:10px;border-radius:999px;background:rgba(99,102,241,0.10);'
            'color:#6366f1;vertical-align:middle;line-height:1;">'
            f'{chip.strip()}</span>'
        )
        return f'{open_tag}{label.rstrip()}{chip_html}{close_tag}'
    return _READTIME_RX.sub(repl, body)


def _domain(url: str) -> str:
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except (ValueError, AttributeError):
        return ""


def _add_source_favicons(html: str) -> str:
    """Prepend each link with its site's favicon, so every source shows a small
    publisher icon — the visual signature of a curated newsletter. Uses Google's
    favicon service (no hosting needed; cached by Gmail)."""
    def repl(m: re.Match) -> str:
        open_tag = m.group(0)
        # Top Stories rows already render their own thumbnail + favicon.
        if "aigenos-src" in open_tag:
            return open_tag
        dom = _domain(m.group(1))
        if not dom or dom.endswith("github.com"):
            return open_tag
        fav = (
            f'<img src="https://www.google.com/s2/favicons?domain={dom}&sz=64" '
            'width="14" height="14" alt="" '
            'style="vertical-align:middle;margin:0 5px 2px 0;border-radius:3px;border:0;display:inline-block;">'
        )
        return fav + open_tag
    return re.sub(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>', repl, html)


def footer_links(cfg, now: datetime, include_unsubscribe: bool = True) -> str:
    """The footer link row: read-online (archive) · subscribe · unsubscribe.
    Each link renders only when its env var is configured. The unsubscribe slot
    accepts a URL or a sending-platform merge tag (e.g. Resend's
    ``{{{{RESEND_UNSUBSCRIBE_URL}}}}``) — required before emailing strangers."""
    a = 'style="color:#6366f1;text-decoration:none;font-weight:600;"'
    links: list[str] = []
    site_url = getattr(cfg, "site_url", "")
    if site_url:
        issue = f"{site_url}/digests/digest_{now.strftime('%Y%m%d')}.html"
        links.append(f'<a {a} href="{issue}">Read online</a>')
    # Subscribe always shows when we have somewhere to send it: the configured
    # SUBSCRIBE_URL, else the landing page's #subscribe box. Lets a forwarded
    # copy convert.
    subscribe_url = getattr(cfg, "subscribe_url", "") or (
        f"{site_url}#subscribe" if site_url else ""
    )
    if subscribe_url:
        links.append(f'<a {a} href="{subscribe_url}">Subscribe</a>')
    unsubscribe_url = getattr(cfg, "unsubscribe_url", "")
    if include_unsubscribe and unsubscribe_url:
        links.append(f'<a {a} href="{unsubscribe_url}">Unsubscribe</a>')
    if not links:
        return ""
    return "<br>" + " &nbsp;·&nbsp; ".join(links)


def render_html(
    body_fragment: str,
    now: datetime,
    engine: str = "",
    cta: str = "",
    footer: str = "",
) -> str:
    """Render the full email. `cta` is an optional pre-built HTML block (e.g. a
    subscribe call-to-action) injected after the body — it is NOT run through the
    tag-styler, so it keeps its own styling intact. `footer` is an optional
    pre-built link row (see ``footer_links``). Pass `engine=""` to omit the
    model-attribution line (SHOW_MODEL_ATTRIBUTION=false)."""
    engine_label = (
        f'<br><span style="opacity:.78;">powered by {engine}.</span>' if engine else ""
    )
    styled_body = _inline_styles(body_fragment)
    styled_body = _enhance_read_time(styled_body)
    styled_body = _add_source_favicons(styled_body)
    return _TEMPLATE.format(
        title="dAIly — Daily AI Digest",
        date=now.strftime("%A, %B %d, %Y"),
        date_short=now.strftime("%b %d").replace(" 0", " "),
        body=styled_body,
        cta=cta,
        engine=engine_label,
        footer_links=footer,
        theme=_THEME_STYLES,
    )


def subject_line(now: datetime) -> str:
    return f"dAIly — AI Digest, {now.strftime('%b %d, %Y')}"


_BODY_RX = re.compile(r"<body[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)


def render_embeddable_html(
    body_fragment: str, now: datetime, engine: str = "", cta: str = "", footer: str = ""
) -> str:
    """The full styled email (hero + logo + cards + footer) WITHOUT the outer
    <html>/<head> wrapper, so another sender (e.g. Buttondown) can drop it into
    its own email shell and subscribers get the same look as the Resend copy.
    Keeps the <style> block (dark-mode for clients that honor it) on top of the
    inline-styled markup that renders everywhere."""
    full = render_html(body_fragment, now, engine=engine, cta=cta, footer=footer)
    m = _BODY_RX.search(full)
    inner = m.group(1).strip() if m else full
    return f"<style>{_THEME_STYLES}</style>\n{inner}"


def subscribe_cta(url: str, embed_html: str = "") -> str:
    """A self-styled subscribe call-to-action (white-on-gradient, reads fine in
    both light and dark). If `embed_html` is set (SUBSCRIBE_EMBED_HTML — e.g. a
    Buttondown/Beehiiv form snippet), it is injected in place of the link button,
    keeping the CTA provider-agnostic. Returns '' if neither is set."""
    if not url and not embed_html:
        return ""
    action = embed_html or (
        f'<a href="{url}" style="display:inline-block;background:#ffffff;color:#4f46e5;'
        'font-weight:700;text-decoration:none;padding:11px 26px;border-radius:999px;font-size:15px;">'
        'Subscribe →</a>'
    )
    return (
        '<div style="margin:28px 0 8px;padding:22px 24px;border-radius:16px;'
        'background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#ffffff;text-align:center;">'
        '<div style="font-size:18px;font-weight:800;letter-spacing:-0.01em;">Want every validated bet?</div>'
        '<div style="font-size:14px;opacity:.92;margin:8px 0 14px;line-height:1.5;">'
        'Today’s Opportunity of the Day is just the teaser. <strong>The Builder’s Edge</strong> '
        'gives subscribers 3–5 fully-validated bets a day — prior-art checked, with the moat '
        'and a two-week plan for each.</div>'
        f'{action}</div>'
    )


def send_email(cfg: Config, subject: str, html: str) -> dict:
    """Send via Resend. Raises on non-2xx so CI surfaces failures."""
    resp = requests.post(
        RESEND_ENDPOINT,
        headers={
            "Authorization": f"Bearer {cfg.resend_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": cfg.email_from,
            "to": [cfg.email_to],
            "subject": subject,
            "html": html,
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Resend send failed ({resp.status_code}): {resp.text[:500]}"
        )
    data = resp.json()
    log.info("email sent to %s (id=%s)", cfg.email_to, data.get("id"))
    return data
