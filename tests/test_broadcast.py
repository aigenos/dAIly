"""Resend Broadcast subscriber-delivery tests — all network mocked."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import broadcast
from src.broadcast import send_subscribers
from src.config import Config

BODY = (
    "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2>"
    "<h3>🎯 Today's Game-Changer</h3>"
    '<p><strong><a href="https://x.com/m">MegaModel 9</a></strong> shipped.</p>\n'
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
        "EMAIL_TO": "to@example.com",
        "RESEND_API_KEY": "re-key",
        "RESEND_AUDIENCE_ID": "aud_1",
    }
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


def _two_step_post():
    """A requests.post mock that returns create-then-send responses."""
    created = mock.Mock(status_code=201, text="ok")
    created.json.return_value = {"id": "bc_1"}
    sent = mock.Mock(status_code=200, text="ok")
    post = mock.Mock(side_effect=[created, sent])
    return post


class TestConfigDerivation(unittest.TestCase):
    def test_audience_derives_resend_unsubscribe_tag(self):
        self.assertEqual(_cfg().unsubscribe_url, "{{{RESEND_UNSUBSCRIBE_URL}}}")

    def test_reply_to_defaults_to_owner(self):
        self.assertEqual(_cfg().reply_to, "to@example.com")

    def test_feedback_email_override(self):
        cfg = _cfg(FEEDBACK_EMAIL="hello@aigenos.dev")
        self.assertEqual(cfg.feedback_email, "hello@aigenos.dev")
        self.assertEqual(cfg.reply_to, "hello@aigenos.dev")


class TestSendSubscribers(unittest.TestCase):
    def _send(self, cfg, **kwargs):
        post = _two_step_post()
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(
                cfg, BODY, NOW,
                private_ids=kwargs.pop("private_ids", ["opportunity_map"]),
                sentinels=kwargs.pop("sentinels", ["Full Opportunity Map"]),
            )
        return ok, post

    def test_creates_then_sends_public_identical_html(self):
        ok, post = self._send(_cfg())
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)

        create = post.call_args_list[0]
        self.assertEqual(create.args[0], broadcast.BROADCASTS_API)
        payload = create.kwargs["json"]
        self.assertEqual(payload["audience_id"], "aud_1")
        self.assertEqual(payload["reply_to"], "to@example.com")
        self.assertIn("dAIly", payload["subject"])
        # Same rich HTML the owner gets: full document + baked masthead hero.
        self.assertIn("<!DOCTYPE", payload["html"])
        self.assertIn("hero-masthead.png", payload["html"])
        # Public only — private section stripped before send.
        self.assertNotIn("SECRET-MAP-CONTENT", payload["html"])
        # Managed unsubscribe merge tag present for subscribers.
        self.assertIn("{{{RESEND_UNSUBSCRIBE_URL}}}", payload["html"])
        # Auth header uses the Resend key.
        self.assertEqual(create.kwargs["headers"]["Authorization"], "Bearer re-key")

        send = post.call_args_list[1]
        self.assertTrue(send.args[0].endswith("/bc_1/send"))

    def test_fail_closed_on_sentinel_leak(self):
        post = mock.Mock()
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(
                _cfg(), BODY, NOW, private_ids=[], sentinels=["SECRET-MAP-CONTENT"]
            )
        self.assertFalse(ok)
        post.assert_not_called()

    def test_noop_without_audience_id(self):
        post = mock.Mock()
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(_cfg(RESEND_AUDIENCE_ID=""), BODY, NOW)
        self.assertFalse(ok)
        post.assert_not_called()

    def test_create_error_fails_open(self):
        post = mock.Mock(return_value=mock.Mock(status_code=422, text="bad"))
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(_cfg(), BODY, NOW)
        self.assertFalse(ok)  # logged + skipped, never raises
        self.assertEqual(post.call_count, 1)  # never reached the send step


class TestSingleSubscriberChannel(unittest.TestCase):
    def test_buttondown_skipped_when_resend_audience_set(self):
        # Both configured -> only Resend delivers to subscribers; Buttondown must
        # NOT send a second, differently-rendered copy.
        from src import notifiers
        cfg = _cfg(BUTTONDOWN_API_KEY="bd-key")
        with mock.patch.object(notifiers, "send_buttondown") as bd:
            notifiers.notify_all(cfg, BODY, NOW, [], [])
        bd.assert_not_called()

    def test_buttondown_still_used_without_audience(self):
        from src import notifiers
        cfg = _cfg(RESEND_AUDIENCE_ID="", BUTTONDOWN_API_KEY="bd-key")
        with mock.patch.object(notifiers, "send_buttondown") as bd:
            notifiers.notify_all(cfg, BODY, NOW, [], [])
        bd.assert_called_once()


if __name__ == "__main__":
    unittest.main()
