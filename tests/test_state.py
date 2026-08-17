"""Cross-day dedup state tests — no network, all on a temp dir."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src import state
from src.fetchers import Item


def _item(title="A story", url="https://x.com/a"):
    return Item("Src", "lab", title, url, None)


class TestStateRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = state.state_path(self.tmp.name)
        self.now = datetime(2026, 6, 10, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_empty_state(self):
        self.assertEqual(state.load(self.path), {})

    def test_corrupt_file_fails_open(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            fh.write("{not json!!")
        self.assertEqual(state.load(self.path), {})

    def test_wrong_shape_fails_open(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            json.dump(["a", "b"], fh)
        self.assertEqual(state.load(self.path), {})

    def test_mark_save_load_filter(self):
        seen: dict[str, float] = {}
        state.mark_seen([_item()], seen, self.now)
        state.save(self.path, seen, self.now, keep_days=14)

        loaded = state.load(self.path)
        self.assertEqual(loaded, seen)

        # Same URL → filtered; same title under new URL → filtered too.
        kept = state.filter_new(
            [
                _item(),
                _item(title="A Story!", url="https://mirror.com/b"),
                _item(title="Fresh news", url="https://y.com/new"),
            ],
            loaded,
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].url, "https://y.com/new")

    def test_prune_on_save(self):
        seen: dict[str, float] = {}
        old = self.now - timedelta(days=30)
        state.mark_seen([_item(url="https://x.com/old")], seen, old)
        state.mark_seen([_item(title="New", url="https://x.com/new")], seen, self.now)
        state.save(self.path, seen, self.now, keep_days=14)
        loaded = state.load(self.path)
        # Only the fresh item's two keys (url + title) survive pruning.
        self.assertEqual(len(loaded), 2)

    def test_save_failure_is_nonfatal(self):
        # Path inside a file (not a dir) → makedirs/open fails; must not raise.
        bogus = os.path.join(self.tmp.name, "file")
        with open(bogus, "w") as fh:
            fh.write("x")
        state.save(os.path.join(bogus, "nested", "s.json"), {}, self.now, 14)

    def test_filter_empty_state_passthrough(self):
        items = [_item()]
        self.assertIs(state.filter_new(items, {}), items)

    def test_shown_in_digest_matches_only_used_items(self):
        # Only items whose link appears in the rendered body may be marked seen —
        # unused prompt candidates must survive for future issues.
        used = _item(title="Used", url="https://x.com/used")
        unused = _item(title="Unused", url="https://x.com/unused")
        body = '<p><a href="https://x.com/used">Used</a> shipped.</p>'
        self.assertEqual(state.shown_in_digest([used, unused], body), [used])

    def test_shown_in_digest_matches_https_normalized_arxiv(self):
        # Fetcher yields http:// arXiv links; the digest normalizes to https.
        it = _item(title="Paper", url="http://arxiv.org/abs/2606.01234")
        body = '<a href="https://arxiv.org/abs/2606.01234">Paper</a>'
        self.assertEqual(state.shown_in_digest([it], body), [it])


if __name__ == "__main__":
    unittest.main()
