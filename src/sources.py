"""Source registry.

Two kinds of sources:

1. RSS/Atom feeds we fetch deterministically (structured, dated entries).
2. "Web targets" we don't have a reliable feed for — these are handed to the
   provider's web_search tool so it can pull the latest items itself.

RSS URLs change over time; a broken feed is skipped gracefully at fetch time and
the web-search layer is expected to backfill the gap.

FIELD PRESETS: set ``SOURCE_PRESET`` (e.g. ``security``, ``biotech``,
``fintech``) to swap the whole source pack for another field — see
``src/presets/``. The default (``ai``) is exactly the lists defined below.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    category: str  # "lab" | "newsletter" | "infra" | "community" | "research"


# RSS/Atom feeds — only sources that returned HTTP 200 in production runs.
# Anything that 404s or hides its feed is moved to WEB_SEARCH_TARGETS instead.
# Feeds returning 0 items in a window are KEPT (they're reachable, just quiet);
# only remove a feed here when its URL is confirmed dead.
RSS_FEEDS: list[Feed] = [
    # ── Frontier labs / tech giants (verified reachable) ─────────────────────
    Feed("OpenAI", "https://openai.com/news/rss.xml", "lab"),
    Feed("Google DeepMind", "https://deepmind.google/blog/rss.xml", "lab"),
    Feed("Google AI (The Keyword)", "https://blog.google/technology/ai/rss/", "lab"),
    Feed("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "lab"),
    Feed("Microsoft AI Blog", "https://blogs.microsoft.com/ai/feed/", "lab"),
    Feed("Hugging Face", "https://huggingface.co/blog/feed.xml", "lab"),
    Feed("Cohere", "https://cohere.com/blog/rss.xml", "lab"),
    # NOTE: Anthropic, Meta AI, Mistral, DeepSeek, xAI publish no public RSS;
    # they are covered in WEB_SEARCH_TARGETS below.

    # ── Newsletters (engineer + research focused; all verified reachable) ────
    Feed("Latent Space", "https://www.latent.space/feed", "newsletter"),
    Feed("Import AI", "https://importai.substack.com/feed", "newsletter"),
    Feed("Ahead of AI (Raschka)", "https://magazine.sebastianraschka.com/feed", "newsletter"),
    Feed("Interconnects (Lambert)", "https://www.interconnects.ai/feed", "newsletter"),
    Feed("TLDR AI", "https://tldr.tech/api/rss/ai", "newsletter"),
    Feed("Last Week in AI", "https://lastweekin.ai/feed", "newsletter"),
    Feed("Gradient Flow", "https://gradientflow.com/feed/", "newsletter"),
    Feed("The Rundown AI", "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml", "newsletter"),
    Feed("The Gradient", "https://thegradient.pub/rss/", "newsletter"),
    # NOTE: The Batch (DeepLearning.AI) and The Neuron 404 on their published
    # RSS URLs — covered via WEB_SEARCH_TARGETS instead.

    # ── AI infra / tooling vendors (verified reachable) ──────────────────────
    Feed("LangChain", "https://blog.langchain.dev/rss/", "infra"),
    Feed("Together AI", "https://www.together.ai/blog/rss.xml", "infra"),
    Feed("NVIDIA Developer", "https://developer.nvidia.com/blog/feed/", "infra"),
    Feed("AWS ML Blog", "https://aws.amazon.com/blogs/machine-learning/feed/", "infra"),
    # NOTE: LlamaIndex, Pinecone, Weaviate, Modal don't expose stable RSS —
    # covered via WEB_SEARCH_TARGETS.

    # ── Community / where releases break first (all verified reachable) ──────
    Feed("r/LocalLLaMA (top/day)", "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "community"),
    Feed("r/MachineLearning (top/day)", "https://www.reddit.com/r/MachineLearning/top/.rss?t=day", "community"),
    Feed("r/OpenAI (top/day)", "https://www.reddit.com/r/OpenAI/top/.rss?t=day", "community"),
    Feed("HN AI/LLM/agent (50+ pts)", "https://hnrss.org/newest?q=AI+OR+LLM+OR+agent&points=50", "community"),
]

# Sources the model should actively search/verify the web for. Plain-language so
# the model can reason about them. Used only when ENABLE_WEB_SEARCH is true.
WEB_SEARCH_TARGETS: list[str] = [
    # Frontier labs with no reliable public RSS — must be web-searched.
    "Anthropic news and research announcements (anthropic.com/news, anthropic.com/research)",
    "Meta AI (FAIR) announcements and model releases (ai.meta.com)",
    "Mistral AI model releases and announcements (mistral.ai/news)",
    "xAI (Grok) model releases and announcements",
    "DeepSeek releases and papers (DeepSeek-AI on GitHub and Hugging Face)",
    "Qwen / Alibaba model releases (QwenLM on GitHub, Hugging Face)",
    # Lab RSS feeds we DO fetch — backfill anything important they may have
    # buried below the feed window.
    "OpenAI announcements and research (openai.com/news, openai.com/research)",
    "Google DeepMind and Google AI announcements (deepmind.google, blog.google/technology/ai)",
    # Newsletters without reliable RSS — pull latest issues directly.
    "The Batch by DeepLearning.AI — latest issue (deeplearning.ai/the-batch)",
    "The Neuron daily newsletter — latest issue (theneurondaily.com)",
    # Infra / vector DB / serving stacks with flaky or absent RSS.
    "LlamaIndex blog and releases (llamaindex.ai/blog, github.com/run-llama)",
    "Pinecone blog and product updates (pinecone.io/blog)",
    "Weaviate releases and blog (weaviate.io/blog)",
    "Modal blog and product updates (modal.com/blog)",
    "vLLM, SGLang, llama.cpp project releases on GitHub",
    # Signal sources for benchmarks, repo velocity, and demand evidence.
    "LMSYS Chatbot Arena leaderboard moves and new model entries",
    "SWE-bench, GAIA, τ-bench, LiveCodeBench leaderboard updates",
    "GitHub trending repos in Python / AI for the last 24–72 hours",
    "Hugging Face trending models and Spaces for the last few days",
    "Y Combinator AI startup launches in the last week (ycombinator.com/launches)",
    "Product Hunt AI category top launches in the last few days",
    "AI funding rounds in the last 7 days (TechCrunch, The Information, Crunchbase)",
    # Policy / regulation / government actions that change what builders can ship.
    "Major AI policy, regulation, and government actions in the last week — model "
    "bans or restrictions, export controls, executive orders, antitrust moves, and "
    "landmark AI lawsuits (Reuters, Bloomberg, The Verge, official gov releases)",
]

# arXiv: categories + agentic-AI focused search terms.
ARXIV_CATEGORIES: list[str] = ["cs.AI", "cs.LG", "cs.CL", "cs.MA"]

ARXIV_QUERIES: list[str] = [
    'abs:"LLM agent" OR abs:"language model agent" OR abs:"agentic"',
    'abs:"multi-agent" AND (abs:"LLM" OR abs:"language model")',
    'abs:"tool use" AND abs:"language model"',
    'abs:"agent memory" OR abs:"long-horizon" OR abs:"planning" AND abs:"agent"',
    'abs:"retrieval augmented" OR abs:"RAG" AND abs:"agent"',
    'abs:"reasoning" AND (abs:"LLM" OR abs:"language model") AND abs:"benchmark"',
]

# ── Field presets ─────────────────────────────────────────────────────────────
# SOURCE_PRESET swaps the source pack for another field at import time. The
# preset module (src/presets/<name>.py) may override any of RSS_FEEDS,
# WEB_SEARCH_TARGETS, ARXIV_CATEGORIES, ARXIV_QUERIES; missing names keep the
# AI defaults above. Fail-open: an unknown preset logs a warning and keeps the
# defaults rather than killing the run. (This import sits at the bottom so the
# preset module can import `Feed` from here without a circular-import problem.)
_PRESET = os.environ.get("SOURCE_PRESET", "").strip().lower()
if _PRESET and _PRESET != "ai":
    try:
        import importlib

        _mod = importlib.import_module(f"{__package__}.presets.{_PRESET}")
        RSS_FEEDS = list(getattr(_mod, "RSS_FEEDS", RSS_FEEDS))
        WEB_SEARCH_TARGETS = list(getattr(_mod, "WEB_SEARCH_TARGETS", WEB_SEARCH_TARGETS))
        ARXIV_CATEGORIES = list(getattr(_mod, "ARXIV_CATEGORIES", ARXIV_CATEGORIES))
        ARXIV_QUERIES = list(getattr(_mod, "ARXIV_QUERIES", ARXIV_QUERIES))
        logging.getLogger("aigenos.sources").info(
            "source preset %r: %d feed(s), %d web target(s)",
            _PRESET, len(RSS_FEEDS), len(WEB_SEARCH_TARGETS),
        )
    except Exception as exc:  # noqa: BLE001 — bad preset must not kill the run
        logging.getLogger("aigenos.sources").warning(
            "SOURCE_PRESET=%r failed to load (%s) — using default 'ai' sources",
            _PRESET, exc,
        )
