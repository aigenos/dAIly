"""Tests for the digest output-quality fixes — no network, no API keys.

Covers: arXiv https normalization, redundant source-link stripping, the
one-item-one-section prompt rule, the two-pass OPPORTUNITY_MODEL flow, footer
links, dark-mode CSS (no var() in the dark block), and the private-section
guarantee (present in the email, stripped from the archive).
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import analyzer
from src.analyzer import (
    build_instructions,
    normalize_arxiv_links,
    postprocess,
    strip_redundant_source_links,
)
from src.archive import strip_private_sections
from src.config import Config
from src.emailer import _THEME_STYLES, footer_links, render_html


def _make_cfg(**env):
    base = {
        "PROVIDER": "ollama",
        "DRY_RUN": "true",
        "EMAIL_TO": "to@example.com",
    }
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


class TestArxivNormalization(unittest.TestCase):
    def test_http_arxiv_becomes_https(self):
        html = '<a href="http://arxiv.org/abs/2606.01234">Paper</a>'
        self.assertEqual(
            normalize_arxiv_links(html),
            '<a href="https://arxiv.org/abs/2606.01234">Paper</a>',
        )

    def test_export_subdomain_normalized(self):
        html = 'see http://export.arxiv.org/api/query'
        self.assertEqual(
            normalize_arxiv_links(html), "see https://export.arxiv.org/api/query"
        )

    def test_https_untouched(self):
        html = '<a href="https://arxiv.org/abs/1">x</a>'
        self.assertEqual(normalize_arxiv_links(html), html)


class TestRedundantSourceLinks(unittest.TestCase):
    def test_trailing_source_link_same_href_dropped(self):
        html = (
            '<li><a href="https://x.com/a">Title</a> — great stuff. '
            '<a href="https://x.com/a">source</a></li>'
        )
        out = strip_redundant_source_links(html)
        self.assertEqual(out.count("<a "), 1)
        self.assertIn(">Title</a>", out)

    def test_bracketed_source_link_dropped(self):
        html = '<a href="https://x.com/a">Title</a> [<a href="https://x.com/a">source</a>]'
        out = strip_redundant_source_links(html)
        self.assertEqual(out.count("<a "), 1)

    def test_different_href_kept(self):
        html = (
            '<a href="https://x.com/a">Title</a> '
            '<a href="https://y.com/b">source</a>'
        )
        out = strip_redundant_source_links(html)
        self.assertEqual(out.count("<a "), 2)

    def test_meaningful_second_link_kept(self):
        # Same href but a substantive label — not a redundant "source" suffix.
        html = (
            '<a href="https://x.com/a">Title</a> and '
            '<a href="https://x.com/a">the full benchmark table</a>'
        )
        out = strip_redundant_source_links(html)
        self.assertEqual(out.count("<a "), 2)

    def test_postprocess_combines_passes(self):
        html = (
            '<li><a href="http://arxiv.org/abs/1">P</a> '
            '<a href="http://arxiv.org/abs/1">source</a></li>'
        )
        out = postprocess(html)
        self.assertEqual(out.count("<a "), 1)
        self.assertIn("https://arxiv.org", out)
        self.assertNotIn("http://arxiv.org", out)


class TestPromptRules(unittest.TestCase):
    def test_one_item_one_section_rule_in_system_prompt(self):
        self.assertIn("ONE ITEM, ONE SECTION", analyzer.SYSTEM_PROMPT)

    def test_opportunity_requires_two_signals(self):
        instructions = build_instructions()
        self.assertIn("TWO INDEPENDENT signals", instructions)
        self.assertIn("QUANTIFY community interest", instructions)

    def test_link_hygiene_rule_in_instructions(self):
        self.assertIn("LINK HYGIENE", build_instructions())

    def test_importance_order_and_consolidation_rules(self):
        # Items must be ordered by AI-footprint impact with depth to match, and
        # multi-newsletter coverage of one story must merge into one entry.
        self.assertIn("IMPORTANCE ORDER", analyzer.SYSTEM_PROMPT)
        self.assertIn("CONSOLIDATE COVERAGE", analyzer.SYSTEM_PROMPT)

    def test_viral_x_threads_in_scope(self):
        self.assertIn("x.com", analyzer.SYSTEM_PROMPT)


class TestSourceCoverage(unittest.TestCase):
    def test_top_newsletters_present(self):
        from src import sources
        names = [f.name for f in sources.RSS_FEEDS]
        for name in ("The Rundown AI", "SemiAnalysis", "Simon Willison"):
            self.assertIn(name, names)

    def test_missing_feed_newsletters_covered_by_web_search(self):
        from src import sources
        targets = " ".join(sources.WEB_SEARCH_TARGETS)
        for needle in ("theneurondaily", "bensbites", "superhuman", "alphasignal", "x.com"):
            self.assertIn(needle, targets.lower())

    def test_newsletter_authority_ranks_above_base(self):
        from src.enrich import _AUTHORITY, _CATEGORY_BASE
        self.assertGreater(_AUTHORITY["The Rundown AI"], _CATEGORY_BASE["newsletter"])
        self.assertGreater(_AUTHORITY["The Neuron"], _CATEGORY_BASE["newsletter"])


class TestTwoPassOpportunity(unittest.TestCase):
    FIRST = (
        "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>News.</p>\n"
        "<!--SECTION:opp_teaser-->\n<h2>🚀 Opportunity of the Day (2 min read)</h2>"
        "<h3>WeakIdea</h3><p>meh</p>\n"
        "<!--SECTION:stack-->\n<h2>📊 Stack Signals (3 min read)</h2><p>x</p>"
    )
    SECOND = (
        "<!--SECTION:opp_teaser-->\n<h2>🚀 Opportunity of the Day (2 min read)</h2>"
        "<h3>StrongIdea</h3><p>much better</p>"
    )

    def _cfg(self, opportunity_model=""):
        return _make_cfg(OPPORTUNITY_MODEL=opportunity_model)

    def test_unset_opportunity_model_single_pass(self):
        cfg = self._cfg()
        with mock.patch.object(
            analyzer.providers, "generate", return_value=self.FIRST
        ) as gen:
            out = analyzer.build_digest(cfg, [], datetime(2026, 6, 10, tzinfo=timezone.utc))
        self.assertEqual(gen.call_count, 1)
        self.assertIn("WeakIdea", out)

    def test_opportunity_model_triggers_second_pass(self):
        cfg = self._cfg(opportunity_model="strong-model")
        with mock.patch.object(
            analyzer.providers, "generate", side_effect=[self.FIRST, self.SECOND]
        ) as gen:
            out = analyzer.build_digest(cfg, [], datetime(2026, 6, 10, tzinfo=timezone.utc))
        self.assertEqual(gen.call_count, 2)
        # Second pass ran with the stronger model.
        self.assertEqual(gen.call_args_list[1][0][0].model, "strong-model")
        self.assertIn("StrongIdea", out)
        self.assertNotIn("WeakIdea", out)
        # Non-opportunity sections untouched.
        self.assertIn("The Pulse", out)
        self.assertIn("Stack Signals", out)

    def test_second_pass_failure_keeps_first_pass(self):
        cfg = self._cfg(opportunity_model="strong-model")
        with mock.patch.object(
            analyzer.providers,
            "generate",
            side_effect=[self.FIRST, RuntimeError("boom")],
        ):
            out = analyzer.build_digest(cfg, [], datetime(2026, 6, 10, tzinfo=timezone.utc))
        self.assertIn("WeakIdea", out)


class TestSubscribeHandle(unittest.TestCase):
    """One variable wires every subscribe surface."""

    def test_handle_derives_url_form_and_unsubscribe(self):
        cfg = _make_cfg(SUBSCRIBE_HANDLE="daily-ai")
        self.assertEqual(cfg.subscribe_url, "https://buttondown.com/daily-ai")
        self.assertEqual(
            cfg.subscribe_form_action,
            "https://buttondown.com/api/emails/embed-subscribe/daily-ai",
        )
        self.assertEqual(cfg.unsubscribe_url, "{{ unsubscribe_url }}")

    def test_explicit_values_override_handle(self):
        cfg = _make_cfg(
            SUBSCRIBE_HANDLE="daily-ai",
            SUBSCRIBE_URL="https://custom.example/sub",
            UNSUBSCRIBE_URL="https://custom.example/unsub",
        )
        self.assertEqual(cfg.subscribe_url, "https://custom.example/sub")
        self.assertEqual(cfg.unsubscribe_url, "https://custom.example/unsub")
        # The form is still derived since it wasn't overridden.
        self.assertIn("embed-subscribe/daily-ai", cfg.subscribe_form_action)

    def test_no_handle_no_derivation(self):
        cfg = _make_cfg()
        self.assertEqual(cfg.subscribe_url, "")
        self.assertEqual(cfg.subscribe_form_action, "")
        self.assertEqual(cfg.unsubscribe_url, "")


class TestFooter(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 10, tzinfo=timezone.utc)

    def test_all_links_render(self):
        cfg = _make_cfg(
            SITE_URL="https://me.github.io/dAIly",
            SUBSCRIBE_URL="https://buttondown.com/me",
            UNSUBSCRIBE_URL="{{{RESEND_UNSUBSCRIBE_URL}}}",
        )
        row = footer_links(cfg, self.now)
        self.assertIn("digests/digest_20260610.html", row)
        self.assertIn("https://buttondown.com/me", row)
        self.assertIn("{{{RESEND_UNSUBSCRIBE_URL}}}", row)
        self.assertIn("Unsubscribe", row)

    def test_unsubscribe_excludable_for_archive(self):
        cfg = _make_cfg(
            SITE_URL="https://me.github.io/dAIly",
            UNSUBSCRIBE_URL="https://u.example.com",
        )
        row = footer_links(cfg, self.now, include_unsubscribe=False)
        self.assertNotIn("Unsubscribe", row)

    def test_subscribe_falls_back_to_site_anchor(self):
        # No SUBSCRIBE_URL configured, but SITE_URL is — Subscribe still shows,
        # pointing at the landing page's #subscribe box (good for forwards).
        cfg = _make_cfg(SITE_URL="https://me.github.io/dAIly")
        row = footer_links(cfg, self.now)
        self.assertIn("Subscribe", row)
        self.assertIn("https://me.github.io/dAIly#subscribe", row)

    def test_empty_when_nothing_configured(self):
        cfg = _make_cfg()
        self.assertEqual(footer_links(cfg, self.now), "")

    def test_attribution_toggle(self):
        with_engine = render_html("<p>x</p>", self.now, engine="gemini (flash)")
        without = render_html("<p>x</p>", self.now, engine="")
        self.assertIn("powered by gemini (flash)", with_engine)
        self.assertNotIn("powered by", without)

    def test_footer_is_clean(self):
        # No model name, no source/newsletter blurb in the default footer.
        html = render_html("<p>x</p>", self.now, engine="")
        self.assertNotIn("powered by", html)
        self.assertNotIn("frontier labs", html)
        self.assertNotIn("newsletter", html.lower())
        self.assertIn("dAIly", html)

    def test_show_model_attribution_env(self):
        # Off by default (clean footer); opt in explicitly.
        self.assertFalse(_make_cfg().show_model_attribution)
        self.assertTrue(_make_cfg(SHOW_MODEL_ATTRIBUTION="true").show_model_attribution)


class TestHeroBranding(unittest.TestCase):
    NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)

    def test_ai_is_emerald_italic_not_yellow(self):
        html = render_html("<p>x</p>", self.NOW)
        self.assertIn(
            'class="aigenos-ai" style="color:#6ee7b7;font-style:italic;">AI</span>', html
        )
        self.assertNotIn("#fcd34d", html)  # old yellow gone

    def test_emoji_fallback_without_logo_url(self):
        html = render_html("<p>x</p>", self.NOW)
        self.assertIn("🤖", html)

    def test_logo_url_replaces_emoji(self):
        html = render_html("<p>x</p>", self.NOW, logo_url="https://x/logo.png")
        self.assertIn('<img src="https://x/logo.png"', html)
        self.assertIn('alt="aigenos"', html)
        self.assertNotIn("🤖", html)

    def test_hero_uses_dark_logo_no_white_tile(self):
        # No hero image → CSS hero fallback with the dark (teal) logo only.
        html = render_html(
            "<p>x</p>", self.NOW,
            logo_url="https://x/light.png", logo_url_dark="https://x/dark.png",
        )
        self.assertIn("https://x/dark.png", html)
        self.assertNotIn("https://x/light.png", html)
        self.assertNotIn("aigenos-logo-l", html)  # swap removed

    def test_hero_image_used_when_available(self):
        html = render_html("<p>x</p>", self.NOW, hero_image_url="https://x/hero.png")
        # The masthead is a single invert-proof image — no CSS hero text.
        self.assertIn('<img src="https://x/hero.png"', html)
        self.assertIn('alt="dAIly — daily AI intelligence by aigenos"', html)
        # The CSS-hero markup (not the stylesheet rule) is absent.
        self.assertNotIn('class="aigenos-hero-mark"', html)

    def test_hero_image_derived_from_site_url(self):
        cfg = _make_cfg(SITE_URL="https://me.github.io/dAIly")
        self.assertEqual(
            cfg.hero_image_url, "https://me.github.io/dAIly/assets/hero-masthead.png"
        )

    def test_logo_urls_derived_from_site_url(self):
        cfg = _make_cfg(SITE_URL="https://me.github.io/dAIly")
        self.assertEqual(cfg.logo_url, "https://me.github.io/dAIly/assets/aigenos-logo-light.png")
        self.assertEqual(cfg.logo_url_dark, "https://me.github.io/dAIly/assets/aigenos-logo-dark.png")

    def test_explicit_logo_url_overrides_derivation(self):
        cfg = _make_cfg(SITE_URL="https://me.github.io/dAIly", LOGO_URL="https://cdn/x.png")
        self.assertEqual(cfg.logo_url, "https://cdn/x.png")


class TestNewsletterPolish(unittest.TestCase):
    NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)

    def test_intro_lede_section_in_instructions(self):
        from src.analyzer import build_instructions
        instr = build_instructions()
        self.assertIn("<!--SECTION:intro-->", instr)
        self.assertIn("In Brief", instr)

    def test_section_descriptors_injected(self):
        from src.analyzer import add_section_descriptors
        html = "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>x</p>"
        out = add_section_descriptors(html)
        self.assertIn('class="aigenos-desc"', out)
        self.assertIn("start here", out)

    def test_top_stories_render_after_intro(self):
        cfg = _make_cfg()
        body = (
            "<!--SECTION:intro-->\n<h2>👋 In Brief (30 sec read)</h2><p>hi</p>\n"
            "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>x</p>"
        )
        from src.fetchers import Item
        items = [Item("OpenAI", "lab", "Big", "https://x/a", self.NOW)]
        top = "<!--SECTION:topstories-->\n<h2>📌 Top Stories</h2><p>cards</p>"
        with mock.patch.object(analyzer.providers, "generate", return_value=body), \
             mock.patch("src.enrich.select_top_stories", return_value=items), \
             mock.patch("src.enrich.render_top_stories", return_value=top):
            out = analyzer.build_digest(cfg, items, self.NOW)
        self.assertLess(out.index("SECTION:intro"), out.index("SECTION:topstories"))
        self.assertLess(out.index("SECTION:topstories"), out.index("SECTION:pulse"))

    def test_feedback_block_mailto_default(self):
        # Feedback routes to the owner: FEEDBACK_EMAIL, else EMAIL_TO.
        from src.emailer import feedback_block
        fb = feedback_block(_make_cfg(), self.NOW)
        self.assertIn("😍", fb)
        self.assertIn("😕", fb)
        self.assertIn("mailto:to@example.com", fb)
        self.assertIn("aigenos", fb)  # sign-off

    def test_feedback_block_uses_feedback_email(self):
        from src.emailer import feedback_block
        fb = feedback_block(_make_cfg(FEEDBACK_EMAIL="hello@aigenos.dev"), self.NOW)
        self.assertIn("mailto:hello@aigenos.dev", fb)

    def test_feedback_block_uses_url(self):
        from src.emailer import feedback_block
        fb = feedback_block(_make_cfg(FEEDBACK_URL="https://forms.gle/x"), self.NOW)
        self.assertIn("https://forms.gle/x?r=loved", fb)

    def test_feedback_rendered_in_email(self):
        from src.emailer import feedback_block, render_html
        html = render_html("<p>x</p>", self.NOW, feedback=feedback_block(_make_cfg(), self.NOW))
        self.assertIn("How was today", html)


class TestDarkModeCss(unittest.TestCase):
    def test_no_var_in_dark_block(self):
        # Gmail/Outlook strip CSS custom properties: the dark-mode block must
        # use literal colors only.
        dark = _THEME_STYLES.split("@media (prefers-color-scheme: dark)")[1]
        dark = dark.split("@media", 1)[0]
        self.assertNotIn("var(", dark)
        self.assertIn("#0a0a14", dark)

    def test_color_scheme_meta_present(self):
        html = render_html("<p>x</p>", datetime(2026, 6, 10, tzinfo=timezone.utc))
        self.assertIn('<meta name="color-scheme" content="light dark">', html)


class TestPrivateSectionDelivery(unittest.TestCase):
    """The Full Opportunity Map must reach the EMAIL but never the ARCHIVE."""

    BODY = (
        "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>News.</p>\n"
        "<!--SECTION:opportunity_map-->\n<h2>🗺️ Full Opportunity Map (5 min read)</h2>"
        "<p>SECRET-BET-CONTENT</p>\n"
        "<!--SECTION:stack-->\n<h2>📊 Stack Signals (3 min read)</h2><p>x</p>"
    )

    def test_email_html_contains_private_content(self):
        html = render_html(self.BODY, datetime(2026, 6, 10, tzinfo=timezone.utc))
        self.assertIn("SECRET-BET-CONTENT", html)
        self.assertIn("<!--SECTION:opportunity_map-->", html)

    def test_archive_strips_private_content(self):
        public = strip_private_sections(self.BODY, ["opportunity_map"])
        self.assertNotIn("SECRET-BET-CONTENT", public)
        self.assertNotIn("Opportunity Map", public)
        self.assertIn("The Pulse", public)
        self.assertIn("Stack Signals", public)

    def test_private_module_included_in_prompt_and_ids(self):
        fake = [("opportunity_map", 25, "<!--SECTION:opportunity_map-->\n<h2>Map</h2>")]
        with mock.patch.object(analyzer, "_load_private_sections", return_value=fake):
            self.assertIn("opportunity_map", analyzer.private_section_ids())
            self.assertIn("<!--SECTION:opportunity_map-->", build_instructions())

    def test_public_clone_has_no_private_sections(self):
        # With no module under src/private/, the briefing simply omits them.
        self.assertEqual(
            [sid for sid in analyzer.private_section_ids() if sid != "opportunity"],
            analyzer.private_section_ids(),
        )


class TestTopStoriesPlacement(unittest.TestCase):
    NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)
    BODY = (
        "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>News.</p>\n"
        "<!--SECTION:stack-->\n<h2>📊 Stack Signals (3 min read)</h2><p>x</p>"
    )
    TOP = "<!--SECTION:topstories-->\n<h2>📌 Top Stories</h2><p>cards</p>"

    def _items(self):
        from src.fetchers import Item
        return [Item("OpenAI", "lab", "BigStory", "https://x.com/a", self.NOW)]

    def test_enabled_by_default(self):
        self.assertTrue(_make_cfg().enable_top_stories)

    def test_renders_at_the_very_top(self):
        cfg = _make_cfg()
        items = self._items()
        with mock.patch.object(analyzer.providers, "generate", return_value=self.BODY), \
             mock.patch("src.enrich.select_top_stories", return_value=items), \
             mock.patch("src.enrich.render_top_stories", return_value=self.TOP):
            out = analyzer.build_digest(cfg, items, self.NOW)
        self.assertLess(
            out.index("<!--SECTION:topstories-->"), out.index("<!--SECTION:pulse-->")
        )
        self.assertLess(
            out.index("<!--SECTION:pulse-->"), out.index("<!--SECTION:stack-->")
        )

    def test_disabled_when_off(self):
        cfg = _make_cfg(ENABLE_TOP_STORIES="false")
        with mock.patch.object(analyzer.providers, "generate", return_value=self.BODY):
            out = analyzer.build_digest(cfg, self._items(), self.NOW)
        self.assertNotIn("topstories", out)

    def test_featured_titles_injected_into_prompt(self):
        cfg = _make_cfg()
        items = self._items()
        captured = {}

        def fake_generate(c, system, user):
            captured["user"] = user
            return self.BODY

        with mock.patch.object(analyzer.providers, "generate", side_effect=fake_generate), \
             mock.patch("src.enrich.select_top_stories", return_value=items), \
             mock.patch("src.enrich.render_top_stories", return_value=self.TOP):
            analyzer.build_digest(cfg, items, self.NOW)
        self.assertIn("FEATURED AT THE TOP", captured["user"])
        self.assertIn("BigStory", captured["user"])


class TestTopStoriesRender(unittest.TestCase):
    NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)

    def _item(self, **kw):
        from src.fetchers import Item
        base = dict(source="OpenAI", category="lab", title="Big Title",
                    url="https://x.com/a", published=self.NOW, summary="A summary sentence.")
        base.update(kw)
        return Item(**base)

    def test_clean_summary_strips_hf_prefix_and_caps(self):
        from src import enrich
        it = self._item(summary="[1234▲ upvotes on HF] First sentence. Second one. Third one.")
        s = enrich._clean_summary(it)
        self.assertNotIn("▲", s)
        self.assertIn("First sentence.", s)
        self.assertNotIn("Third one.", s)  # capped at 2 sentences

    def test_select_caps_count(self):
        from src import enrich
        items = [self._item(url="https://x/1"), self._item(url="https://x/2", source="blog", category="community")]
        self.assertEqual(len(enrich.select_top_stories(items, self.NOW, 1)), 1)

    def test_render_without_images_is_offline(self):
        from src import enrich
        html = enrich.render_top_stories([self._item()], self.NOW, with_images=False)
        self.assertIn("<!--SECTION:topstories-->", html)
        self.assertIn("Top Stories", html)
        self.assertIn("Big Title", html)
        self.assertIn("A summary sentence", html)


if __name__ == "__main__":
    unittest.main()
