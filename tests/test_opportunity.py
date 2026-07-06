"""Opportunity novelty-guard tests: self-memory from receipts + prior-art rule,
and that the paid 'Builder's Edge' template is a valid private section."""

from __future__ import annotations

import contextlib
import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import analyzer
from src.analyzer import (
    _opportunity_memory_block,
    build_digest,
    build_instructions,
    recent_opportunity_titles,
)
from src.config import Config

NOW = datetime(2026, 6, 14, tzinfo=timezone.utc)

RECEIPTS = """\
# Receipts — Opportunity of the Day, every day

intro line

- **2026-06-13** — [TraceLint](https://x/digests/digest_20260613.html)
- **2026-06-12** — [AgentMeter](https://x/digests/digest_20260612.html)
- **2026-01-02** — [AncientIdea](https://x/digests/digest_20260102.html)
"""


def _cfg(tmp, **env):
    base = {"PROVIDER": "ollama", "DRY_RUN": "true", "ARCHIVE_DIR": tmp}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


class TestRecentOpportunityTitles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmp.name, "receipts.md"), "w") as fh:
            fh.write(RECEIPTS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recent_within_window_newest_first(self):
        titles = recent_opportunity_titles(self.tmp.name, 60, NOW)
        self.assertEqual(titles[:2], ["TraceLint", "AgentMeter"])
        self.assertNotIn("AncientIdea", titles)  # ~5 months old, outside 60d

    def test_wide_window_includes_old(self):
        titles = recent_opportunity_titles(self.tmp.name, 365, NOW)
        self.assertIn("AncientIdea", titles)

    def test_missing_file_fails_open(self):
        self.assertEqual(recent_opportunity_titles("/no/such/dir", 60, NOW), [])


class TestMemoryBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmp.name, "receipts.md"), "w") as fh:
            fh.write(RECEIPTS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_block_lists_recent_picks(self):
        block = _opportunity_memory_block(_cfg(self.tmp.name), NOW)
        self.assertIn("ALREADY PROPOSED", block)
        self.assertIn("TraceLint", block)

    def test_block_empty_when_memory_disabled(self):
        cfg = _cfg(self.tmp.name, OPPORTUNITY_MEMORY="false")
        self.assertEqual(_opportunity_memory_block(cfg, NOW), "")

    def test_block_empty_without_history(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(_opportunity_memory_block(_cfg(empty), NOW), "")

    def test_memory_injected_into_prompt(self):
        cfg = _cfg(self.tmp.name)
        captured = {}

        def fake_generate(c, system, user):
            captured["user"] = user
            return "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>x</p>"

        with mock.patch.object(analyzer.providers, "generate", side_effect=fake_generate):
            build_digest(cfg, [], NOW)
        self.assertIn("ALREADY PROPOSED", captured["user"])
        self.assertIn("TraceLint", captured["user"])

    def test_memory_absent_from_prompt_when_disabled(self):
        cfg = _cfg(self.tmp.name, OPPORTUNITY_MEMORY="false")
        captured = {}

        def fake_generate(c, system, user):
            captured["user"] = user
            return "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2><p>x</p>"

        with mock.patch.object(analyzer.providers, "generate", side_effect=fake_generate):
            build_digest(cfg, [], NOW)
        # The static prior-art rule references "ALREADY PROPOSED", but the
        # injected memory (the actual receipt titles) must be absent.
        self.assertNotIn("TraceLint", captured["user"])
        self.assertNotIn("published in the last", captured["user"])


class TestPriorArtRule(unittest.TestCase):
    def test_teaser_has_closest_existing_solution_and_prior_art(self):
        instructions = build_instructions()
        self.assertIn("Closest existing solution", instructions)
        self.assertIn("PRIOR ART", instructions)


class TestBuildersEdgeModule(unittest.TestCase):
    """The bundled paid section must be a valid, well-formed private section."""

    def _load(self):
        from src.private import builders_edge
        return builders_edge

    def test_module_is_well_formed(self):
        mod = self._load()
        self.assertEqual(mod.SECTION_ID, "builders_edge")
        self.assertIsInstance(mod.ORDER, int)
        self.assertIn(f"<!--SECTION:{mod.SECTION_ID}-->", mod.INSTRUCTIONS)
        self.assertIn("Prior art", mod.INSTRUCTIONS)
        self.assertIn("ALREADY PROPOSED", mod.INSTRUCTIONS)
        # The 3–6 month research grounding the user asked for.
        self.assertIn("RESEARCH HORIZON", mod.INSTRUCTIONS)
        self.assertIn("3–6 month", mod.INSTRUCTIONS)
        self.assertTrue(mod.PUBLIC_SENTINELS)
        for s in mod.PUBLIC_SENTINELS:
            self.assertIn(s.split()[-1], mod.INSTRUCTIONS)

    def test_strips_like_a_private_section(self):
        from src.archive import strip_private_sections

        mod = self._load()
        body = (
            "<!--SECTION:pulse-->\n<h2>Pulse</h2><p>keep</p>\n"
            + mod.INSTRUCTIONS
            + "\n<!--SECTION:stack-->\n<h2>Stack</h2><p>keep</p>"
        )
        public = strip_private_sections(body, [mod.SECTION_ID], mod.PUBLIC_SENTINELS)
        self.assertIn("Pulse", public)
        self.assertIn("Stack", public)
        self.assertNotIn("Builder", public)


class TestBuildersEdgeActivation(unittest.TestCase):
    """ENABLE_BUILDERS_EDGE loads the bundled paid section (no private module).

    A real src/private/opportunity.py (gitignored secret sauce) rightfully wins
    over builders_edge, so these tests block that import to simulate the public
    clone this activation path is for.
    """

    @staticmethod
    @contextlib.contextmanager
    def _no_private_module():
        # `from .private import opportunity` resolves via the package attribute
        # when the module was already imported, so hide BOTH the attribute and
        # the sys.modules entry (a None entry forces ImportError on re-import).
        import sys
        from src import private as priv
        saved_attr = priv.__dict__.pop("opportunity", None)
        saved_mod = sys.modules.pop("src.private.opportunity", None)
        sys.modules["src.private.opportunity"] = None  # type: ignore[assignment]
        try:
            yield
        finally:
            sys.modules.pop("src.private.opportunity", None)
            if saved_mod is not None:
                sys.modules["src.private.opportunity"] = saved_mod
            if saved_attr is not None:
                priv.opportunity = saved_attr

    def test_loads_when_enabled(self):
        with self._no_private_module(), \
             mock.patch.dict(os.environ, {"ENABLE_BUILDERS_EDGE": "true"}, clear=False):
            ids = analyzer.private_section_ids()
            sentinels = analyzer.private_sentinels()
            instructions = build_instructions()
        self.assertIn("builders_edge", ids)
        self.assertTrue(any("Builder" in s for s in sentinels))
        self.assertIn("<!--SECTION:builders_edge-->", instructions)
        self.assertIn("RESEARCH HORIZON", instructions)

    def test_absent_when_disabled(self):
        env = dict(os.environ)
        env.pop("ENABLE_BUILDERS_EDGE", None)
        with self._no_private_module(), mock.patch.dict(os.environ, env, clear=True):
            self.assertNotIn("builders_edge", analyzer.private_section_ids())


if __name__ == "__main__":
    unittest.main()
