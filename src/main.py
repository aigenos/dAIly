"""Entry point: fetch → synthesize → email the daily AI digest.

Run locally:  python -m src.main
In CI:        invoked by .github/workflows/daily-ai-digest.yml
"""

from __future__ import annotations

import dataclasses
import logging
import sys
from datetime import datetime, timezone

from . import archive, audio, broadcast, linkcheck, notifiers, state
from .analyzer import (
    build_digest,
    private_section_ids,
    private_sentinels,
    select_for_prompt,
)
from .config import Config
from .emailer import (
    feedback_block,
    footer_links,
    list_report_block,
    listen_button,
    render_html,
    send_email,
    subject_line,
)
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

    # Brand the sender everywhere: once a domain is verified in Resend, the
    # owner copy upgrades from onboarding@resend.dev to daily@<domain> — the
    # same address the subscriber broadcast uses. Fail-open: any API hiccup
    # keeps the configured sender, so the owner email always goes out.
    if cfg.resend_api_key and not cfg.dry_run:
        try:
            sender = broadcast.resolve_sender(cfg)
            if sender and sender != cfg.email_from:
                cfg = dataclasses.replace(cfg, email_from=sender)
        except Exception as exc:  # noqa: BLE001 — cosmetic upgrade, never fatal
            log.debug("sender resolution skipped: %s", exc)

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

    # 2c. Audio episode (podcast mode) — generated BEFORE rendering so the
    # ▶️ Listen button can be injected into every copy. The MP3 lands in the
    # archive (docs/audio/) so GitHub Pages hosts it. Fail-open: no audio just
    # means no button, exactly as before.
    listen = ""
    if cfg.enable_audio:
        episode = audio.generate(cfg, body, now)
        if episode and episode.get("url"):
            listen = listen_button(episode["url"], episode.get("minutes", 0))

    # Daily subscriber report — a private list-health card (subscribers, new in
    # 24h, unsubscribes, total). Owner copy ONLY, injected via the cta slot so it
    # never reaches subscribers or the archive. Fail-open: any API hiccup just
    # omits the card. Skipped in DRY_RUN (no network).
    owner_report = ""
    if cfg.list_report_in_email and not cfg.dry_run and cfg.resend_api_key:
        try:
            stats = broadcast.audience_stats(cfg, now)
            if stats:
                owner_report = list_report_block(stats, now)
                log.info(
                    "list health: %d subscribers (+%d in 24h), %d unsubscribed",
                    stats["active"], stats["new_24h"], stats["unsubscribed"],
                )
        except Exception as exc:  # noqa: BLE001 — report is a nicety, never fatal
            log.debug("audience stats skipped: %s", exc)

    # Owner copy: the full issue (private sections included). No unsubscribe link
    # in the footer — that's for subscribers, and the Resend merge tag only
    # resolves inside a Broadcast, not a direct send.
    html = render_html(
        body,
        now,
        engine=engine if cfg.show_model_attribution else "",
        cta=owner_report,
        footer=footer_links(cfg, now, include_unsubscribe=False),
        logo_url=cfg.logo_url,
        logo_url_dark=cfg.logo_url_dark,
        hero_image_url=cfg.hero_image_url,
        feedback=feedback_block(cfg, now),
        prelude=listen,
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

    # 4. Deliver externally (skipped in DRY_RUN).
    if cfg.dry_run:
        log.info("DRY_RUN enabled — skipping email + channel posts. Open %s to review.", out_path)
        return 0
    send_email(cfg, subject_line(now), html)
    # Subscribers get the same styled issue via Resend Broadcasts (public version,
    # managed unsubscribe). Fail-open: the owner email above is the guaranteed
    # deliverable, so a Broadcast error never aborts the run. When Resend
    # delivered, notify_all skips the Buttondown send (no second copy); when it
    # didn't (e.g. domain not verified yet), Buttondown remains the fallback.
    delivered = broadcast.send_subscribers(
        cfg, body, now, private_section_ids(), private_sentinels(), prelude=listen
    )
    notifiers.notify_all(
        cfg, body, now, private_section_ids(), private_sentinels(),
        subscribers_delivered=delivered,
    )

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
