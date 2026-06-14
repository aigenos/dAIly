"""Public digest archive for GitHub Pages.

Writes each day's digest to ``<archive_dir>/digests/digest_YYYYMMDD.html``,
regenerates ``<archive_dir>/index.html`` listing every past issue (with each
issue's Game-Changer headline as preview text), an Atom feed
(``<archive_dir>/feed.xml``) so people can follow without email, and a receipts
log (``<archive_dir>/receipts.md``) recording every Opportunity of the Day —
the "my agent suggested X before Y launched" evidence base.

SAFETY: private sections (e.g. the Opportunity Map) are stripped here BEFORE
anything is written, using the ``<!--SECTION:id-->`` markers the model emits.
The published archive therefore never contains your secret sauce, even though the
emailed copy does.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

from .emailer import footer_links, render_html, subscribe_cta

log = logging.getLogger("aigenos.archive")

_DIGEST_RX = re.compile(r"digest_(\d{8})\.html$")


def strip_private_sections(
    body_fragment: str, private_ids: list[str], sentinels: list[str] | None = None
) -> str:
    """Remove private sections two ways, because a weak model may omit markers:

    1. Marker-based: from <!--SECTION:id--> to the next marker (clean path).
    2. Heading-based fallback: any <h2> whose text contains a private sentinel,
       through to the next <h2> (or end). Catches the case where the model
       dropped the comment marker but kept the heading.
    """
    out = body_fragment
    for sid in private_ids:
        out = re.sub(
            r"<!--SECTION:" + re.escape(sid) + r"-->.*?(?=<!--SECTION:|\Z)",
            "", out, flags=re.DOTALL,
        )
    for kw in (sentinels or []):
        out = re.sub(
            r"<h2[^>]*>[^<]*" + re.escape(kw) + r".*?(?=<h2|\Z)",
            "", out, flags=re.DOTALL | re.IGNORECASE,
        )
    return out


def _list_issues(digests_dir: str) -> list[tuple[str, datetime]]:
    """Return (filename, date) for each archived digest, newest first."""
    issues: list[tuple[str, datetime]] = []
    if not os.path.isdir(digests_dir):
        return issues
    for name in os.listdir(digests_dir):
        m = _DIGEST_RX.search(name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            continue
        issues.append((name, d))
    issues.sort(key=lambda t: t[1], reverse=True)
    return issues


_GAMECHANGER_RX = re.compile(
    r"Game-Changer.*?</h3>\s*<p[^>]*>(.*?)</p>", flags=re.DOTALL | re.IGNORECASE
)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def issue_headline(issue_path: str, max_len: int = 170) -> str:
    """The issue's Game-Changer first sentence(s) — used as preview text on the
    index and in the Atom feed. Fail-open: any problem returns ''."""
    try:
        with open(issue_path, encoding="utf-8") as fh:
            html = fh.read(400_000)
        m = _GAMECHANGER_RX.search(html)
        if not m:
            return ""
        text = _strip_tags(m.group(1))
        if len(text) > max_len:
            text = text[: max_len].rsplit(" ", 1)[0] + "…"
        return text
    except OSError:
        return ""


_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="description" content="dAIly — your personal AI analyst. A 90-second daily briefing that ends with what to build, every claim source-linked.">
<title>{title}</title>
<link rel="alternate" type="application/atom+xml" title="dAIly" href="feed.xml">
<style>
:root {{
  color-scheme: light dark;
  --bg:#f3f4f8; --surface:#fff; --text:#14142a; --text-soft:#3a3a55; --muted:#6b6b85;
  --accent:#6366f1; --border:#e8e6f5; --gold:#fcd34d;
  --shadow:0 1px 2px rgba(20,20,42,.04),0 8px 24px rgba(20,20,42,.06);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:#0a0a14; --surface:#14141f; --text:#ececf5; --text-soft:#c8c8d8; --muted:#8e8ea8;
    --accent:#8b8cff; --border:#2a2a3d;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);
  }}
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI Variable','Segoe UI',Roboto,Arial,sans-serif;
  -webkit-font-smoothing:antialiased; line-height:1.6;
}}
.wrap {{ max-width:760px; margin:0 auto; padding:32px 18px 64px; }}
@keyframes heroShift {{ 0%{{background-position:0% 50%}} 50%{{background-position:100% 50%}} 100%{{background-position:0% 50%}} }}
@keyframes rise {{ from{{opacity:0;transform:translateY(14px)}} to{{opacity:1;transform:none}} }}
@keyframes blip {{ 0%,100%{{opacity:1}} 50%{{opacity:.35}} }}
.hero {{
  position:relative; overflow:hidden;
  background:linear-gradient(120deg,#4f46e5,#7c3aed,#c026d3,#7c3aed,#4f46e5);
  background-size:300% 300%; animation:heroShift 14s ease infinite;
  border-radius:24px; padding:42px 36px 36px; color:#fff;
  box-shadow:0 12px 40px rgba(79,70,229,.35);
}}
.hero .kicker {{ font-size:11px; letter-spacing:3px; text-transform:uppercase; opacity:.85; font-weight:700; }}
.hero h1 {{ margin:12px 0 8px; font-size:46px; font-weight:800; letter-spacing:-.03em; line-height:1; }}
.hero h1 .ai {{ color:var(--gold); }}
.hero .tag {{ margin:0 0 22px; font-size:17.5px; opacity:.95; font-weight:500; max-width:34em; }}
.hero .live {{
  position:absolute; top:26px; right:28px; font-size:11px; font-weight:800; letter-spacing:1px;
  display:flex; align-items:center; gap:7px; opacity:.95;
}}
.hero .live i {{ width:9px; height:9px; border-radius:50%; background:#4ade80; animation:blip 1.6s ease infinite; }}
.cta {{ display:flex; flex-wrap:wrap; gap:10px; }}
.btn {{
  display:inline-block; padding:12px 22px; border-radius:999px; font-weight:700; font-size:14.5px;
  text-decoration:none; transition:transform .12s ease, box-shadow .12s ease;
}}
.btn:hover {{ transform:translateY(-2px); }}
.btn.solid {{ background:#fff; color:#4f46e5; box-shadow:0 4px 14px rgba(0,0,0,.18); }}
.btn.ghost {{ background:rgba(255,255,255,.16); color:#fff; box-shadow:inset 0 0 0 1px rgba(255,255,255,.35); }}
.stats {{ display:flex; flex-wrap:wrap; gap:8px; margin:18px 0 0; animation:rise .7s ease both .15s; }}
.stats span {{
  background:var(--surface); border:1px solid var(--border); color:var(--text-soft);
  border-radius:999px; padding:7px 14px; font-size:12.5px; font-weight:650; box-shadow:var(--shadow);
}}
.section-label {{
  margin:34px 0 0; font-size:12px; font-weight:800; letter-spacing:2px;
  text-transform:uppercase; color:var(--muted);
}}
.featured {{ display:block; text-decoration:none; color:var(--text); margin-top:12px;
  background:var(--surface); border:1px solid var(--border); border-left:4px solid var(--accent);
  border-radius:16px; padding:22px 24px; box-shadow:var(--shadow);
  transition:transform .12s ease, border-color .12s ease; animation:rise .7s ease both .25s;
}}
.featured:hover {{ transform:translateY(-2px); }}
.featured .when {{ font-size:12.5px; font-weight:700; color:var(--accent); letter-spacing:.5px; text-transform:uppercase; }}
.featured .what {{ font-size:19px; font-weight:750; letter-spacing:-.01em; line-height:1.4; margin:6px 0 4px; }}
.featured .read {{ font-size:14px; font-weight:700; color:var(--accent); }}
ul.issues {{ list-style:none; margin:12px 0 0; padding:0; }}
li.issue a {{
  display:block;
  background:var(--surface); border:1px solid var(--border); border-radius:14px;
  padding:15px 20px; margin:10px 0; text-decoration:none; color:var(--text);
  box-shadow:var(--shadow); transition:transform .12s ease, border-color .12s ease;
}}
li.issue a:hover {{ transform:translateY(-2px); border-color:var(--accent); }}
li.issue .row {{ display:flex; justify-content:space-between; align-items:center; }}
li.issue .date {{ font-weight:650; font-size:15.5px; }}
li.issue .go {{ color:var(--accent); font-weight:700; font-size:14px; white-space:nowrap; }}
li.issue .headline {{ color:var(--muted); font-size:13.5px; line-height:1.5; margin-top:5px; }}
.fork {{
  margin-top:34px; background:var(--surface); border:1px solid var(--border); border-radius:16px;
  padding:22px 24px; box-shadow:var(--shadow);
}}
.fork h2 {{ margin:0 0 6px; font-size:18px; letter-spacing:-.01em; }}
.fork p {{ margin:0 0 14px; color:var(--text-soft); font-size:14.5px; }}
.fork .chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.fork .chips a {{
  text-decoration:none; font-weight:700; font-size:13.5px; color:var(--accent);
  background:transparent; border:1px solid var(--border); border-radius:999px; padding:8px 16px;
  transition:transform .12s ease, border-color .12s ease;
}}
.fork .chips a:hover {{ transform:translateY(-2px); border-color:var(--accent); }}
.empty {{ color:var(--muted); margin-top:24px; }}
.foot {{ text-align:center; color:var(--muted); font-size:12px; margin-top:44px; }}
.foot a {{ color:var(--accent); text-decoration:none; }}
@media (max-width:560px) {{
  .hero {{ padding:32px 24px 28px; }}
  .hero h1 {{ font-size:38px; }}
  .hero .live {{ display:none; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="live"><i></i>SHIPS DAILY</div>
    <div class="kicker">by aigenos · daily ai intelligence</div>
    <h1>d<span class="ai">AI</span>ly</h1>
    <p class="tag">Your personal AI analyst — reads everything in AI every day and tells
    you <strong>what to build</strong>. 90 seconds, every claim source-linked.</p>
    <div class="cta">{cta_buttons}</div>
  </div>
  <div class="stats">{stats}</div>
  {subscribe}
  {body}
  <div class="fork">
    <h2>🔁 Fork it for <em>your</em> field</h2>
    <p>This whole agent retargets with one env var — same synthesis, different beat.
    Run it free on GitHub Actions in ~5 minutes.</p>
    <div class="chips">
      <a href="{repo_url}">🔒 SOURCE_PRESET=security</a>
      <a href="{repo_url}">🧬 SOURCE_PRESET=biotech</a>
      <a href="{repo_url}">💸 SOURCE_PRESET=fintech</a>
      <a href="{repo_url}#run-your-own-in-5-minutes">🚀 Run your own →</a>
    </div>
  </div>
  <div class="foot">
    <strong>dAIly</strong> by <a href="https://github.com/aigenos">aigenos</a> ·
    <a href="{repo_url}">GitHub</a> · <a href="feed.xml">RSS</a>
  </div>
</div>
</body>
</html>"""

_REPO_URL = "https://github.com/aigenos/dAIly"


def _render_subscribe(cfg) -> str:
    """One-click subscribe box for the landing page.

    - If SUBSCRIBE_EMBED_HTML is set (a provider's form snippet — Buttondown,
      Beehiiv, …), inject it verbatim inside the card. Provider-agnostic.
    - Else if SUBSCRIBE_FORM_ACTION is set (e.g. a Buttondown embed-subscribe
      URL), render a one-field POST form — works on a static site, no backend.
    - Else if SUBSCRIBE_URL is set, render a button linking to it.
    - Else render nothing.
    """
    embed = getattr(cfg, "subscribe_embed_html", "")
    action = getattr(cfg, "subscribe_form_action", "")
    url = getattr(cfg, "subscribe_url", "")
    card_open = (
        '<div id="subscribe" style="background:var(--surface);border:1px solid var(--border);'
        'border-radius:16px;padding:22px 24px;margin:18px 0 6px;box-shadow:var(--shadow);'
        'text-align:center;">'
        '<div style="font-size:19px;font-weight:750;color:var(--text);letter-spacing:-.01em;">'
        '📬 Get dAIly free in your inbox</div>'
        '<div style="font-size:14px;color:var(--muted);margin:6px 0 15px;">'
        'One email a day · the AI signal that matters in ~90 seconds · unsubscribe anytime.</div>'
    )
    btn = (
        'padding:12px 24px;border:0;border-radius:10px;font-weight:700;font-size:15px;'
        'background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;cursor:pointer;'
        'text-decoration:none;display:inline-block;'
    )
    if embed:
        return card_open + embed + "</div>"
    if action:
        form = (
            f'<form action="{action}" method="post" target="popupwindow" '
            'style="display:flex;gap:8px;max-width:440px;margin:0 auto;flex-wrap:wrap;justify-content:center;">'
            '<input type="email" name="email" required placeholder="you@email.com" '
            'style="flex:1;min-width:200px;padding:12px 14px;border:1px solid var(--border);'
            'border-radius:10px;font-size:15px;background:var(--bg);color:var(--text);">'
            f'<button type="submit" style="{btn}">Subscribe →</button></form>'
        )
        return card_open + form + "</div>"
    if url:
        return card_open + f'<a href="{url}" style="{btn}">Subscribe →</a></div>'
    return ""


def _date_label(d: datetime) -> str:
    return (
        d.strftime("%A, %B %-d, %Y") if os.name != "nt"
        else d.strftime("%A, %B %d, %Y")
    )


def _render_index(cfg, issues: list[tuple[str, datetime, str]]) -> str:
    # Hero CTA row. Subscribe goes to the on-page form when one renders,
    # otherwise straight to SUBSCRIBE_URL; omitted when neither exists.
    buttons: list[str] = []
    if issues:
        buttons.append(
            f'<a class="btn solid" href="digests/{issues[0][0]}">📬 Read today\'s issue</a>'
        )
    has_form = bool(
        getattr(cfg, "subscribe_embed_html", "")
        or getattr(cfg, "subscribe_form_action", "")
    )
    sub_url = getattr(cfg, "subscribe_url", "")
    if has_form:
        buttons.append('<a class="btn ghost" href="#subscribe">✉️ Subscribe free</a>')
    elif sub_url:
        buttons.append(f'<a class="btn ghost" href="{_esc(sub_url)}">✉️ Subscribe free</a>')
    buttons.append(f'<a class="btn ghost" href="{_REPO_URL}">⭐ Star on GitHub</a>')
    buttons.append('<a class="btn ghost" href="feed.xml">📡 RSS</a>')

    # Proof-of-life stats under the hero.
    try:
        from .sources import RSS_FEEDS, WEB_SEARCH_TARGETS
        n_sources = len(RSS_FEEDS) + len(WEB_SEARCH_TARGETS)
    except Exception:  # noqa: BLE001 — stats are decoration, never fatal
        n_sources = 0
    stats = [
        f"📰 {len(issues)} issue{'s' if len(issues) != 1 else ''} published",
        *([f"🛰️ {n_sources}+ sources scanned daily"] if n_sources else []),
        "⚡ essentials in 90 seconds",
        "🔗 every claim source-linked",
        "🤖 runs itself on GitHub Actions",
    ]
    stats_html = "".join(f"<span>{s}</span>" for s in stats)

    if issues:
        # Newest issue gets the spotlight; the rest are the archive list.
        name, d, headline = issues[0]
        what = f"🎯 {_esc(headline)}" if headline else "Today's briefing is live."
        body = (
            '<div class="section-label">Latest issue</div>\n'
            f'  <a class="featured" href="digests/{name}">'
            f'<div class="when">{_date_label(d)}</div>'
            f'<div class="what">{what}</div>'
            f'<div class="read">Read the full briefing →</div></a>'
        )
        if issues[1:]:
            rows = []
            for name, d, headline in issues[1:]:
                preview = (
                    f'<div class="headline">🎯 {_esc(headline)}</div>' if headline else ""
                )
                rows.append(
                    f'    <li class="issue"><a href="digests/{name}">'
                    f'<div class="row"><span class="date">{_date_label(d)}</span>'
                    f'<span class="go">Read →</span></div>{preview}</a></li>'
                )
            body += (
                '\n  <div class="section-label">Past issues</div>\n'
                '  <ul class="issues">\n' + "\n".join(rows) + "\n  </ul>"
            )
    else:
        body = '  <p class="empty">No issues published yet — the first one ships with tomorrow\'s run.</p>'

    return _INDEX_TEMPLATE.format(
        title=cfg.site_title,
        cta_buttons="".join(buttons),
        stats=stats_html,
        subscribe=_render_subscribe(cfg),
        body=body,
        repo_url=_REPO_URL,
    )


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_feed(cfg, issues: list[tuple[str, datetime, str]]) -> str:
    """Atom feed of the archive — follow the digest without email. Requires
    SITE_URL (Atom links must be absolute)."""
    site = cfg.site_url
    updated = (
        issues[0][1].replace(tzinfo=timezone.utc) if issues
        else datetime.now(timezone.utc)
    )
    entries: list[str] = []
    for name, d, headline in issues:
        url = f"{site}/digests/{name}"
        title = f"dAIly — {d.strftime('%B %d, %Y')}"
        if headline:
            title += f": {headline}"
        iso = d.replace(tzinfo=timezone.utc).isoformat()
        entries.append(
            "  <entry>\n"
            f"    <title>{_esc(title)}</title>\n"
            f'    <link href="{_esc(url)}"/>\n'
            f"    <id>{_esc(url)}</id>\n"
            f"    <updated>{iso}</updated>\n"
            f"    <summary>{_esc(headline) or 'Daily AI intelligence briefing.'}</summary>\n"
            "  </entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>{_esc(cfg.site_title)}</title>\n"
        f'  <link href="{_esc(site)}/"/>\n'
        f'  <link rel="self" href="{_esc(site)}/feed.xml"/>\n'
        f"  <id>{_esc(site)}/</id>\n"
        f"  <updated>{updated.isoformat()}</updated>\n"
        + "\n".join(entries)
        + "\n</feed>\n"
    )


_OPP_TITLE_RX = re.compile(
    r"<!--SECTION:opp_teaser-->.*?<h3[^>]*>(.*?)</h3>", flags=re.DOTALL
)


def append_receipt(cfg, public_fragment: str, now: datetime) -> None:
    """Append today's Opportunity of the Day to <archive_dir>/receipts.md — the
    'called it' log that builds the agent's track record over time. Idempotent
    per day; fail-open (a receipts problem never blocks publishing)."""
    try:
        m = _OPP_TITLE_RX.search(public_fragment)
        if not m:
            log.warning("receipts: no Opportunity of the Day title found — skipped")
            return
        title = _strip_tags(m.group(1))
        if not title:
            return
        stamp = now.strftime("%Y-%m-%d")
        issue_name = f"digest_{now.strftime('%Y%m%d')}.html"
        link = (
            f"{cfg.site_url}/digests/{issue_name}" if cfg.site_url
            else f"digests/{issue_name}"
        )
        path = os.path.join(cfg.archive_dir, "receipts.md")
        existing = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                existing = fh.read()
        if issue_name in existing:
            return  # already logged today (re-run)
        if not existing:
            existing = (
                "# Receipts — Opportunity of the Day, every day\n\n"
                "What this agent said to build, and when. When one of these "
                "ships as a product or paper later, this log is the proof it "
                "was called here first.\n\n"
            )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(existing.rstrip() + f"\n- **{stamp}** — [{title}]({link})\n")
        log.info("receipts: logged %r", title)
    except Exception as exc:  # noqa: BLE001 — receipts must never block publishing
        log.warning("receipts append failed: %s", exc)


def publish(
    cfg, body_fragment: str, now: datetime, engine: str,
    private_ids: list[str], sentinels: list[str] | None = None,
) -> str:
    """Strip private sections, write the public issue, regenerate the index.

    FAIL-CLOSED: if any private sentinel survives stripping (e.g. a weak model
    mangled the section so neither marker nor heading matched), we refuse to
    publish rather than risk leaking paid/private content.

    Returns the path to the written issue file.
    """
    sentinels = sentinels or []
    before_len = len(body_fragment)
    public_fragment = strip_private_sections(body_fragment, private_ids, sentinels)
    removed = before_len - len(public_fragment)

    leaks = [kw for kw in sentinels if kw.lower() in public_fragment.lower()]
    if leaks:
        raise RuntimeError(
            "refusing to publish public archive — private content may have leaked "
            f"(sentinel still present: {leaks}). The model likely renamed or "
            "dropped the private section's marker AND heading. Email still sent; "
            "archive skipped this run."
        )

    # Public archive gets the subscribe CTA (the freemium upsell); the email does
    # not need it. No-op when SUBSCRIBE_URL / SUBSCRIBE_EMBED_HTML are unset.
    cta = subscribe_cta(
        getattr(cfg, "subscribe_url", ""), getattr(cfg, "subscribe_embed_html", "")
    )
    public_html = render_html(
        public_fragment,
        now,
        engine=engine if getattr(cfg, "show_model_attribution", True) else "",
        cta=cta,
        footer=footer_links(cfg, now, include_unsubscribe=False),
    )

    digests_dir = os.path.join(cfg.archive_dir, "digests")
    os.makedirs(digests_dir, exist_ok=True)

    issue_name = f"digest_{now.strftime('%Y%m%d')}.html"
    issue_path = os.path.join(digests_dir, issue_name)
    with open(issue_path, "w", encoding="utf-8") as fh:
        fh.write(public_html)

    # Regenerate the index (and Atom feed) over all issues now on disk, each
    # previewed by its Game-Changer headline.
    issues = [
        (name, d, issue_headline(os.path.join(digests_dir, name)))
        for name, d in _list_issues(digests_dir)
    ]
    index_html = _render_index(cfg, issues)
    index_path = os.path.join(cfg.archive_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(index_html)
    if cfg.site_url:
        with open(os.path.join(cfg.archive_dir, "feed.xml"), "w", encoding="utf-8") as fh:
            fh.write(_render_feed(cfg, issues))
    else:
        log.info("feed.xml skipped — set SITE_URL to publish an Atom feed")

    # The "called it" log.
    append_receipt(cfg, public_fragment, now)

    log.info("archived public issue → %s (index regenerated)", issue_path)
    if private_ids or sentinels:
        log.info(
            "private-content guard: removed %d chars; sentinels clear (%s)",
            removed, ", ".join(sentinels) or "none",
        )
    return issue_path
