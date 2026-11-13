"""Focused tests for destructive API-data retention behavior."""

import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from api_data_retention import (
    flags_from_records, fresh_user_flags, purge_expired_sessions,
)
from settings_manager import SettingsManager


class RetentionTests(unittest.TestCase):
    def test_only_expired_app_sessions_are_deleted(self):
        build_dir = Path(__file__).parent / "build"
        build_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_dir) as temporary:
            root = Path(temporary) / "logs" / "sessions"
            root.mkdir(parents=True)
            old = root / "20260901_120000_oldvideo"
            recent = root / "20261110_120000_newvideo"
            unrelated = root / "user_notes"
            for path in (old, recent, unrelated):
                path.mkdir()
                (path / "comments.jsonl").write_text("sample", encoding="utf-8")
            count = purge_expired_sessions(temporary, datetime.datetime(2026, 11, 13))
            self.assertEqual(count, 1)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_saved_viewer_flags_expire_and_legacy_flags_do_not_survive(self):
        now = datetime.datetime(2026, 11, 13)
        flags = {
            "old": {"stored_at": "2026-10-01T00:00:00", "display_name": "old"},
            "new": {"stored_at": "2026-11-12T00:00:00", "display_name": "new"},
            "legacy": {"display_name": "legacy"},
        }
        self.assertEqual(list(fresh_user_flags(flags, now)), ["new"])

    def test_saving_one_viewer_does_not_refresh_other_viewers(self):
        now = datetime.datetime(2026, 11, 13, 12)
        def viewer(channel_id, days_old):
            return SimpleNamespace(
                channel_id=channel_id, display_name=channel_id,
                last_comment_time=now - datetime.timedelta(days=days_old),
                is_whitelist=True, is_blacklist=False,
                is_filter_target=True,
            )
        flags = flags_from_records([viewer('old', 40), viewer('recent', 1)], now)
        self.assertEqual(list(flags), ['recent'])
        self.assertEqual(flags['recent']['stored_at'], '2026-11-12T12:00:00')

    def test_settings_reload_keeps_unrelated_configuration(self):
        build_dir = Path(__file__).parent / "build"
        build_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=build_dir) as temporary:
            config = Path(temporary) / "settings.json"
            config.write_text(json.dumps({
                "theme": "dark",
                "user_flags": {"legacy": {"display_name": "old"}}
            }), encoding="utf-8")
            manager = SettingsManager(str(config))
            manager.load()
            self.assertEqual(manager.get("theme"), "dark")
            self.assertEqual(manager.get("user_flags"), {})
            reloaded = SettingsManager(str(config))
            reloaded.load()
            self.assertEqual(reloaded.get("theme"), "dark")
            self.assertEqual(reloaded.get("user_flags"), {})


if __name__ == "__main__":
    unittest.main()
