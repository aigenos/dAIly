"""Audio episode / podcast-mode tests — gTTS and network mocked."""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

from src import audio
from src.config import Config

NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)

BODY = (
    "<!--SECTION:intro-->\n<h2>👋 In Brief (30 sec read)</h2>"
    "<p>A big day for open models.</p>\n"
    "<!--SECTION:pulse-->\n<h2>⚡ The Pulse (90 sec read)</h2>"
    '<h3>🎯 Today\'s Game-Changer</h3>'
    '<p><a href="https://x.com/m">MegaModel 9</a> shipped with 2x context.</p>\n'
    "<!--SECTION:opp_teaser-->\n<h2>🚀 Opportunity of the Day (2 min read)</h2>"
    "<h3>AgentLint</h3><ul><li><strong>The gap:</strong> nobody lints traces.</li></ul>"
)


def _cfg(tmp, **env):
    base = {
        "PROVIDER": "ollama", "DRY_RUN": "true", "ARCHIVE_DIR": tmp,
        "PUBLISH_ARCHIVE": "true", "SITE_URL": "https://me.github.io/dAIly",
        "ENABLE_AUDIO": "true",
    }
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        return Config.from_env()


class FakeTTS:
    """Stands in for gtts.gTTS — writes a tiny fake mp3."""
    last_text = ""

    def __init__(self, text="", **kwargs):
        FakeTTS.last_text = text

    def save(self, path):
        with open(path, "wb") as fh:
            fh.write(b"ID3fakemp3")


class TestSpokenText(unittest.TestCase):
    def test_includes_intro_pulse_opportunity_without_urls(self):
        text = audio._spoken_text(BODY)
        self.assertIn("A big day for open models", text)
        self.assertIn("MegaModel 9", text)
        self.assertIn("opportunity of the day", text.lower())
        self.assertNotIn("http", text)

    def test_estimate_minutes_floor_one(self):
        self.assertEqual(audio.estimate_minutes("short text"), 1)
        self.assertEqual(audio.estimate_minutes("word " * 480), 3)


class TestGenerate(unittest.TestCase):
    def _gen(self, cfg):
        fake_mod = types.SimpleNamespace(gTTS=FakeTTS)
        with mock.patch.dict(sys.modules, {"gtts": fake_mod}):
            return audio.generate(cfg, BODY, NOW)

    def test_episode_in_archive_with_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = self._gen(_cfg(tmp))
            self.assertIsNotNone(episode)
            self.assertTrue(os.path.exists(episode["path"]))
            self.assertTrue(episode["path"].endswith(
                os.path.join("audio", "digest_20260708.mp3")))
            self.assertEqual(
                episode["url"],
                "https://me.github.io/dAIly/audio/digest_20260708.mp3",
            )
            self.assertGreaterEqual(episode["minutes"], 1)
            # Voiced text carries the branded intro/outro.
            self.assertIn("dAIly", FakeTTS.last_text)

    def test_no_url_without_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            episode = self._gen(_cfg(tmp, SITE_URL="", PUBLISH_ARCHIVE="false",
                                     AUDIO_DIR=os.path.join(tmp, "out")))
            self.assertIsNotNone(episode)
            self.assertEqual(episode["url"], "")

    def test_fail_open_without_gtts(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(sys.modules, {"gtts": None}):
            self.assertIsNone(audio.generate(_cfg(tmp), BODY, NOW))

    def test_prune_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            adir = os.path.join(tmp, "audio")
            os.makedirs(adir)
            for i in range(audio.KEEP_EPISODES + 5):
                open(os.path.join(adir, f"digest_202601{i:02d}.mp3"), "wb").close()
            audio._prune_old(adir)
            left = [f for f in os.listdir(adir) if f.endswith(".mp3")]
            self.assertEqual(len(left), audio.KEEP_EPISODES)
            self.assertIn(f"digest_202601{audio.KEEP_EPISODES + 4:02d}.mp3", left)


class TestListenUI(unittest.TestCase):
    def test_listen_button_links_episode(self):
        from src.emailer import listen_button
        html = listen_button("https://x/audio/digest_20260708.mp3", 4)
        self.assertIn("Listen to today", html)
        self.assertIn("4 min", html)
        self.assertIn("https://x/audio/digest_20260708.mp3", html)

    def test_listen_button_empty_without_url(self):
        from src.emailer import listen_button
        self.assertEqual(listen_button(""), "")

    def test_prelude_renders_at_top_of_card(self):
        from src.emailer import listen_button, render_html
        html = render_html("<p>body text</p>", NOW,
                           prelude=listen_button("https://x/a.mp3", 3))
        self.assertLess(html.index("Listen to today"), html.index("body text"))

    def test_audio_player_has_audio_element(self):
        from src.emailer import audio_player
        html = audio_player("../audio/digest_20260708.mp3")
        self.assertIn("<audio controls", html)
        self.assertIn("../audio/digest_20260708.mp3", html)


class TestPodcastFeed(unittest.TestCase):
    def test_feed_lists_episodes_newest_first(self):
        from src.archive import _render_podcast_feed
        with tempfile.TemporaryDirectory() as tmp:
            adir = os.path.join(tmp, "audio")
            os.makedirs(adir)
            for name in ("digest_20260707.mp3", "digest_20260708.mp3"):
                with open(os.path.join(adir, name), "wb") as fh:
                    fh.write(b"x" * 100)
            cfg = _cfg(tmp)
            feed = _render_podcast_feed(cfg)
        self.assertIn("<rss", feed)
        self.assertIn('enclosure url="https://me.github.io/dAIly/audio/digest_20260708.mp3"', feed)
        self.assertIn('length="100"', feed)
        self.assertLess(feed.index("digest_20260708"), feed.index("digest_20260707"))

    def test_feed_empty_without_episodes(self):
        from src.archive import _render_podcast_feed
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_render_podcast_feed(_cfg(tmp)), "")


if __name__ == "__main__":
    unittest.main()
