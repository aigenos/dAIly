"""Buttondown subscriber-delivery tests — all network mocked."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import notifiers
from src.config import Config
from src.notifiers import build_buttondown_body, html_to_markdown, send_buttondown

BODY = (
    "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2>"
    "<h3>🎯 Today's Game-Changer</h3>"
    '<p><strong><a href="https://x.com/m">MegaModel 9</a></strong> shipped.</p>\n'
    "<!--SECTION:opp_teaser-->\n<h2>🚀 Opportunity of the Day (2 min read)</h2>"
    "<h3>AgentLint</h3><ul><li><strong>The gap:</strong> nobody lints traces.</li></ul>\n"
    "<!--SECTION:opportunity_map-->\n<h2>🗺️ Full Opportunity Map (5 min read)</h2>"
    "<p>SECRET-MAP-CONTENT</p>\n"
    "<!--SECTION:stack-->\n<h2>📊 Stack Signals (3 min read)</h2><p>x</p>"
)
NOW = datetime(2026, 6, 12, tzinfo=timezone.utc)


def _cfg(**env):
    base = {
        "PROVIDER": "ollama",
        "DRY_RUN": "true",
        "SITE_URL": "https://me.github.io/dAIly",
        "BUTTONDOWN_API_KEY": "bd-key",
    }
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


class TestHtmlToMarkdown(unittest.TestCase):
    def test_links_headings_bullets_bold(self):
        md = html_to_markdown(
            '<h2>Title</h2><ul><li><strong>Bold:</strong> '
            '<a href="https://x.com">text</a></li></ul>'
        )
        self.assertIn("## Title", md)
        self.assertIn("- **Bold:** [text](https://x.com)", md)

    def test_html_comments_removed(self):
        self.assertNotIn("SECTION", html_to_markdown("<!--SECTION:pulse--><p>hi</p>"))


class TestBuildBody(unittest.TestCase):
    def test_teaser_mode_pulse_opp_and_link(self):
        cfg = _cfg()  # teaser is the default
        body = build_buttondown_body(cfg, BODY, NOW)
        self.assertIn("The Pulse", body)
        self.assertIn("AgentLint", body)
        self.assertNotIn("Stack Signals", body)  # teaser stays short
        self.assertIn(
            "[Read the full issue →](https://me.github.io/dAIly/digests/digest_20260612.html)",
            body,
        )

    def test_full_mode_includes_everything_public(self):
        cfg = _cfg(BUTTONDOWN_MODE="full")
        body = build_buttondown_body(cfg, BODY, NOW)
        self.assertIn("Stack Signals", body)


class TestSendButtondown(unittest.TestCase):
    def _send(self, cfg, **kwargs):
        with mock.patch.object(notifiers.requests, "post") as post:
            post.return_value = mock.Mock(status_code=201, text="ok")
            ok = send_buttondown(
                cfg, BODY, NOW,
                private_ids=["opportunity_map"],
                sentinels=kwargs.pop("sentinels", ["Full Opportunity Map"]),
            )
        return ok, post

    def test_sends_public_version_only(self):
        ok, post = self._send(_cfg())
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["status"], "about_to_send")
        self.assertIn("dAIly", payload["subject"])
        self.assertNotIn("SECRET-MAP-CONTENT", payload["body"])
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Token bd-key")

    def test_fail_closed_on_sentinel_leak(self):
        # A sentinel that survives stripping (not in a marker/heading section)
        # must abort the subscriber send entirely.
        with mock.patch.object(notifiers.requests, "post") as post:
            ok = send_buttondown(
                _cfg(), BODY, NOW, private_ids=[], sentinels=["SECRET-MAP-CONTENT"]
            )
        self.assertFalse(ok)
        post.assert_not_called()

    def test_noop_without_api_key(self):
        with mock.patch.object(notifiers.requests, "post") as post:
            ok = send_buttondown(_cfg(BUTTONDOWN_API_KEY=""), BODY, NOW)
        self.assertFalse(ok)
        post.assert_not_called()

    def test_api_error_fails_open(self):
        cfg = _cfg()
        with mock.patch.object(notifiers.requests, "post") as post:
            post.return_value = mock.Mock(status_code=403, text="nope")
            ok = send_buttondown(cfg, BODY, NOW)
        self.assertFalse(ok)  # logged + skipped, never raises


if __name__ == "__main__":
    unittest.main()
