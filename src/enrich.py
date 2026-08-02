"""Deterministic enrichment: priority ranking + article images + a Top Stories
section that does NOT depend on the model.

This is the reliability layer. Whatever the LLM does (or fails to do), we always
produce a "Top Stories" strip built straight from the fetched candidate items —
with real source links, og:image thumbnails, and a defensible priority order —
so every digest has clickable, image-rich, sensibly-ranked sources even on a weak
local model with no web grounding.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests

from .fetchers import Item, USER_AGENT, _hf_upvotes

log = logging.getLogger("aigenos.enrich")

# Source authority (named publishers beat generic category weight).
_AUTHORITY = {
    "OpenAI": 95, "Anthropic": 95, "Google DeepMind": 92, "Meta AI": 90,
    "Mistral": 85, "Hugging Face": 85, "Google AI (The Keyword)": 78,
    "Microsoft Research": 75, "NVIDIA Developer": 75, "Microsoft AI Blog": 70,
    "Cohere": 70, "Together AI": 66, "AWS ML Blog": 62, "LangChain": 60,
    # Top AI newsletters: high-detail coverage of the major players. Below the
    # frontier labs (their stories are secondary coverage) but well above the
    # generic newsletter base so their key articles reliably make the cut.
    "SemiAnalysis": 84, "Import AI": 82, "The Rundown AI": 80,
    "Latent Space": 80, "Interconnects (Lambert)": 80, "The Neuron": 78,
    "Simon Willison": 78, "Ahead of AI (Raschka)": 76, "Ben's Bites": 74,
    "AlphaSignal": 74, "The Sequence": 72, "Superhuman AI": 72, "TLDR AI": 70,
}
_CATEGORY_BASE = {
    "lab": 68, "research": 60, "newsletter": 55, "infra": 52, "community": 46,
}

# Down-weight corporate / PR items the reader called out as low-signal.
_BIZ_RE = re.compile(
    r"\b(S-1|IPO|SEC|fil(?:ed|ing)|funding|raises?|raised|valuation|round|"
    r"partnership|hires?|hiring|appoints?|acquir\w*|merger|lawsuit|board|"
    r"\$\d+\s?(?:million|billion|m|b)\b)",
    re.IGNORECASE,
)
# Up-weight capability / builder-relevant signal.
_CAPABILITY_RE = re.compile(
    r"\b(release[sd]?|launch\w*|open[- ]?source|open[- ]?weights?|model|"
    r"benchmark|SOTA|state[- ]of[- ]the[- ]art|outperform\w*|inference|"
    r"training|fine[- ]?tun\w*|quantiz\w*|context window|agent\w*|reasoning|"
    r"RAG|retrieval|throughput|latency|tokens?/s)\b",
    re.IGNORECASE,
)
# Extra boost for the agentic-architect signal that news-buzz ranking misses:
# new standards / specs / protocols / formats and enterprise agent-platform
# building blocks (the Open Knowledge Format class of story).
_STANDARDS_RE = re.compile(
    r"\b(standard\w*|spec(?:ification)?s?|protocol\w*|interoperab\w*|schema\w*|"
    r"open [a-z]+ format|knowledge format|MCP\b|model context protocol|"
    r"agent2agent|A2A\b|agents\.json|llms\.txt|reference architecture\w*|"
    r"orchestrat\w*|agent framework\w*|governance|ISO/IEC|NIST|"
    r"enterprise[- ](?:grade|agents?|AI|platform\w*))\b",
    re.IGNORECASE,
)


def priority_score(item: Item, now: datetime) -> float:
    """Rank by builder-relevance, not by who has the biggest PR team."""
    score = float(_AUTHORITY.get(item.source, _CATEGORY_BASE.get(item.category, 45)))

    # Recency: today >> last week.
    age = item.age_days(now)
    score += max(0.0, 25.0 - age * 4.0)

    # Research community signal.
    score += min(70.0, float(_hf_upvotes(item)))

    # Capability vs corporate-news nudges (the reader's ordering complaint).
    text = f"{item.title} {item.summary[:200]}"
    if _CAPABILITY_RE.search(text):
        score += 18.0
    # Standards / specs / protocols / enterprise-agent building blocks rarely
    # generate buzz but are exactly what an agentic architect must not miss —
    # boost them past ordinary news.
    if _STANDARDS_RE.search(text):
        score += 26.0
    if _BIZ_RE.search(text):
        score -= 32.0

    return score


def rank_by_priority(items: list[Item], now: datetime) -> list[Item]:
    return sorted(items, key=lambda it: priority_score(it, now), reverse=True)


_OG_RE = (
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', re.I),
)


def fetch_og_image(url: str, timeout: int = 8) -> str | None:
    """Best-effort: pull a page's og:image (the article's hero thumbnail).
    Returns None on any failure — never raises."""
    try:
        r = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout,
            stream=True, allow_redirects=True,
        )
        if r.status_code >= 300 or "html" not in r.headers.get("content-type", "").lower():
            return None
        raw = r.raw.read(200_000, decode_content=True) or b""
        head = raw.decode("utf-8", "ignore")
    except (requests.RequestException, ValueError, OSError):
        return None
    finally:
        try:
            r.close()  # type: ignore
        except Exception:
            pass
    for rx in _OG_RE:
        m = rx.search(head)
        if m:
            img = m.group(1).strip()
            if img.startswith("//"):
                img = "https:" + img
            if img.startswith("http"):
                return img
    return None


def _favicon(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except (ValueError, AttributeError):
        return ""


def select_top_stories(items: list[Item], now: datetime, count: int) -> list[Item]:
    """The top `count` items by builder-relevance — the featured set. Returned
    separately from rendering so the synthesis prompt can be told which items are
    featured (and avoid repeating them in The Pulse)."""
    return rank_by_priority(items, now)[:count]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _clean_summary(it: Item, max_sentences: int = 2, max_chars: int = 230) -> str:
    """A short, clean 1–2 sentence blurb for a top-story card. Strips the HF
    upvote prefix and trims to a sentence boundary."""
    text = re.sub(r"^\[\d+▲[^\]]*\]\s*", "", it.summary or "").strip()
    if not text:
        return ""
    sentences = _SENT_SPLIT.split(text)
    out = " ".join(sentences[:max_sentences]).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out


def render_top_stories(
    items: list[Item], now: datetime, with_images: bool
) -> str:
    """Render the image-rich Top Stories hero: the day's biggest stories as cards
    with a full-width article image (og:image, falling back to a favicon tile),
    a linked headline, source·date, and a 1–2 sentence summary.
    Marked <!--SECTION:topstories--> and public (kept in the archive)."""
    if not items:
        return ""

    cards: list[str] = []
    img_hits = 0
    for it in items:
        dom = _domain(it.url) or "news"
        thumb = fetch_og_image(it.url) if with_images else None
        if thumb:
            img_hits += 1
        date = it.published.strftime("%b %d") if it.published else ""
        blurb = _clean_summary(it)
        # Full-width article image when we have one; otherwise skip the image band
        # (a thin favicon tile would look broken at full width).
        image_band = ""
        if thumb:
            # Larger, magazine-style photo with a source caption strip beneath it.
            image_band = (
                f'<a href="{it.url}"><img src="{thumb}" alt="" width="100%" '
                'style="width:100%;max-height:260px;object-fit:cover;border-radius:16px 16px 0 0;'
                'border:0;display:block;"></a>'
                f'<div class="aigenos-src-cap" style="padding:6px 18px 0;font-size:11px;'
                f'color:#9a9aa8;font-style:italic;">Photo: {_esc(it.source)}</div>'
            )
        pad = "12px 18px 16px" if thumb else "16px 18px"
        blurb_html = (
            f'<div class="aigenos-src-blurb" style="margin-top:7px;font-size:14px;'
            f'color:#3a3a55;line-height:1.55;">{_esc(blurb)}</div>' if blurb else ""
        )
        cards.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'class="aigenos-src-row" style="margin:12px 0;border:1px solid #ece9fb;border-radius:16px;'
            'background:#ffffff;overflow:hidden;"><tr><td style="padding:0;">'
            f'{image_band}'
            f'<div style="padding:{pad};">'
            f'<a href="{it.url}" class="aigenos-src-title" style="color:#14142a;text-decoration:none;'
            f'font-weight:700;font-size:17px;line-height:1.3;letter-spacing:-0.01em;">{_esc(it.title)}</a>'
            f'<div class="aigenos-src-meta" style="margin-top:5px;font-size:12px;color:#8a8a9a;">'
            f'<img src="{_favicon(dom)}" width="13" height="13" alt="" style="vertical-align:middle;margin-right:5px;border-radius:3px;border:0;">'
            f'{_esc(it.source)}{" · " + date if date else ""}</div>'
            f'{blurb_html}'
            '</div></td></tr></table>'
        )

    log.info("top stories: %d item(s), %d og:image thumbnail(s)", len(items), img_hits)
    return (
        "<!--SECTION:topstories-->\n"
        '<h2>📌 Top Stories — Today\'s Biggest Moves (skim)</h2>\n'
        "<p>The day's highest-signal stories, ranked by builder-relevance — each "
        "linked to its primary source.</p>\n" + "\n".join(cards)
    )


def build_top_stories(
    items: list[Item], now: datetime, count: int, with_images: bool
) -> str:
    """Backward-compatible one-shot: select + render."""
    return render_top_stories(select_top_stories(items, now, count), now, with_images)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
