"""Fact-gate tests — the verifier pass that keeps wrong information out.

All provider calls mocked. The gate must be fail-open: any misbehavior by the
checker (lost markers, gutted content, errors, empty output) keeps the
original draft byte-for-byte.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import analyzer
from src.analyzer import _fact_check
from src.config import Config

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)

DRAFT = (
    "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2>"
    '<p><a href="https://x.com/a">RealModel</a> shipped with a 41% score.</p>'
    "<ul><li>True bullet kept verbatim.</li>"
    "<li>FabricatedThing 9 launched — 99% on FakeBench.</li></ul>\n"
    "<!--SECTION:stack-->\n<h2>📊 Stack Signals (3 min read)</h2><p>x</p>"
)


def _cfg(**env):
    base = {"PROVIDER": "ollama", "DRY_RUN": "true", "EMAIL_TO": "o@x.com"}
    base.update(env)
    base = {k: v for k, v in base.items() if v is not None}
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


class TestFactCheckConfig(unittest.TestCase):
    def test_on_by_default_model_blank(self):
        cfg = _cfg()
        self.assertTrue(cfg.fact_check)
        self.assertEqual(cfg.factcheck_model, "")

    def test_can_disable_and_override_model(self):
        cfg = _cfg(FACT_CHECK="false", FACTCHECK_MODEL="gemini-2.5-pro")
        self.assertFalse(cfg.fact_check)
        self.assertEqual(cfg.factcheck_model, "gemini-2.5-pro")


class TestFactCheckPass(unittest.TestCase):
    def test_good_correction_is_used(self):
        corrected = DRAFT.replace(
            "<li>FabricatedThing 9 launched — 99% on FakeBench.</li>", ""
        )
        with mock.patch.object(analyzer.providers, "generate", return_value=corrected) as gen:
            out = _fact_check(_cfg(), DRAFT, NOW)
        self.assertEqual(out, corrected)
        self.assertNotIn("FabricatedThing", out)
        self.assertIn("True bullet kept verbatim.", out)
        # The checker saw the draft and the fact-checker system prompt.
        system, user = gen.call_args.args[1], gen.call_args.args[2]
        self.assertIn("FACT-CHECKER", system)
        self.assertIn("NUMBERS ARE QUOTES", system)
        self.assertIn(DRAFT, user)

    def test_lost_marker_keeps_draft(self):
        mangled = DRAFT.replace("<!--SECTION:stack-->", "")
        with mock.patch.object(analyzer.providers, "generate", return_value=mangled):
            self.assertEqual(_fact_check(_cfg(), DRAFT, NOW), DRAFT)

    def test_gutted_output_keeps_draft(self):
        tiny = "<!--SECTION:pulse--><!--SECTION:stack--><p>ok</p>"
        with mock.patch.object(analyzer.providers, "generate", return_value=tiny):
            self.assertEqual(_fact_check(_cfg(), DRAFT, NOW), DRAFT)

    def test_empty_output_keeps_draft(self):
        with mock.patch.object(analyzer.providers, "generate", return_value="  "):
            self.assertEqual(_fact_check(_cfg(), DRAFT, NOW), DRAFT)

    def test_provider_error_keeps_draft(self):
        with mock.patch.object(analyzer.providers, "generate",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(_fact_check(_cfg(), DRAFT, NOW), DRAFT)

    def test_model_override_used(self):
        with mock.patch.object(analyzer.providers, "generate", return_value=DRAFT) as gen:
            _fact_check(_cfg(FACTCHECK_MODEL="strong-model"), DRAFT, NOW)
        self.assertEqual(gen.call_args.args[0].model, "strong-model")


class TestFirstPassRules(unittest.TestCase):
    def test_numbers_and_absolutes_rules_in_instructions(self):
        instr = analyzer.build_instructions()
        self.assertIn("NUMBERS ARE QUOTES, NOT ESTIMATES", instr)
        self.assertIn("ABSOLUTE CLAIMS REQUIRE A SEARCH", instr)


if __name__ == "__main__":
    unittest.main()
