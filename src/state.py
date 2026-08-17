"""Cross-day dedup state: remember what previous digests already covered.

A lightweight JSON file (``<archive_dir>/.state/seen_items.json``) maps
URL/title hashes to the unix timestamp they were first covered, so an item
featured yesterday is dropped from today's candidate set. The workflow already
commits ``docs/`` back to the repo, so persistence is free.

FAIL-OPEN by design: a missing or corrupt state file means "nothing seen yet"
and a failed save is a warning — cross-day dedup must never kill the run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

from .fetchers import Item

log = logging.getLogger("aigenos.state")


def state_path(archive_dir: str) -> str:
    return os.path.join(archive_dir, ".state", "seen_items.json")


def _hash(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


def _keys(it: Item) -> list[str]:
    """Both a URL key and a normalized-title key, mirroring fetchers.dedupe —
    so a re-post of the same story under a new URL is still caught."""
    out: list[str] = []
    url = (it.url or "").rstrip("/").lower()
    if url:
        out.append(_hash("u", url))
    title = "".join(c for c in (it.title or "").lower() if c.isalnum())
    if title:
        out.append(_hash("t", title))
    return out


def load(path: str) -> dict[str, float]:
    """Load hash → first-seen timestamp. Any problem returns an empty state."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {
                str(k): float(v)
                for k, v in data.items()
                if isinstance(v, (int, float))
            }
        log.warning("cross-day state has unexpected shape — starting fresh")
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 — corrupt state must not kill the run
        log.warning("cross-day state unreadable (%s) — starting fresh", exc)
    return {}


def filter_new(items: list[Item], seen: dict[str, float]) -> list[Item]:
    """Drop items already covered by a previous digest."""
    if not seen:
        return items
    out: list[Item] = []
    dropped = 0
    for it in items:
        if any(k in seen for k in _keys(it)):
            dropped += 1
            continue
        out.append(it)
    if dropped:
        log.info("cross-day dedup: dropped %d item(s) covered in earlier digests", dropped)
    return out


def shown_in_digest(items: list[Item], body_html: str) -> list[Item]:
    """The subset of items that actually appear in the rendered digest.

    Marking ALL prompt candidates as covered burned ~80 items/day — including
    the majority the model never used — so the candidate pool shrank every run
    and coverage collapsed. Only what was genuinely shown may be excluded from
    future issues.

    Matching is two-tier:
    - URL, anchored to an href attribute (a bare substring test could match a
      prefix of a DIFFERENT url and wrongly ban an unshown story). The https://
      form is also checked — the digest normalizes http:// arXiv links.
    - Title fallback (≥4 words, case-insensitive) — the model sometimes links a
      story's canonical source instead of the candidate URL; without this the
      story would repeat in tomorrow's issue.
    """
    body_low = body_html.lower()
    out: list[Item] = []
    for it in items:
        url = (it.url or "").strip()
        alt = "https://" + url[len("http://"):] if url.startswith("http://") else url
        hit = any(
            f'href="{u}"' in body_html or f"href='{u}'" in body_html
            for u in {url, alt} if u
        )
        if not hit:
            title = (it.title or "").strip().lower()
            if len(title.split()) >= 4 and title in body_low:
                hit = True
        if hit:
            out.append(it)
    return out


def mark_seen(items: list[Item], seen: dict[str, float], now: datetime) -> None:
    """Record items as covered (call only after a successful, non-dry run)."""
    ts = now.timestamp()
    for it in items:
        for k in _keys(it):
            seen.setdefault(k, ts)


def save(path: str, seen: dict[str, float], now: datetime, keep_days: int) -> None:
    """Prune entries older than keep_days and write atomically. Fail-open."""
    cutoff = now.timestamp() - keep_days * 86_400
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(pruned, fh, separators=(",", ":"))
        os.replace(tmp, path)
        log.info("cross-day state saved: %d entry(ies) (%s)", len(pruned), path)
    except OSError as exc:
        log.warning("could not save cross-day state: %s", exc)
