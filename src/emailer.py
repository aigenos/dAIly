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
from urllib.parse import quote, urlparse

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
  .aigenos-card { background: #14141f !important; border-color: #23263a !important; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.35) !important; }
  .aigenos-text { color: #ececf5 !important; }
  .aigenos-muted { color: #8e8ea8 !important; }
  .aigenos-pre td { color: #8e8ea8 !important; }
  .aigenos-pre a { color: #5eead4 !important; }
  .aigenos-idx-label { color: #8e8ea8 !important; }
  .aigenos-idx-chip { background: #14141f !important; border-color: #2a2d44 !important; color: #c8c8d8 !important; }
  .aigenos-fbcard { background: #14141f !important; border-color: #23263a !important; }
  .aigenos-share { border-color: #262a3e !important; }
  .aigenos-share-q { color: #8e8ea8 !important; }
  .aigenos-share-x, .aigenos-share-l { background: rgba(94, 234, 212, 0.14) !important; color: #5eead4 !important; }
  h2.aigenos-h2 { color: #f0f1fa !important; border-color: #262a3e !important; }
  h3.aigenos-h3 { color: #ececf5 !important; }
  p.aigenos-p, li.aigenos-li { color: #c8c8d8 !important; }
  /* Links: bright teal text + a clearly-visible underline (was near-black on dark). */
  a.aigenos-a { color: #5eead4 !important; border-bottom-color: rgba(94,234,212,0.55) !important; }
  strong.aigenos-strong { color: #ffffff !important; }
  blockquote.aigenos-bq {
    background: #1a1a26 !important;
    color: #c8c8d8 !important;
    border-color: #5eead4 !important;
  }
  .aigenos-chip {
    background: rgba(94, 234, 212, 0.16) !important;
    color: #5eead4 !important;
  }
  .aigenos-footer { color: #8e8ea8 !important; }
  .aigenos-footer a { color: #5eead4 !important; }
  .aigenos-desc { color: #8e8ea8 !important; }
  .aigenos-src-cap { color: #8e8ea8 !important; }
  .aigenos-signoff-q { color: #ececf5 !important; }
  .aigenos-signoff-s { color: #8e8ea8 !important; }
  /* Hero stays dark with light text in dark mode. It uses a SOLID dark
     background-color (not a gradient) — mail clients recognize a flat dark
     element and leave its white text alone, whereas a gradient hero got its
     text smart-inverted to near-black. These !important rules pin the colors. */
  /* Dark mode keeps a SOLID dark navy (no gradient) so Gmail/iOS smart-invert
     leaves the white wordmark alone; the baked image hero is the primary path. */
  .aigenos-hero { background-color: #080e16 !important; background-image: none !important; }
  .aigenos-hero-kicker, .aigenos-hero-mark { color: #ffffff !important; }
  .aigenos-ai { color: #6ee7b7 !important; font-style: italic !important; }
  .aigenos-hero-sub { color: rgba(255,255,255,0.88) !important; }
  .aigenos-src-row { background: #1a1a26 !important; border-color: #2a2a3d !important; }
  a.aigenos-src-title { color: #ececf5 !important; }
  .aigenos-src-meta { color: #8e8ea8 !important; }
  /* The Top Stories summary was uncovered → dark-on-dark; make it readable. */
  .aigenos-src-blurb { color: #c8c8d8 !important; }
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
<body class="aigenos-bg" style="margin:0;padding:0;background:#f5f6fa;color-scheme:light dark;">
<div class="aigenos-shell" style="max-width:720px;margin:0 auto;padding:22px 18px 30px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI Variable','Segoe UI',Roboto,'SF Pro Display','Helvetica Neue',Arial,sans-serif;font-feature-settings:'cv11','ss03';-webkit-font-smoothing:antialiased;">

  {preheader}

  <!-- Hero / masthead -->
  {hero}

  {index}

  <!-- Body card -->
  <div class="aigenos-card" style="background:#ffffff;border:1px solid #e9ebf4;border-radius:22px;padding:10px 34px 30px;margin-top:16px;box-shadow:0 1px 2px rgba(20,20,42,0.03),0 10px 30px rgba(20,20,42,0.05);">
    {prelude}
    {body}
    {cta}
  </div>

  {feedback}

  <!-- Footer -->
  <div class="aigenos-footer" style="text-align:center;color:#6b7186;font-size:12px;padding:26px 8px 6px;line-height:1.9;">
    <strong style="color:#0f766e;font-weight:800;letter-spacing:-0.01em;">dAIly</strong>
    <span style="opacity:.75;">— daily AI intelligence by aigenos</span>{footer_links}{engine}
    <br><span style="font-size:11px;opacity:.65;">© {year} aigenos · built in public ·
    <a href="https://github.com/aigenos/dAIly" style="color:#6b7186;text-decoration:underline;">open source</a></span>
  </div>

</div>
</body>
</html>"""

# ── Inline styling for the model-produced tags ────────────────────────────────
# Inline styles are the light-mode baseline. Class names are the hook for the
# dark-mode @media block above to retarget colors via CSS.
_TAG_STYLES = {
    # Section headlines are near-BLACK, not brand-teal — colored headings read
    # "blog", neutral headings read "product". Teal is reserved for links,
    # chips, and CTAs. Each h2 sits on generous air with a hairline rule.
    "<h2>": (
        '<h2 class="aigenos-h2" style="font-size:22px;margin:38px 0 10px;padding-bottom:12px;'
        'border-bottom:1px solid #edeef5;color:#101223;font-weight:800;letter-spacing:-0.015em;'
        'line-height:1.25;">'
    ),
    "<h3>": (
        '<h3 class="aigenos-h3" style="font-size:16.5px;margin:24px 0 7px;color:#101223;'
        'font-weight:700;letter-spacing:-0.008em;line-height:1.35;">'
    ),
    "<p>": (
        '<p class="aigenos-p" style="margin:11px 0;font-size:15px;color:#3f4254;'
        'line-height:1.7;">'
    ),
    "<ul>": (
        '<ul class="aigenos-ul" style="margin:10px 0 14px 0;padding-left:22px;">'
    ),
    "<li>": (
        '<li class="aigenos-li" style="margin:8px 0;font-size:15px;color:#3f4254;'
        'line-height:1.65;">'
    ),
    "<a ": (
        '<a class="aigenos-a" style="color:#0f766e;text-decoration:none;font-weight:600;'
        'border-bottom:1px solid rgba(15,118,110,0.28);" '
    ),
    # Neutral panel with a teal spine — calmer than the old mint-green wash.
    "<blockquote>": (
        '<blockquote class="aigenos-bq" style="margin:16px 0;padding:13px 18px;'
        'border-left:3px solid #0f766e;background:#f7f8fc;color:#3f4254;border-radius:0 12px 12px 0;'
        'font-size:15px;line-height:1.65;">'
    ),
    "<strong>": (
        '<strong class="aigenos-strong" style="color:#101223;font-weight:700;">'
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
            'margin-left:10px;border-radius:999px;background:rgba(15,118,110,0.12);'
            'color:#0f766e;vertical-align:middle;line-height:1;">'
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


_H2_TEXT_RX = re.compile(r"<h2[^>]*>(.*?)</h2>", re.DOTALL | re.IGNORECASE)


def _preheader(now: datetime, read_online_url: str = "") -> str:
    """The slim product bar above the hero: issue date left, Read-online right.
    Small touches like this are what make it read as a product, not a blast."""
    date = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    right = (
        f'<a href="{read_online_url}" style="color:#0f766e;text-decoration:none;'
        'font-weight:700;">Read online →</a>' if read_online_url else "&nbsp;"
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'class="aigenos-pre" style="margin:0 2px 10px;"><tr>'
        f'<td style="font-size:12px;color:#8a90a5;font-weight:600;">{date}</td>'
        f'<td style="font-size:12px;text-align:right;">{right}</td>'
        '</tr></table>'
    )


def _issue_index(body_fragment: str) -> str:
    """The "IN TODAY'S ISSUE" chip row, auto-built from the section headlines —
    the at-a-glance menu every commercial newsletter opens with. Returns '' when
    fewer than 3 sections are present (not worth a menu)."""
    names: list[str] = []
    for raw in _H2_TEXT_RX.findall(body_fragment):
        t = re.sub(r"<[^>]+>", "", raw)
        t = re.sub(r"\([^)]*\bread\b[^)]*\)", "", t, flags=re.IGNORECASE)
        t = t.split("—")[0]
        t = re.sub(r"\s+", " ", t).strip(" —–-·:")
        if t:
            names.append(t)
    if len(names) < 3:
        return ""
    chips = "".join(
        '<span class="aigenos-idx-chip" style="display:inline-block;background:#ffffff;'
        'border:1px solid #e9ebf4;color:#3f4254;border-radius:999px;padding:6px 13px;'
        f'margin:3px;font-size:12px;font-weight:600;">{n}</span>'
        for n in names
    )
    return (
        '<div class="aigenos-idx" style="text-align:center;margin:16px 2px 0;">'
        '<div class="aigenos-idx-label" style="font-size:10.5px;letter-spacing:2px;'
        'color:#8a90a5;font-weight:700;margin-bottom:8px;">IN TODAY&#8217;S ISSUE</div>'
        f'{chips}</div>'
    )


def footer_links(cfg, now: datetime, include_unsubscribe: bool = True) -> str:
    """The footer link row: read-online (archive) · subscribe · unsubscribe.
    Each link renders only when its env var is configured. The unsubscribe slot
    accepts a URL or a sending-platform merge tag (e.g. Resend's
    ``{{{{RESEND_UNSUBSCRIBE_URL}}}}``) — required before emailing strangers."""
    a = 'style="color:#0f766e;text-decoration:none;font-weight:600;"'
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


def _email_addr(email_from: str) -> str:
    """Pull the bare address out of 'Name <addr@x>' (or return as-is)."""
    m = re.search(r"<([^>]+)>", email_from or "")
    return m.group(1) if m else (email_from or "").strip()


def feedback_block(cfg, now: datetime) -> str:
    """A one-click '😍 🙂 😕 — how was today's issue?' widget + a warm sign-off.
    Links to FEEDBACK_URL (with ?r=...) when set, else a mailto to the sender."""
    base = getattr(cfg, "feedback_url", "")
    date = now.strftime("%b %d")
    if base:
        sep = "&" if "?" in base else "?"
        def link(r):
            return f"{base}{sep}r={r}"
    else:
        # Route feedback to the aigenos owner: FEEDBACK_EMAIL / EMAIL_TO, then the
        # sender address as a last resort.
        addr = (
            getattr(cfg, "feedback_email", "")
            or _email_addr(getattr(cfg, "email_from", ""))
            or "hello@aigenos.dev"
        )
        def link(r):
            return f"mailto:{addr}?subject=dAIly%20feedback%20({date}):%20{r}"
    a = ('text-decoration:none;display:inline-block;margin:0 8px;font-size:30px;'
         'line-height:1;')
    chips = "".join(
        f'<a href="{link(r)}" style="{a}" title="{t}">{e}</a>'
        for e, r, t in (("😍", "loved", "Loved it"),
                        ("🙂", "ok", "It was OK"),
                        ("😕", "meh", "Not great"))
    )
    return (
        '<div class="aigenos-fbcard" style="text-align:center;margin:18px 0 4px;'
        'padding:22px 20px;background:#ffffff;border:1px solid #e9ebf4;border-radius:18px;">'
        '<div class="aigenos-signoff-q" style="font-size:14px;font-weight:700;color:#101223;margin-bottom:12px;">'
        'How was today’s issue?</div>'
        f'<div>{chips}</div>'
        f'{_share_row(cfg, now)}'
        '<div class="aigenos-signoff-s" style="font-size:13px;color:#6b7186;margin-top:15px;line-height:1.5;">'
        'Until next time — the <strong>aigenos</strong> team 👋</div>'
        '</div>'
    )


def _share_row(cfg, now: datetime) -> str:
    """The growth loop: an explicit ask to forward + a one-tap share-on-X link
    prefilled with today's issue URL. Newsletters grow by forwarding, and
    readers forward far more when asked. '' without a SITE_URL (nothing to
    link)."""
    site_url = getattr(cfg, "site_url", "")
    if not site_url:
        return ""
    issue = f"{site_url}/digests/digest_{now.strftime('%Y%m%d')}.html"
    text = quote(
        "dAIly — a daily AI briefing that ends with what to BUILD, not just "
        f"what happened. Today's issue: {issue}"
    )
    x_link = f"https://x.com/intent/post?text={text}"
    pill = (
        'style="display:inline-block;background:rgba(15,118,110,0.10);color:#0f766e;'
        'font-weight:700;font-size:12.5px;text-decoration:none;padding:7px 15px;'
        'border-radius:999px;margin:0 4px;"'
    )
    return (
        '<div class="aigenos-share" style="margin-top:16px;padding-top:14px;'
        'border-top:1px solid #edeef5;">'
        '<div class="aigenos-share-q" style="font-size:12.5px;color:#6b7186;margin-bottom:9px;">'
        'Know one builder who’d love this? <strong>Forward it on</strong> — or share:</div>'
        f'<a href="{x_link}" class="aigenos-share-x" {pill}>𝕏 Share today’s issue</a>'
        f'<a href="{issue}" class="aigenos-share-l" {pill}>🔗 Copy the link</a>'
        '</div>'
    )


def listen_button(url: str, minutes: int = 0) -> str:
    """The ▶️ Listen pill shown at the top of the email. Mail clients can't
    embed playable audio, so this links to the hosted MP3 (one tap → the
    phone's player opens, podcast-style). '' when there's no URL."""
    if not url:
        return ""
    mins = f" · {minutes} min" if minutes else ""
    return (
        '<div style="text-align:center;margin:18px 0 2px;">'
        f'<a href="{url}" class="aigenos-listen" '
        'style="display:inline-block;background:#0f766e;color:#ffffff;font-weight:700;'
        'font-size:14px;text-decoration:none;padding:10px 22px;border-radius:999px;">'
        f'▶️&nbsp; Listen to today\'s issue{mins}</a>'
        '<div class="aigenos-muted" style="font-size:11px;color:#8a8a9a;margin-top:6px;">'
        'No time to read? Play it like a podcast.</div>'
        '</div>'
    )


def audio_player(url: str, minutes: int = 0) -> str:
    """A real inline <audio> player for the ARCHIVE page (browsers, not email).
    Falls back to a download link for anything that can't play mp3 inline."""
    if not url:
        return ""
    mins = f" · ~{minutes} min listen" if minutes else ""
    return (
        '<div class="aigenos-audio" style="margin:18px 0 6px;padding:14px 16px;'
        'border:1px solid #e4e2f3;border-radius:14px;background:#faf9ff;">'
        '<div style="font-size:13px;font-weight:700;color:#14142a;margin-bottom:8px;">'
        f'🎧 Listen to this issue{mins}</div>'
        f'<audio controls preload="none" style="width:100%;" src="{url}">'
        f'<a href="{url}">Download the audio</a></audio>'
        '</div>'
    )


def list_report_block(stats: dict, now: datetime) -> str:
    """A private 'list health' card for the OWNER's copy only (injected via the
    cta slot, so it never reaches subscribers or the archive). Shows active
    subscribers, new joins in the last 24h, cumulative unsubscribes, and total
    contacts — the daily subscriber report."""
    if not stats:
        return ""

    def tile(value, label, accent="#0f766e"):
        return (
            '<td style="text-align:center;padding:6px 4px;">'
            f'<div style="font-size:26px;font-weight:800;color:{accent};line-height:1;">{value}</div>'
            f'<div style="font-size:11px;color:#6b6b85;margin-top:5px;text-transform:uppercase;'
            f'letter-spacing:.4px;font-weight:600;">{label}</div></td>'
        )

    new_24h = stats.get("new_24h", 0)
    new_label = f"+{new_24h}" if new_24h else "0"
    new_accent = "#16a34a" if new_24h else "#6b6b85"
    return (
        '<div style="margin:26px 0 4px;padding:18px 20px;border:1px solid #e4e2f3;'
        'border-radius:16px;background:#faf9ff;">'
        '<div style="font-size:13px;font-weight:700;color:#14142a;margin-bottom:2px;">'
        '📊 Your dAIly list</div>'
        '<div style="font-size:11px;color:#8a8a9a;margin-bottom:12px;">'
        'Private — only in your copy, never sent to subscribers.</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        + tile(stats.get("active", 0), "Subscribers", "#0f766e")
        + tile(new_label, "New (24h)", new_accent)
        + tile(stats.get("unsubscribed", 0), "Unsubscribed", "#6b6b85")
        + tile(stats.get("total", 0), "Total contacts", "#6b6b85")
        + '</tr></table></div>'
    )


def _logo_html(logo_url: str, logo_url_dark: str = "") -> str:
    """The hero masthead mark. The hero is dark in every theme, so we always use
    the dark (teal) logo directly on it — on a faint translucent circle for
    definition, never a solid white tile. Falls back to the 🤖 emoji when no
    logo is configured."""
    url = logo_url_dark or logo_url
    if url:
        return (
            f'<img src="{url}" width="52" height="52" alt="aigenos" '
            'style="width:52px;height:52px;border-radius:50%;display:block;border:0;'
            'object-fit:contain;background:rgba(255,255,255,0.12);padding:5px;box-sizing:border-box;">'
        )
    return (
        '<div style="width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.16);'
        'text-align:center;font-size:27px;line-height:52px;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.18);">🤖</div>'
    )


def _css_hero(logo_url: str, logo_url_dark: str, date: str, date_short: str) -> str:
    """Fallback CSS/HTML hero (used when no HERO_IMAGE_URL is available). Some
    mail clients recolor this in dark mode; the image hero avoids that."""
    return (
        '<div class="aigenos-hero" style="background-color:#080e16;background:linear-gradient(105deg,#0d211f 0%,#0a141c 18%,#080e16 55%,#05070d 100%);border-radius:20px;padding:26px 28px;color:#ffffff;box-shadow:0 8px 32px rgba(10,20,41,0.45);">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="width:54px;vertical-align:middle;">' + _logo_html(logo_url, logo_url_dark) + '</td>'
        '<td style="vertical-align:middle;padding-left:14px;">'
        '<div class="aigenos-hero-kicker" style="font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.85;font-weight:600;color:#ffffff;">by aigenos · daily ai intelligence</div>'
        '<div class="aigenos-hero-mark" style="font-size:30px;font-weight:800;letter-spacing:-0.02em;line-height:1.05;margin-top:3px;color:#ffffff;">d<span class="aigenos-ai" style="color:#6ee7b7;font-style:italic;">AI</span>ly</div>'
        '</td>'
        '<td style="vertical-align:middle;text-align:right;white-space:nowrap;">'
        f'<span style="display:inline-block;background:rgba(255,255,255,0.18);padding:6px 13px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.3px;">{date_short}</span>'
        '</td></tr></table>'
        '<div class="aigenos-hero-sub" style="font-size:13.5px;opacity:.92;font-weight:500;line-height:1.5;margin-top:15px;padding-top:13px;border-top:1px solid rgba(255,255,255,0.18);">'
        f'📅 {date} &nbsp;·&nbsp; Cutting-edge AI in ~90 seconds — the news, the must-read research, and what to build next.'
        '</div></div>'
    )


def _hero_html(hero_image_url: str, logo_url: str, logo_url_dark: str,
               date: str, date_short: str) -> str:
    """Prefer the baked masthead IMAGE (invert-proof in every mail client); fall
    back to the CSS hero when no image URL is configured."""
    if hero_image_url:
        return (
            f'<img src="{hero_image_url}" width="720" '
            'alt="dAIly — daily AI intelligence by aigenos" '
            'style="display:block;width:100%;max-width:100%;height:auto;border:0;'
            'border-radius:20px;background:#080e16;">'
        )
    return _css_hero(logo_url, logo_url_dark, date, date_short)


def render_html(
    body_fragment: str,
    now: datetime,
    engine: str = "",
    cta: str = "",
    footer: str = "",
    logo_url: str = "",
    logo_url_dark: str = "",
    hero_image_url: str = "",
    feedback: str = "",
    prelude: str = "",
    read_online_url: str = "",
) -> str:
    """Render the full email. `cta` is an optional pre-built HTML block (e.g. a
    subscribe call-to-action) injected after the body — it is NOT run through the
    tag-styler, so it keeps its own styling intact. `footer` is an optional
    pre-built link row (see ``footer_links``). `logo_url` (+ optional
    `logo_url_dark`) swap the hero emoji for the light/dark logo. Pass
    `engine=""` to omit the model-attribution line. `prelude` is a pre-built
    HTML block (e.g. the ▶️ Listen button) rendered at the very top of the body
    card, untouched by the tag-styler."""
    engine_label = (
        f'<br><span style="opacity:.78;">powered by {engine}.</span>' if engine else ""
    )
    styled_body = _inline_styles(body_fragment)
    styled_body = _enhance_read_time(styled_body)
    styled_body = _add_source_favicons(styled_body)
    hero = _hero_html(
        hero_image_url, logo_url, logo_url_dark,
        now.strftime("%A, %B %d, %Y"),
        now.strftime("%b %d").replace(" 0", " "),
    )
    return _TEMPLATE.format(
        title="dAIly — Daily AI Digest",
        body=styled_body,
        cta=cta,
        engine=engine_label,
        footer_links=footer,
        hero=hero,
        feedback=feedback,
        prelude=prelude,
        preheader=_preheader(now, read_online_url),
        index=_issue_index(body_fragment),
        year=now.strftime("%Y"),
        theme=_THEME_STYLES,
    )


def subject_line(now: datetime) -> str:
    return f"dAIly — AI Digest, {now.strftime('%b %d, %Y')}"


_BODY_RX = re.compile(r"<body[^>]*>(.*)</body>", re.IGNORECASE | re.DOTALL)


def render_embeddable_html(
    body_fragment: str, now: datetime, engine: str = "", cta: str = "",
    footer: str = "", logo_url: str = "", logo_url_dark: str = "",
    hero_image_url: str = "", feedback: str = "", prelude: str = "",
    read_online_url: str = "",
) -> str:
    """The full styled email (hero + logo + cards + footer) WITHOUT the outer
    <html>/<head> wrapper, so another sender (e.g. Buttondown) can drop it into
    its own email shell and subscribers get the same look as the Resend copy.
    Keeps the <style> block (dark-mode for clients that honor it) on top of the
    inline-styled markup that renders everywhere."""
    full = render_html(body_fragment, now, engine=engine, cta=cta, footer=footer,
                       logo_url=logo_url, logo_url_dark=logo_url_dark,
                       hero_image_url=hero_image_url, feedback=feedback,
                       prelude=prelude, read_online_url=read_online_url)
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
        f'<a href="{url}" style="display:inline-block;background:#ffffff;color:#0f766e;'
        'font-weight:700;text-decoration:none;padding:11px 26px;border-radius:999px;font-size:15px;">'
        'Subscribe →</a>'
    )
    return (
        '<div style="margin:28px 0 8px;padding:22px 24px;border-radius:16px;'
        'background:linear-gradient(135deg,#065f46,#0d9488);color:#ffffff;text-align:center;">'
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
            # Replies land in the owner's inbox, not the (often no-reply) sender.
            **({"reply_to": cfg.reply_to} if getattr(cfg, "reply_to", "") else {}),
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
