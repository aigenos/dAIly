"""Synthesis layer: turn raw fetched items into a curated digest.

Builds the (provider-agnostic) prompt, then delegates generation to the configured
provider (Gemini or Claude) which grounds itself with web search to (a) curate and
deduplicate the day's signal, (b) extract learnings + next steps, (c) propose
OSS/product ideas, and (d) surface open problems in agentic AI worth publishing on.

The model returns a self-contained HTML body fragment which the emailer wraps in a
styled template.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from . import providers
from .config import Config
from .fetchers import Item
from .sources import WEB_SEARCH_TARGETS

log = logging.getLogger("aigenos.analyzer")

SYSTEM_PROMPT = """\
You are an elite AI industry + research analyst writing a daily intelligence \
briefing for a senior AI engineer whose goals are: (1) stay at the cutting edge \
of the AI stack so it directly improves day-to-day AI work, (2) spot missing \
pieces in the ecosystem, and (3) turn those gaps into a viral, revenue-generating \
product, framework, OSS project, startup, or publishable paper. The reader wants \
to build something new — not just consume news.

DESIGN PRINCIPLE — INFORMATION PYRAMID. The briefing is structured so a reader \
with 90 seconds gets everything essential; a reader with 10 minutes gets depth. \
The TOP section must stand alone: if the reader stops there, they should still \
have the full day's signal. No section should bury its thesis.

VOICE. Technical, specific, signal-dense. Name models, libraries, benchmarks, \
numbers, paper IDs, repo names, round sizes. No hype, no filler, no "in today's \
fast-moving world" preambles. Use bullets over prose wherever possible. Short \
sentences. Active voice. Bold the headline of each bullet so the reader can \
skim. No paragraph longer than 3 sentences.

SOURCES. You are given candidate items fetched from frontier labs, AI-engineer \
newsletters, infra/tooling vendors, community feeds (Reddit, HN), and recent \
arXiv papers. Some sources may be missing or stale — use web search to verify, \
fill gaps, and pull anything important from the last few days that the candidate \
list missed (especially trending GitHub repos, Hugging Face models, eval \
leaderboard moves, AI funding rounds, and YC / Show HN / Product Hunt launches). \
Cross-check claims; do not invent releases. Every factual claim must correspond \
to a real, linkable primary source.

CITATIONS — NON-NEGOTIABLE. Every single factual claim, story, paper, release, \
benchmark number, funding round, or opportunity proof-point MUST be followed by a \
real <a href="..."> link to its primary source. No orphan claims. When an item \
comes from the candidate list below, use its EXACT url — do not paraphrase or \
guess the link. When you pull something via web search, link the canonical \
primary source (the lab's own post, the arXiv abstract, the official repo), not \
an aggregator. If you cannot find a source for a claim, DROP the claim. A bullet \
without a link is a bug. The reader uses these links to verify truth.

Curate ruthlessly. Deduplicate. Rank by importance to the reader's goals — \
prioritize signal that either (a) changes how the reader should build AI today, \
or (b) reveals a gap that a small team could exploit.

ONE ITEM, ONE SECTION. Each story/paper/launch may appear in AT MOST ONE \
section of the briefing. The only exception: the Game-Changer may be referenced \
ONCE more in Stack Signals, and only if you add a genuinely new angle there \
(benchmark numbers, adoption/velocity data) — never a restated summary. Before \
emitting, scan your draft for any item mentioned twice and cut the duplicate."""

# ── Briefing sections ─────────────────────────────────────────────────────────
# Each section is (id, order, instructions). Public sections live here. Private
# sections (e.g. the Opportunity Map — the "secret sauce") are loaded at runtime
# from the gitignored src/private/ package, so they never appear in the public
# repo and a public clone simply omits them. See src/private/README.md.
#
# Every section instructs the model to emit an HTML-comment marker
# (<!--SECTION:id-->) right before its <h2>. Markers are invisible in email but
# let the archive layer strip private sections before publishing publicly.

_INSTRUCTIONS_HEADER = """\
Produce the briefing as a single self-contained HTML fragment (no <html>, <head>, \
or <body> tags — just the inner content). Use ONLY these tags: <h2>, <h3>, <p>, \
<ul>, <li>, <a>, <strong>, <em>, <blockquote>, plus HTML comments. Every external \
reference must be a real <a href="..."> link to the primary source.

Structure it as EXACTLY these {n} sections, in the order given below. Immediately \
before each section's <h2>, output that section's HTML-comment marker (shown at \
the top of the section, e.g. <!--SECTION:pulse-->) on its own line — these are \
invisible in email and let tooling identify sections. Each <h2> must end with its \
read-time budget in parentheses. Do not add, drop, reorder, or rename sections, \
and do not emit any section not listed below.

TRUTHFULNESS — READ TWICE. Only report a development if it is (a) present in the \
candidate list below, or (b) something you verified THIS run via web search. Do \
NOT report rumors, leaks, "alleged" items, or "unconfirmed" reports. Do NOT \
invent model names, version numbers, funding amounts, benchmark scores, or \
release dates. If you are not certain an item is real and recent, OMIT it. \
Fabricating a plausible-sounding item is the single worst failure — a shorter, \
fully-true briefing beats a longer one with one made-up item.

LINKS — every claim is clickable. Each item you mention must be wrapped in or \
followed by a real <a href="..."> to its primary source. For candidate items, \
use the URL printed under that item VERBATIM. Example of the required style:
  <li><strong><a href="https://arxiv.org/abs/2606.07454">Code2LoRA</a></strong> \
— hypernetwork-generated LoRA adapters for code models.</li>
A claim with no link will be treated as unverified and is a defect.

LINK HYGIENE. Link each item EXACTLY ONCE per bullet: hyperlink the item's \
title/name itself. Never append a trailing "<a>source</a>" / "<a>link</a>" that \
points to the same URL as the title link — that is a defect. Always use https:// \
URLs (arXiv links in particular must be https://arxiv.org/...)."""

_INSTRUCTIONS_FOOTER = """\
End with a one-line <p><em>…</em></p> sign-off. Output ONLY the HTML fragment. \
No markdown code fences, no commentary before or after."""

_SECTION_PULSE = ("pulse", 10, """\
<!--SECTION:pulse-->
<h2>⚡ The Pulse — If You Only Read One Thing (90 sec read)</h2>
This section MUST stand alone. A reader who stops here should still have the
full day's signal. Two sub-blocks:

<h3>🎯 Today's Game-Changer</h3>
The single most important development from the last 24–72 hours — pick ONE.
"Important" means biggest impact on what an AI builder can DO or KNOW: new
models, capabilities, tools, benchmarks, or research. MAJOR policy / regulatory /
legal news that changes what builders can access or ship — a government blocking,
banning, or restricting a model, export controls, landmark AI regulation, or a
major lawsuit or safety incident with real product impact — IS high-signal; treat
it as Game-Changer-worthy. Only DEPRIORITIZE minor corporate / financial PR
(routine funding rounds, IPOs, SEC filings, hires, partnerships) — do not lead
with that unless it directly changes capabilities. A 2–3 sentence <p>: what
happened (with the primary <a> link, named model / repo / number), then one tight
clause on why it matters more than anything else today. If nothing is truly
game-changing, say so honestly and elevate the most consequential item instead —
do not manufacture drama.

<h3>📍 In a Nutshell</h3>
A <ul> of 8–12 ultra-tight one-line bullets covering everything else important
today: model releases, infra changes, major AI policy / regulation / government
actions, funding, eval leaderboard moves, big papers, ecosystem shifts, notable
launches. Pattern per bullet:
<strong>X shipped Y</strong> — one-clause why-it-matters. <a>source</a>
Skim-readable in under a minute. Cluster related bullets next to each other.
Zero filler. If it doesn't change a builder's decisions or signal a gap, cut it.""")

_SECTION_OPP_TEASER = ("opp_teaser", 20, """\
<!--SECTION:opp_teaser-->
<h2>🚀 Opportunity of the Day (2 min read)</h2>
Pick THE single most compelling thing to build from today's signal — the one bet
with the clearest path to BOTH viral adoption and revenue. Present just this one,
in full. An <h3> with a punchy product/project name (not a description), then a
<ul> with these EXACT bolded labels in order:
<ul>
<li><strong>The gap:</strong> what's missing or broken in the current AI stack
(cite the specific news/paper above that exposes it).</li>
<li><strong>Why now:</strong> what changed in the last few days that makes this
newly tractable (a new model, API, benchmark, price drop, or capability shift).</li>
<li><strong>Build as:</strong> pick one — arXiv paper / OSS library / dev tool /
SaaS product / vertical app / startup — and say why that shape fits.</li>
<li><strong>Wedge &amp; moat:</strong> the first user, the first dollar, and what
compounds over time.</li>
<li><strong>Already heating up:</strong> 2–3 concrete, linked proof points of real
early demand (HN thread, repo with star velocity, recent funding, Show HN). If
none, mark <em>(speculative — no validation signal yet)</em> honestly.</li>
<li><strong>Closest existing solution:</strong> search for what already exists —
name the nearest real product / repo / paper (with a link) and one clause on why
there's still an opening (timing, a gap it misses, or a better wedge). If the
space is already crowded with no clear opening, pick a different opportunity.</li>
<li><strong>First step this week:</strong> one concrete action to validate or
prototype it in the next 7 days.</li>
</ul>
EVIDENCE BAR — the opportunity must rest on AT LEAST TWO INDEPENDENT signals
from unrelated sources (e.g. a paper + a product launch, or a benchmark move +
a funded startup). A single Reddit/HN post is NOT sufficient evidence for "Why
now" or "Already heating up" — if you only have one signal, pick a different
opportunity. QUANTIFY community interest wherever possible ("1.2k upvotes on
r/LocalLLaMA", "#1 on HF Daily Papers today", "4.3k stars in 48h") — vague
claims like "high community interest" are a defect.
PRIOR ART — do not propose something that already exists in mature form. Use web
search to verify; the "Closest existing solution" line must name the nearest real
alternative and justify why the opening is still open, or you must pick another
idea. Do not re-propose an opportunity listed under ALREADY PROPOSED above.
Make this the strongest, most shareable pick of the day — the single best thing
to build right now.""")

_SECTION_STACK = ("stack", 30, """\
<!--SECTION:stack-->
<h2>📊 Stack Signals — Pick Your Tools (3 min read)</h2>
Three skim-friendly sub-blocks under <h3> headers. Bullets, not prose.

<h3>Benchmarks &amp; Evals</h3>
What moved on LMSYS Arena, SWE-bench, GAIA, τ-bench, HumanEval, MMLU-Pro,
LiveCodeBench, MTEB, or any other live leaderboard in the last few days. Note
any NEW benchmark released — those signal what the next race is about. Each
bullet: who moved, by how much, link to source. If nothing material moved, say
"no notable leaderboard moves" — do not pad.

<h3>Repo &amp; Model Velocity</h3>
A <ul> of the 5–8 fastest-rising AI-related GitHub repos (last 24–72h) plus
trending Hugging Face models / Spaces. Each bullet: linked name, one clause on
what it does, one clause on why dev mindshare is shifting there (problem it
solves, who's adopting it).

<h3>Funding &amp; Launches — with Thesis</h3>
AI rounds announced in the last few days plus notable Show HN / Product Hunt /
YC batch AI launches. For each bullet: company (linked), round size + stage (or
"Show HN" / "PH #1"), and crucially a <strong>Thesis:</strong> one-line
extraction of WHAT BET this round/launch is buying (e.g. "vertical agent for
healthcare RCM", "open-weight reasoning model for sub-$1/M tokens"). Skip any
item with no clear thesis.""")

_SECTION_DEEP = ("deep", 40, """\
<!--SECTION:deep-->
<h2>🔬 Deep Reads — For When You Have Time (skip if rushed)</h2>
Two sub-blocks for readers who want depth. Everything above already gave them
the signal — this section is the depth layer.

<h3>📖 The One Deep Read</h3>
Pick the single most important paper or essay from the last few days and tell
the reader to ACTUALLY read it end-to-end. <h3> already provided — follow it
with a <p>: linked title + authors, 2–3 sentences explaining why this is THE
piece to read this week (what it changes, why it's worth a full hour), and a
<strong>Read it for:</strong> one-line takeaway preview.

<h3>📑 Supporting Research</h3>
A <ul> of 5–8 other recent arXiv papers / lab research posts worth knowing
about. Each <li>: linked title, authors (or "et al."), one sentence on the
contribution and result. Terse — this is a scanning list.""")

# Public sections, in display order. Private sections slot in by their `order`.
# The Opportunity-of-the-Day teaser is PUBLIC (it ships in the archive as the
# viral hook); the full Opportunity Map is private (loaded from src/private/).
_PUBLIC_SECTIONS: list[tuple[str, int, str]] = [
    _SECTION_PULSE,
    _SECTION_OPP_TEASER,
    _SECTION_STACK,
    _SECTION_DEEP,
]


def _public_only() -> bool:
    """When DAILY_PUBLIC_ONLY is set, skip private sections entirely — used to
    generate a clean public sample/archive with no private content to strip."""
    import os
    return os.environ.get("DAILY_PUBLIC_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def _load_private_sections() -> list[tuple[str, int, str]]:
    """Load optional private section blocks from the gitignored src/private/.

    The Opportunity Map lives there. A public clone has no such module, so this
    returns [] and the briefing is produced without it — the secret never ships.
    """
    if _public_only():
        return []
    out: list[tuple[str, int, str]] = []
    try:
        from .private import opportunity  # type: ignore
        out.append((opportunity.SECTION_ID, opportunity.ORDER, opportunity.INSTRUCTIONS))
    except Exception as exc:  # noqa: BLE001 — absence is the normal public case
        log.debug("no private sections loaded (%s)", exc)
    return out


def private_section_ids() -> list[str]:
    """Section ids that must be stripped before publishing publicly."""
    return [sid for sid, _, _ in _load_private_sections()]


def private_sentinels() -> list[str]:
    """Phrases that must NEVER appear in the public copy. Used to strip private
    sections by heading (when the model omits markers) and to fail-closed if any
    private content survives. Always loads the declared sentinels (independent of
    DAILY_PUBLIC_ONLY) so the leak-check is defense-in-depth."""
    out: list[str] = []
    try:
        from .private import opportunity  # type: ignore
        out += list(getattr(opportunity, "PUBLIC_SENTINELS", []))
    except Exception:  # noqa: BLE001
        pass
    return out


def build_instructions() -> str:
    """Compose the full instruction block from public + private sections."""
    sections = sorted(_PUBLIC_SECTIONS + _load_private_sections(), key=lambda s: s[1])
    body = "\n\n".join(block for _, _, block in sections)
    return (
        _INSTRUCTIONS_HEADER.format(n=len(sections))
        + "\n\n" + body
        + "\n\n" + _INSTRUCTIONS_FOOTER
    )


# Per-source caps keep one chatty feed from dominating the prompt. Tuned so
# the full briefing fits ~10K input tokens with all feeds healthy.
_PER_SOURCE_CAP = {
    "lab": 3,
    "newsletter": 2,
    "infra": 2,
    "community": 4,
    "research": 5,
}
# Global ceiling on items handed to the model — keeps the prompt bounded even
# if every feed comes back full.
_TOTAL_ITEM_CAP = 80


def _select_for_prompt(items: list[Item]) -> list[Item]:
    """Rank + cap items so the prompt is signal-dense, not exhaustive.

    Strategy: rank (HF papers by community upvotes, everything else by recency),
    keep the top N per source, then truncate to a global cap. The fetch layer
    stays exhaustive; selection happens here.
    """
    from .fetchers import _hf_upvotes

    def rank_key(it: Item) -> float:
        # HF Daily Papers carry an upvote signal — let "must-read" beat "newest".
        # Each upvote is worth ~half a day of recency so a highly-upvoted paper
        # from yesterday outranks a zero-vote one from today.
        ts = it.published.timestamp() if it.published else 0.0
        upvote_boost = _hf_upvotes(it) * 43200 if it.source == "HF Daily Papers" else 0
        return -(ts + upvote_boost)

    ordered = sorted(items, key=rank_key)
    per_source: dict[str, int] = {}
    selected: list[Item] = []
    for it in ordered:
        cap = _PER_SOURCE_CAP.get(it.category, 3)
        seen = per_source.get(it.source, 0)
        if seen >= cap:
            continue
        per_source[it.source] = seen + 1
        selected.append(it)
        if len(selected) >= _TOTAL_ITEM_CAP:
            break
    return selected


def select_for_prompt(items: list[Item]) -> list[Item]:
    """Public wrapper — main.py uses it to mark exactly the items the model saw
    as 'covered' in the cross-day dedup state."""
    return _select_for_prompt(items)


def _format_items(items: list[Item]) -> str:
    by_cat: dict[str, list[Item]] = {
        "lab": [], "newsletter": [], "infra": [], "community": [], "research": [],
    }
    for it in items:
        by_cat.setdefault(it.category, []).append(it)

    labels = {
        "lab": "FRONTIER LABS / TECH GIANTS",
        "newsletter": "NEWSLETTERS (AI engineer + research focused)",
        "infra": "AI INFRA / TOOLING VENDORS",
        "community": "COMMUNITY (Reddit / HN — where releases break first)",
        "research": "RESEARCH PAPERS (arXiv + HF Daily Papers; ▲ = community upvotes = must-read signal)",
    }
    blocks: list[str] = []
    for cat in ("lab", "newsletter", "infra", "community", "research"):
        group = by_cat.get(cat) or []
        if not group:
            continue
        lines = [f"### {labels[cat]} ({len(group)})"]
        for it in group:
            date = it.published.strftime("%Y-%m-%d") if it.published else "n/a"
            authors = f" — {', '.join(it.authors[:2])}" if it.authors else ""
            lines.append(
                f"- [{it.source} | {date}] {it.title}{authors}\n"
                f"  {it.url}\n"
                f"  {it.summary[:240]}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no items fetched deterministically)"


_RECEIPT_RX = re.compile(r"-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+—\s+\[([^\]]+)\]")


def recent_opportunity_titles(archive_dir: str, days: int, now: datetime) -> list[str]:
    """Opportunity-of-the-Day titles logged in <archive_dir>/receipts.md within
    the last `days`, newest first and de-duplicated. This is the agent's memory
    of what it has already proposed, so it stops re-pitching the same idea.
    Fail-open: a missing/unreadable receipts file returns []."""
    import os

    path = os.path.join(archive_dir, "receipts.md")
    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return []
    cutoff = now.date().toordinal() - max(0, days)
    dated: list[tuple[str, str]] = []
    for m in _RECEIPT_RX.finditer(content):
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d.toordinal() >= cutoff:
            dated.append((m.group(1), m.group(2).strip()))
    dated.sort(key=lambda t: t[0], reverse=True)
    seen: set[str] = set()
    titles: list[str] = []
    for _, t in dated:
        key = t.lower()
        if t and key not in seen:
            seen.add(key)
            titles.append(t)
    return titles


def _opportunity_memory_block(cfg: Config, now: datetime) -> str:
    """A prompt block listing recently-proposed opportunities, so the model
    doesn't repeat itself. Empty when memory is off or there's no history."""
    if not getattr(cfg, "opportunity_memory", False):
        return ""
    titles = recent_opportunity_titles(cfg.archive_dir, cfg.opportunity_memory_days, now)
    if not titles:
        return ""
    joined = "\n".join(f"- {t}" for t in titles[:40])
    log.info("opportunity memory: %d prior pick(s) fed into the prompt", len(titles))
    return (
        f"ALREADY PROPOSED — opportunities this agent has published in the last "
        f"{cfg.opportunity_memory_days} days. Do NOT re-propose these. Choose a "
        f"genuinely different opportunity; if you revisit a theme, state explicitly "
        f"what is newly different and why it is not a rerun:\n{joined}\n\n"
    )


def build_digest(cfg: Config, items: list[Item], now: datetime) -> str:
    """Build the prompt, run the configured provider, return the HTML fragment."""
    selected = _select_for_prompt(items)
    log.info(
        "selected %d/%d items for prompt (per-source + global cap)",
        len(selected), len(items),
    )
    targets = "\n".join(f"- {t}" for t in WEB_SEARCH_TARGETS)
    user_content = (
        f"Date: {now.strftime('%A, %B %d, %Y')} (UTC).\n"
        f"Consider developments from roughly the last {cfg.lookback_days} days.\n\n"
        f"CANDIDATE ITEMS (fetched from RSS + arXiv — pre-ranked by recency, "
        f"capped per source):\n\n"
        f"{_format_items(selected)}\n\n"
        f"SOURCES TO VERIFY / BACKFILL VIA WEB SEARCH (pull anything important "
        f"these published recently that's missing above):\n{targets}\n\n"
        f"{_opportunity_memory_block(cfg, now)}"
        f"{build_instructions()}"
    )
    log.info(
        "prompt size: ~%d chars (~%d tokens est.)",
        len(user_content), len(user_content) // 4,
    )

    log.info("generating digest via %s (%s)", cfg.provider, cfg.model)
    raw = providers.generate(cfg, SYSTEM_PROMPT, user_content)
    html = _strip_code_fence(raw)
    if not html:
        raise RuntimeError("provider produced an empty digest")

    # Guarantee clickable sources: the model is unreliable about emitting <a>
    # links, so deterministically hyperlink any fetched item it names back to the
    # item's real URL. This makes every candidate-sourced claim verifiable.
    html, added = _backfill_links(html, selected)
    log.info("digest generated: %d chars (+%d source links backfilled)", len(html), added)

    # Optional second pass: re-synthesize the Opportunity sections with a
    # stronger model (OPPORTUNITY_MODEL). Unset = single pass, as before.
    if cfg.opportunity_model and cfg.opportunity_model != cfg.model:
        html = _regenerate_opportunities(cfg, html, selected, now)

    html = postprocess(html)

    # Optional deterministic Top Stories strip (off by default — it duplicated
    # The Pulse). When enabled it renders BELOW The Pulse so the pyramid still
    # opens with the 90-second summary.
    if cfg.enable_top_stories:
        from . import enrich
        top = enrich.build_top_stories(
            selected, now, cfg.top_stories_count, cfg.enable_images
        )
        if top:
            html = _insert_after_section(html, "pulse", top)
    return html


def _opportunity_section_ids() -> list[str]:
    """Sections the (optional) stronger OPPORTUNITY_MODEL re-synthesizes: the
    public Opportunity of the Day plus any private opportunity sections."""
    return ["opp_teaser", *private_section_ids()]


def _regenerate_opportunities(
    cfg: Config, html: str, items: list[Item], now: datetime
) -> str:
    """Two-pass synthesis: redo just the Opportunity sections with a stronger
    model, splicing the result back over the first-pass sections by marker.
    Fail-open — any error keeps the first-pass content."""
    from dataclasses import replace

    ids = [sid for sid in _opportunity_section_ids() if f"<!--SECTION:{sid}-->" in html]
    if not ids:
        log.warning("opportunity 2nd pass skipped: no opportunity section markers found")
        return html

    blocks = {
        sid: block
        for sid, order, block in sorted(
            _PUBLIC_SECTIONS + _load_private_sections(), key=lambda s: s[1]
        )
        if sid in ids
    }
    instructions = (
        _INSTRUCTIONS_HEADER.format(n=len(blocks))
        + "\n\n" + "\n\n".join(blocks.values())
        + "\n\nOutput ONLY these sections (marker + <h2> + content each), nothing "
        "else. No markdown code fences, no commentary before or after."
    )
    context = (
        f"Date: {now.strftime('%A, %B %d, %Y')} (UTC).\n"
        f"You are re-synthesizing ONLY the opportunity section(s) of today's "
        f"briefing with a stronger model. The rest of the briefing (already "
        f"final) is below for context — do NOT repeat its items verbatim; "
        f"build on them.\n\n"
        f"TODAY'S BRIEFING (final, for context):\n{html}\n\n"
        f"CANDIDATE ITEMS:\n\n{_format_items(items)}\n\n"
        f"{_opportunity_memory_block(cfg, now)}"
        f"{instructions}"
    )
    try:
        strong_cfg = replace(cfg, model=cfg.opportunity_model)
        log.info("opportunity 2nd pass via %s (%s)", cfg.provider, cfg.opportunity_model)
        raw = _strip_code_fence(providers.generate(strong_cfg, SYSTEM_PROMPT, context))
        raw, _ = _backfill_links(raw, items)
        replaced = 0
        for sid in ids:
            new_block = _extract_section(raw, sid)
            if new_block:
                html = _replace_section(html, sid, new_block)
                replaced += 1
        log.info("opportunity 2nd pass: replaced %d/%d section(s)", replaced, len(ids))
    except Exception as exc:  # noqa: BLE001 — keep the first-pass digest
        log.warning("opportunity 2nd pass failed; keeping first pass: %s", exc)
    return html


def _section_rx(sid: str) -> re.Pattern:
    return re.compile(
        r"<!--SECTION:" + re.escape(sid) + r"-->.*?(?=\s*<!--SECTION:|\Z)",
        flags=re.DOTALL,
    )


def _extract_section(html: str, sid: str) -> str:
    m = _section_rx(sid).search(html)
    return m.group(0).strip() if m else ""


def _replace_section(html: str, sid: str, new_block: str) -> str:
    return _section_rx(sid).sub(lambda _: new_block + "\n", html, count=1)


def _insert_after_section(html: str, sid: str, block: str) -> str:
    """Insert `block` right after section `sid` ends (or append if not found)."""
    m = _section_rx(sid).search(html)
    if not m:
        return html + "\n" + block
    end = m.end()
    return html[:end] + "\n" + block + "\n" + html[end:]


# ── Deterministic output hygiene (runs on every digest) ───────────────────────

# A trailing anchor that just restates the previous link: same href, generic
# label ("source", "link", "[source]", "read more", a bare domain, "→", …),
# separated only by whitespace/punctuation. The prompt forbids these; this pass
# guarantees it.
_REDUNDANT_SRC_RX = re.compile(
    r'(<a\b[^>]*\bhref="([^"]+)"[^>]*>(?:(?!</a>).)*?</a>)'   # the real link
    r'((?:(?!<a\b|</li>|</p>|<h\d).)*?)'                       # prose, no other anchor
    r'[\s—–·,]*[\(\[]?\s*'                                     # separator / bracket
    r'<a\b[^>]*\bhref="\2"[^>]*>\s*'                           # same-href anchor
    r'(?:source|link|read more|details|→|↗|[a-z0-9.-]+\.[a-z]{2,})'
    r'\s*</a>\s*[\)\]]?',
    flags=re.IGNORECASE | re.DOTALL,
)


def strip_redundant_source_links(html: str) -> str:
    """Drop a trailing "source"-style link whose href equals the preceding
    inline link's href (the title is already hyperlinked)."""
    prev = None
    while prev != html:
        prev = html
        html = _REDUNDANT_SRC_RX.sub(r"\1\3", html)
    return html


def normalize_arxiv_links(html: str) -> str:
    """arXiv serves http:// URLs in its API; emails must not mix schemes."""
    return re.sub(
        r'http://(export\.)?arxiv\.org', r"https://\1arxiv.org", html
    )


def postprocess(html: str) -> str:
    """Deterministic hygiene passes applied to every generated digest."""
    html = normalize_arxiv_links(html)
    html = strip_redundant_source_links(html)
    return html


# Distinctive low-value tokens we won't treat as a linkable "phrase" on their own.
_GENERIC_TITLE_WORDS = {
    "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on",
    "ai", "llm", "llms", "model", "models", "new", "paper", "study", "report",
}


def _backfill_links(html: str, items: list[Item]) -> tuple[str, int]:
    """Hyperlink the first unlinked mention of each fetched item's title (or its
    pre-colon head) to the item's URL — without touching existing <a> elements or
    tag internals. Returns (html, links_added)."""
    pairs: list[tuple[str, str]] = []
    for it in items:
        title = (it.title or "").strip()
        if not it.url or len(title) < 6:
            continue
        pairs.append((title, it.url))
        head = title.split(":")[0].strip()
        # Only use the head if it's specific enough (multi-word or a distinctive
        # single token like "Code2LoRA" / "MemDreamer").
        if 6 <= len(head) < len(title):
            if " " in head or head.lower() not in _GENERIC_TITLE_WORDS:
                pairs.append((head, it.url))
    # Prefer the most specific (longest) phrases first.
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    # URLs already present in the output need no backfill.
    linked: set[str] = {u for _, u in pairs if u in html}

    # Tokenise into tags vs text so we never edit inside a tag or an <a> element.
    parts = re.split(r"(<[^>]+>)", html)
    inside_a = 0
    added = 0
    for i, tok in enumerate(parts):
        if tok.startswith("<") and tok.endswith(">"):
            low = tok.lower()
            if low.startswith("<a") and not low.startswith("<area"):
                inside_a += 1
            elif low.startswith("</a"):
                inside_a = max(0, inside_a - 1)
            continue
        if inside_a or not tok:
            continue
        seg = tok
        for phrase, url in pairs:
            if url in linked:
                continue
            idx = seg.find(phrase)
            if idx == -1:
                continue
            seg = f'{seg[:idx]}<a href="{url}">{phrase}</a>{seg[idx + len(phrase):]}'
            linked.add(url)
            added += 1
        parts[i] = seg
    return "".join(parts), added


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ```html fence if the model added one."""
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t.strip()
