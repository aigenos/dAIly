"""Audio version of the digest — the daily issue as a listenable episode.

Uses gTTS (Google Translate TTS): free, no API key, so a $0 clone still works.
The dependency is imported lazily and optional — if gTTS isn't installed or the
TTS call fails, audio is skipped with a warning rather than failing the run.

We voice the "commute cut": In Brief, The Pulse, and the Opportunity of the Day
— the standalone core of the issue (~3–6 minutes), not the link-heavy long tail.

When PUBLISH_ARCHIVE is on, the MP3 lands in <archive_dir>/audio/ so GitHub
Pages hosts it: the email links to it (▶️ Listen), the archive page embeds a
player, and archive.py publishes a podcast RSS feed of all episodes.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from .config import Config
from .notifiers import extract_section, html_to_text

log = logging.getLogger("aigenos.audio")

# Keep roughly this many episodes in the archive so the repo doesn't grow
# unboundedly (~2–4 MB per episode). Oldest are pruned at generation time.
KEEP_EPISODES = 30

# Speaking rate used to estimate the episode length shown on the button.
_WORDS_PER_MINUTE = 160


def _spoken_text(body_fragment: str) -> str:
    """Turn In Brief + The Pulse + Opportunity of the Day into clean prose for
    TTS (drop URLs — unspeakable)."""
    intro = extract_section(body_fragment, "intro")
    pulse = extract_section(body_fragment, "pulse")
    opp = extract_section(body_fragment, "opp_teaser")
    chunks = []
    if intro:
        chunks.append(html_to_text(intro, max_bullets=4))
    if pulse:
        chunks.append(html_to_text(pulse, max_bullets=12))
    if opp:
        chunks.append("And here's today's opportunity of the day. " + html_to_text(opp, max_bullets=8))
    text = "\n".join(chunks)
    # Strip the "(url)" parentheticals html_to_text leaves in — links don't read
    # aloud well.
    text = re.sub(r"\s*\(https?://[^)]+\)", "", text)
    text = re.sub(r"•\s*", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def estimate_minutes(text: str) -> int:
    """Whole-minute listen estimate for the ▶️ button (at ~160 wpm, min 1)."""
    words = len(text.split())
    return max(1, round(words / _WORDS_PER_MINUTE))


def audio_dir(cfg: Config) -> str:
    """Where episodes live: the published archive (so Pages serves them) when
    archiving is on, else the local AUDIO_DIR."""
    if getattr(cfg, "publish_archive", False):
        return os.path.join(cfg.archive_dir, "audio")
    return cfg.audio_dir


def episode_filename(now: datetime) -> str:
    return f"digest_{now.strftime('%Y%m%d')}.mp3"


def episode_url(cfg: Config, now: datetime) -> str:
    """Public URL of today's episode ('' when it can't be public)."""
    site = getattr(cfg, "site_url", "")
    if site and getattr(cfg, "publish_archive", False):
        return f"{site}/audio/{episode_filename(now)}"
    return ""


def _prune_old(directory: str) -> None:
    """Keep the newest KEEP_EPISODES mp3s; delete the rest. Fail-open."""
    try:
        mp3s = sorted(
            f for f in os.listdir(directory)
            if f.startswith("digest_") and f.endswith(".mp3")
        )
        for stale in mp3s[:-KEEP_EPISODES]:
            os.remove(os.path.join(directory, stale))
            log.info("pruned old episode %s", stale)
    except OSError as exc:
        log.debug("episode prune skipped: %s", exc)


def generate(cfg: Config, body_fragment: str, now: datetime) -> dict | None:
    """Write today's episode MP3. Returns {"path", "minutes", "url"} or None
    if skipped/failed (never raises)."""
    text = _spoken_text(body_fragment)
    if not text:
        log.warning("audio skipped: no Pulse text to voice")
        return None

    try:
        from gtts import gTTS  # lazy: optional dependency
    except ImportError:
        log.warning("audio skipped: gTTS not installed (`pip install gTTS`)")
        return None

    out_dir = audio_dir(cfg)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, episode_filename(now))
    try:
        intro = f"dAIly — your AI briefing for {now.strftime('%A, %B %d')}. "
        outro = " That's today's dAIly. The full issue, with every source linked, is in your inbox and on the archive."
        gTTS(text=intro + text + outro, lang="en", tld="com").save(out_path)
    except Exception as exc:  # noqa: BLE001 — network/TTS errors shouldn't kill the run
        log.warning("audio generation failed: %s", exc)
        return None

    _prune_old(out_dir)
    minutes = estimate_minutes(text)
    log.info("audio episode → %s (~%d min, %d chars voiced)", out_path, minutes, len(text))
    return {"path": out_path, "minutes": minutes, "url": episode_url(cfg, now)}
