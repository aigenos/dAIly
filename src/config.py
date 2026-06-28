"""Runtime configuration, resolved from environment variables.

The analysis provider is pluggable (Gemini or Claude), chosen via PROVIDER.
Only the API key for the selected provider is required.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VALID_PROVIDERS = {"gemini", "claude", "ollama"}

# Default model per provider when DIGEST_MODEL is not set.
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "claude": "claude-sonnet-4-6",
    "ollama": "llama3.1",
}


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    provider: str
    anthropic_api_key: str
    gemini_api_key: str
    resend_api_key: str
    ollama_host: str
    dry_run: bool
    email_to: str
    email_from: str
    model: str
    # Optional stronger model for the Opportunity sections (two-pass synthesis).
    # Blank = single pass with `model`, exactly the pre-existing behavior.
    opportunity_model: str
    # Self-memory: feed recent Opportunity titles (from receipts.md) into the
    # prompt so the agent doesn't re-propose its own past picks. Fail-open.
    opportunity_memory: bool
    opportunity_memory_days: int
    lookback_days: int
    enable_web_search: bool
    arxiv_max_results: int
    save_html: bool
    # Public archive (GitHub Pages). Private sections are stripped before publish.
    publish_archive: bool
    archive_dir: str
    site_title: str
    site_url: str
    # Hero masthead logo images (light + dark variants). Blank = 🤖 emoji
    # fallback. Derived from SITE_URL, or set LOGO_URL / LOGO_URL_DARK.
    logo_url: str
    logo_url_dark: str
    # Baked masthead image used as the hero (invert-proof in all mail clients).
    # Derived from SITE_URL, or set HERO_IMAGE_URL. Blank = CSS hero fallback.
    hero_image_url: str
    # One-click feedback widget target. A URL (gets ?r=loved|ok|meh appended) or
    # blank → a mailto to the sender address.
    feedback_url: str
    subscribe_url: str
    subscribe_form_action: str
    # Raw HTML form snippet (e.g. Buttondown/Beehiiv embed) injected wherever a
    # subscribe CTA renders. Takes precedence over the plain SUBSCRIBE_URL link.
    subscribe_embed_html: str
    # Unsubscribe link for the email footer. May be a URL or your sending
    # platform's merge tag (e.g. Resend's {{{RESEND_UNSUBSCRIBE_URL}}}).
    unsubscribe_url: str
    # Show the "powered by <provider> (<model>)" line in the email footer.
    show_model_attribution: bool
    # Multi-channel delivery (all optional; blank = disabled).
    slack_webhook_url: str
    discord_webhook_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    # Buttondown: send each issue to your newsletter subscribers (the public
    # version — private sections are stripped first). "teaser" sends The Pulse
    # + Opportunity as clean markdown with a link to the full issue (renders
    # reliably); "full" sends the whole public HTML fragment.
    buttondown_api_key: str
    buttondown_mode: str
    # Audio / TTS version of The Pulse.
    enable_audio: bool
    audio_dir: str
    # Deterministic "Top Stories" strip — real links + og:image thumbnails,
    # ranked by priority. Works on any provider (even link-less local models).
    enable_top_stories: bool
    enable_images: bool
    top_stories_count: int
    # Cross-day dedup: drop items already covered in a previous digest, tracked
    # in <archive_dir>/.state/seen_items.json. Fail-open if the file is broken.
    cross_day_dedup: bool
    # HEAD-check every link in the digest before sending/publishing and flag
    # dead ones. Fail-open: network trouble never aborts the run.
    enable_link_check: bool
    # Load the bundled paid "Builder's Edge" section (src/private/builders_edge.py)
    # when no truly-private src/private/opportunity.py exists. Goes to your email +
    # subscribers; always stripped from the public archive.
    enable_builders_edge: bool

    @classmethod
    def from_env(cls) -> "Config":
        provider = (os.environ.get("PROVIDER") or "").strip().lower() or "gemini"
        if provider not in VALID_PROVIDERS:
            raise SystemExit(
                f"Invalid PROVIDER={provider!r}. "
                f"Choose one of: {', '.join(sorted(VALID_PROVIDERS))}."
            )

        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        gemini_api_key = (
            os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        ).strip()
        resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
        dry_run = _get_bool("DRY_RUN", False)
        email_to = os.environ.get("EMAIL_TO", "").strip()

        # Only the selected provider's key is required (ollama needs none).
        missing = []
        if provider == "gemini" and not gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if provider == "claude" and not anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        # Resend + recipient are only needed when we actually send (not DRY_RUN).
        if not dry_run and not resend_api_key:
            missing.append("RESEND_API_KEY")
        if not dry_run and not email_to:
            missing.append("EMAIL_TO")
        if missing:
            raise SystemExit(
                "Missing required environment variable(s): "
                + ", ".join(missing)
                + f"\n(provider={provider}). See .env.example for setup details."
            )

        model = os.environ.get("DIGEST_MODEL", "").strip() or DEFAULT_MODELS[provider]
        opportunity_model = os.environ.get("OPPORTUNITY_MODEL", "").strip()

        # One-variable subscribe wiring. Set SUBSCRIBE_HANDLE to your Buttondown
        # username and the subscribe URL, the on-page signup form, and the
        # unsubscribe merge tag are all derived — so the landing page, README
        # target, newsletter footer, and subscriber delivery work together from a
        # single value. Any explicit SUBSCRIBE_URL / SUBSCRIBE_FORM_ACTION /
        # UNSUBSCRIBE_URL still overrides the derived default.
        site_url = os.environ.get("SITE_URL", "").strip().rstrip("/")
        # Two logo variants for the hero: light (navy mark, for the white tile in
        # light mode) and dark (teal mark, floats on the dark hero in dark mode).
        # Derived from SITE_URL; override with LOGO_URL / LOGO_URL_DARK.
        logo_url = os.environ.get("LOGO_URL", "").strip()
        logo_url_dark = os.environ.get("LOGO_URL_DARK", "").strip()
        hero_image_url = os.environ.get("HERO_IMAGE_URL", "").strip()
        if site_url:
            logo_url = logo_url or f"{site_url}/assets/aigenos-logo-light.png"
            logo_url_dark = logo_url_dark or f"{site_url}/assets/aigenos-logo-dark.png"
            hero_image_url = hero_image_url or f"{site_url}/assets/hero-masthead.png"

        handle = os.environ.get("SUBSCRIBE_HANDLE", "").strip().strip("/")
        subscribe_url = os.environ.get("SUBSCRIBE_URL", "").strip()
        subscribe_form_action = os.environ.get("SUBSCRIBE_FORM_ACTION", "").strip()
        unsubscribe_url = os.environ.get("UNSUBSCRIBE_URL", "").strip()
        if handle:
            subscribe_url = subscribe_url or f"https://buttondown.com/{handle}"
            subscribe_form_action = subscribe_form_action or (
                f"https://buttondown.com/api/emails/embed-subscribe/{handle}"
            )
            unsubscribe_url = unsubscribe_url or "{{ unsubscribe_url }}"

        return cls(
            provider=provider,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            resend_api_key=resend_api_key,
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip(),
            dry_run=dry_run,
            email_to=email_to,
            email_from=os.environ.get(
                "EMAIL_FROM", "AI Daily Digest <onboarding@resend.dev>"
            ).strip(),
            model=model,
            opportunity_model=opportunity_model,
            opportunity_memory=_get_bool("OPPORTUNITY_MEMORY", True),
            opportunity_memory_days=_get_int("OPPORTUNITY_MEMORY_DAYS", 60),
            lookback_days=_get_int("LOOKBACK_DAYS", 3),
            enable_web_search=_get_bool("ENABLE_WEB_SEARCH", True),
            arxiv_max_results=_get_int("ARXIV_MAX_RESULTS", 40),
            save_html=_get_bool("SAVE_HTML", True),
            publish_archive=_get_bool("PUBLISH_ARCHIVE", False),
            archive_dir=os.environ.get("ARCHIVE_DIR", "docs").strip() or "docs",
            site_title=os.environ.get("SITE_TITLE", "aigenos — Daily AI Digest").strip(),
            site_url=site_url,
            logo_url=logo_url,
            logo_url_dark=logo_url_dark,
            hero_image_url=hero_image_url,
            feedback_url=os.environ.get("FEEDBACK_URL", "").strip(),
            subscribe_url=subscribe_url,
            # POST endpoint for the landing-page subscribe form (e.g. Buttondown's
            # embed-subscribe URL). When set, the index renders a one-field form.
            subscribe_form_action=subscribe_form_action,
            subscribe_embed_html=os.environ.get("SUBSCRIBE_EMBED_HTML", "").strip(),
            unsubscribe_url=unsubscribe_url,
            show_model_attribution=_get_bool("SHOW_MODEL_ATTRIBUTION", False),
            buttondown_api_key=os.environ.get("BUTTONDOWN_API_KEY", "").strip(),
            buttondown_mode=(
                os.environ.get("BUTTONDOWN_MODE", "").strip().lower() or "html"
            ),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", "").strip(),
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
            enable_audio=_get_bool("ENABLE_AUDIO", False),
            audio_dir=os.environ.get("AUDIO_DIR", "out").strip() or "out",
            # Image-rich "Top Stories" hero (top 3–4 with article thumbnails +
            # a short summary), rendered at the very top. The synthesis prompt is
            # told which items are featured so The Pulse doesn't repeat them.
            enable_top_stories=_get_bool("ENABLE_TOP_STORIES", True),
            enable_images=_get_bool("ENABLE_IMAGES", True),
            top_stories_count=_get_int("TOP_STORIES_COUNT", 4),
            cross_day_dedup=_get_bool("CROSS_DAY_DEDUP", True),
            enable_link_check=_get_bool("ENABLE_LINK_CHECK", True),
            enable_builders_edge=_get_bool("ENABLE_BUILDERS_EDGE", False),
        )
