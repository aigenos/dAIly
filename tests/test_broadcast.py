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
        "EMAIL_FROM": "dAIly <digest@aigenos.io>",
        "RESEND_API_KEY": "re-key",
        "RESEND_AUDIENCE_ID": "aud_1",
    }
    base.update(env)
    # Drop keys explicitly set to None so tests can simulate unset env vars.
    base = {k: v for k, v in base.items() if v is not None}
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

    def test_audience_autoresolved_when_id_unset(self):
        # No RESEND_AUDIENCE_ID -> the account's first audience is used.
        cfg = _cfg(RESEND_AUDIENCE_ID=None)
        listing = mock.Mock(status_code=200)
        listing.json.return_value = {"data": [{"id": "aud_auto", "name": "General"}]}
        post = _two_step_post()
        with mock.patch.object(broadcast.requests, "get", return_value=listing), \
             mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(cfg, BODY, NOW, private_ids=["opportunity_map"],
                                  sentinels=["Full Opportunity Map"])
        self.assertTrue(ok)
        create = post.call_args_list[0]
        self.assertEqual(create.kwargs["json"]["audience_id"], "aud_auto")
        # Unsubscribe merge tag still present despite UNSUBSCRIBE_URL being unset.
        self.assertIn("{{{RESEND_UNSUBSCRIBE_URL}}}", create.kwargs["json"]["html"])

    def test_audience_autocreated_when_none_exist(self):
        cfg = _cfg(RESEND_AUDIENCE_ID=None)
        empty = mock.Mock(status_code=200)
        empty.json.return_value = {"data": []}
        created_aud = mock.Mock(status_code=201)
        created_aud.json.return_value = {"id": "aud_new"}
        bc = mock.Mock(status_code=201); bc.json.return_value = {"id": "bc_1"}
        sent = mock.Mock(status_code=200)
        post = mock.Mock(side_effect=[created_aud, bc, sent])
        with mock.patch.object(broadcast.requests, "get", return_value=empty), \
             mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(cfg, BODY, NOW, private_ids=["opportunity_map"],
                                  sentinels=["Full Opportunity Map"])
        self.assertTrue(ok)
        self.assertEqual(post.call_args_list[0].kwargs["json"], {"name": "dAIly subscribers"})
        self.assertEqual(post.call_args_list[1].kwargs["json"]["audience_id"], "aud_new")

    def test_sender_derived_from_verified_domain(self):
        # EMAIL_FROM left on the onboarding default -> digest@<verified domain>.
        cfg = _cfg(EMAIL_FROM=None)
        domains = mock.Mock(status_code=200)
        domains.json.return_value = {"data": [{"name": "aigenos.io", "status": "verified"}]}
        post = _two_step_post()
        with mock.patch.object(broadcast.requests, "get", return_value=domains), \
             mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(cfg, BODY, NOW, private_ids=["opportunity_map"],
                                  sentinels=["Full Opportunity Map"])
        self.assertTrue(ok)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["from"],
                         "dAIly <digest@aigenos.io>")

    def test_skipped_when_no_verified_domain(self):
        cfg = _cfg(EMAIL_FROM=None)
        domains = mock.Mock(status_code=200)
        domains.json.return_value = {"data": [{"name": "aigenos.io", "status": "pending"}]}
        post = mock.Mock()
        with mock.patch.object(broadcast.requests, "get", return_value=domains), \
             mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(cfg, BODY, NOW)
        self.assertFalse(ok)
        post.assert_not_called()

    def test_noop_without_api_key(self):
        post = mock.Mock()
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(_cfg(RESEND_API_KEY="", DRY_RUN="true"), BODY, NOW)
        self.assertFalse(ok)
        post.assert_not_called()

    def test_create_error_fails_open(self):
        post = mock.Mock(return_value=mock.Mock(status_code=422, text="bad"))
        with mock.patch.object(broadcast.requests, "post", post):
            ok = send_subscribers(_cfg(), BODY, NOW)
        self.assertFalse(ok)  # logged + skipped, never raises
        self.assertEqual(post.call_count, 1)  # never reached the send step


class TestSingleSubscriberChannel(unittest.TestCase):
    def test_buttondown_skipped_when_broadcast_delivered(self):
        # Resend delivered the identical copy -> Buttondown must NOT send a
        # second, differently-rendered one.
        from src import notifiers
        cfg = _cfg(BUTTONDOWN_API_KEY="bd-key")
        with mock.patch.object(notifiers, "send_buttondown") as bd:
            notifiers.notify_all(cfg, BODY, NOW, [], [], subscribers_delivered=True)
        bd.assert_not_called()

    def test_buttondown_fallback_when_broadcast_failed(self):
        # Broadcast didn't go out (e.g. domain not verified yet) -> Buttondown
        # still delivers, so subscribers never miss an issue mid-migration.
        from src import notifiers
        cfg = _cfg(BUTTONDOWN_API_KEY="bd-key")
        with mock.patch.object(notifiers, "send_buttondown") as bd:
            notifiers.notify_all(cfg, BODY, NOW, [], [], subscribers_delivered=False)
        bd.assert_called_once()


class TestButtondownSync(unittest.TestCase):
    def test_missing_subscribers_are_added(self):
        cfg = _cfg(BUTTONDOWN_API_KEY="bd-key")
        contacts = mock.Mock(status_code=200)
        contacts.json.return_value = {"data": [{"email": "already@x.com"}]}
        bd_list = mock.Mock(status_code=200)
        bd_list.json.return_value = {"results": [
            {"email_address": "already@x.com", "subscriber_type": "regular"},
            {"email_address": "new@x.com", "subscriber_type": "regular"},
            {"email_address": "gone@x.com", "subscriber_type": "unsubscribed"},
            {"email_address": "not-an-email", "subscriber_type": "regular"},
        ], "next": None}
        post = mock.Mock(return_value=mock.Mock(status_code=201))
        with mock.patch.object(broadcast.requests, "get",
                               side_effect=[contacts, bd_list]), \
             mock.patch.object(broadcast.requests, "post", post):
            added = broadcast.sync_buttondown_contacts(cfg, "aud_1")
        self.assertEqual(added, 1)  # only the genuinely new active subscriber
        self.assertEqual(post.call_args.kwargs["json"]["email"], "new@x.com")

    def test_noop_without_buttondown_key(self):
        with mock.patch.object(broadcast.requests, "get") as get:
            self.assertEqual(broadcast.sync_buttondown_contacts(_cfg(), "aud_1"), 0)
        get.assert_not_called()

    def test_sync_failure_is_fail_open(self):
        cfg = _cfg(BUTTONDOWN_API_KEY="bd-key")
        import requests as _rq
        with mock.patch.object(broadcast.requests, "get",
                               side_effect=_rq.ConnectionError("boom")):
            self.assertEqual(broadcast.sync_buttondown_contacts(cfg, "aud_1"), 0)


if __name__ == "__main__":
    unittest.main()
