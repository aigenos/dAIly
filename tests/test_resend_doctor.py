"""Resend doctor checks — all network mocked."""

from __future__ import annotations

import unittest
from unittest import mock

from scripts import resend_doctor
from scripts.resend_doctor import _from_domain, run_checks


def _fake_get(responses: dict[str, tuple[int, dict]]):
    """Map path-prefix -> (status, json)."""
    def get(path, api_key):
        for prefix, resp in responses.items():
            if path.startswith(prefix):
                return resp
        return 404, {}
    return get


GOOD = {
    "/domains": (200, {"data": [{"name": "aigenos.dev", "status": "verified"}]}),
    "/audiences/aud_1/contacts": (200, {"data": [
        {"email": "a@x.com", "unsubscribed": False},
        {"email": "b@x.com", "unsubscribed": True},
    ]}),
    "/audiences": (200, {"data": [{"id": "aud_1", "name": "General"}]}),
}


class TestFromDomain(unittest.TestCase):
    def test_display_name_form(self):
        self.assertEqual(_from_domain("dAIly <digest@aigenos.dev>"), "aigenos.dev")

    def test_bare_address(self):
        self.assertEqual(_from_domain("digest@aigenos.dev"), "aigenos.dev")

    def test_empty(self):
        self.assertEqual(_from_domain(""), "")


class TestRunChecks(unittest.TestCase):
    def _run(self, responses, email_from="dAIly <digest@aigenos.dev>", audience="aud_1"):
        with mock.patch.object(resend_doctor, "_get", _fake_get(responses)):
            return run_checks("re_key", email_from, audience)

    def test_all_green(self):
        rows = self._run(GOOD)
        self.assertTrue(all(ok for ok, _ in rows), rows)
        self.assertIn("2 contact(s), 1 subscribed", rows[-1][1])

    def test_no_key_short_circuits(self):
        rows = run_checks("", "x", "y")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0][0])

    def test_unverified_domain_flagged(self):
        resp = dict(GOOD)
        resp["/domains"] = (200, {"data": [{"name": "aigenos.dev", "status": "pending"}]})
        rows = self._run(resp)
        self.assertTrue(any(not ok and "NOT verified" in msg for ok, msg in rows))

    def test_onboarding_sender_flagged(self):
        rows = self._run(GOOD, email_from="AI Digest <onboarding@resend.dev>")
        self.assertTrue(any(not ok and "onboarding@resend.dev" in msg for ok, msg in rows))

    def test_missing_audience_lists_available(self):
        rows = self._run(GOOD, audience="")
        bad = [msg for ok, msg in rows if not ok]
        self.assertTrue(any("General=aud_1" in m for m in bad))

    def test_wrong_audience_id_flagged(self):
        rows = self._run(GOOD, audience="aud_nope")
        self.assertTrue(any(not ok and "not found" in msg for ok, msg in rows))

    def test_empty_audience_flagged(self):
        resp = dict(GOOD)
        resp["/audiences/aud_1/contacts"] = (200, {"data": []})
        rows = self._run(resp)
        self.assertTrue(any(not ok and "0 contacts" in msg for ok, msg in rows))

    def test_bad_key_reported(self):
        resp = {"/domains": (401, {})}
        rows = self._run(resp)
        self.assertEqual(len(rows), 1)
        self.assertIn("invalid", rows[0][1])


if __name__ == "__main__":
    unittest.main()
