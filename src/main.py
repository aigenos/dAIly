"""Entry point: fetch → synthesize → email the daily AI digest.

Run locally:  python -m src.main
In CI:        invoked by .github/workflows/daily-ai-digest.yml
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from . import archive, audio, linkcheck, notifiers, state
from .analyzer import (
    build_digest,
    private_section_ids,
    private_sentinels,
    select_for_prompt,
)
from .config import Config
from .emailer import footer_links, render_html, send_email, subject_line
from .fetchers import dedupe, fetch_all_feeds, fetch_arxiv, fetch_hf_papers

# Load .env for local runs. It's a dev convenience only — in CI the environment
# is provided by the workflow, so a missing python-dotenv must not be fatal.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aigenos")


def run() -> int:
    cfg = Config.from_env()
    now = datetime.now(timezone.utc)
    log.info("starting daily digest run (model=%s, lookback=%dd)", cfg.model, cfg.lookback_days)

    # 1. Fetch
    feed_items = fetch_all_feeds(cfg.lookback_days, now)
    arxiv_items = fetch_arxiv(cfg.lookback_days, now, cfg.arxiv_max_results)
    hf_items = fetch_hf_papers(cfg.lookback_days, now)
    items = dedupe([*feed_items, *arxiv_items, *hf_items])
    log.info(
        "fetched %d item(s) total (%d feed, %d arXiv, %d HF papers) after dedupe",
        len(items),
        len(feed_items),
        len(arxiv_items),
        len(hf_items),
    )

    # 1b. Cross-day dedup: drop items a previous digest already covered.
    # Fail-open — a missing/corrupt state file just means nothing is filtered.
    seen: dict[str, float] = {}
    if cfg.cross_day_dedup:
        seen = state.load(state.state_path(cfg.archive_dir))
        items = state.filter_new(items, seen)

    if not items and not cfg.enable_web_search:
        log.error("no items fetched and web search disabled — aborting")
        return 1

    # 2. Synthesize. `body` is the section-marked fragment (private sections
    # included); `html` is the full styled email.
    engine = f"{cfg.provider} ({cfg.model})"
    if cfg.opportunity_model:
        engine += f" + {cfg.opportunity_model}"
    body = build_digest(cfg, items, now)

    # 2b. Verify links before anything ships. Fail-open: network trouble only
    # means links go out unchecked, exactly as before.
    if cfg.enable_link_check:
        body = linkcheck.verify_links(body)

    html = render_html(
        body,
        now,
        engine=engine if cfg.show_model_attribution else "",
        footer=footer_links(cfg, now),
    )

    # Always save to disk in DRY_RUN so you can eyeball the result locally.
    if cfg.save_html or cfg.dry_run:
        out_path = f"digest_{now.strftime('%Y%m%d')}.html"
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(html)
            log.info("saved rendered digest to %s", out_path)
        except OSError as exc:
            log.warning("could not save html: %s", exc)

    # 3. Local artifacts — safe to produce even in DRY_RUN (just files).
    #    Archive publishes a PUBLIC copy with private sections stripped.
    if cfg.publish_archive:
        try:
            archive.publish(cfg, body, now, engine, private_section_ids(), private_sentinels())
        except Exception as exc:  # noqa: BLE001 — never let archiving kill the run
            log.warning("archive publish failed: %s", exc)
    if cfg.enable_audio:
        audio.generate(cfg, body, now)

    # 4. Deliver externally (skipped in DRY_RUN).
    if cfg.dry_run:
        log.info("DRY_RUN enabled — skipping email + channel posts. Open %s to review.", out_path)
        return 0
    send_email(cfg, subject_line(now), html)
    notifiers.notify_all(cfg, body, now, private_section_ids(), private_sentinels())

    # 5. Persist cross-day dedup state — only after a successful real delivery,
    # and only for the items the model actually saw (the prompt selection).
    if cfg.cross_day_dedup:
        state.mark_seen(select_for_prompt(items), seen, now)
        state.save(
            state.state_path(cfg.archive_dir), seen, now, cfg.lookback_days * 2
        )
    log.info("done.")
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("digest run failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
