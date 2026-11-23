import os
import tempfile
import unittest
from datetime import timedelta
from unittest import mock

from kangtwin import config, heartbeat


class HeartbeatTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_fresh_beat_is_not_stale(self):
        t = config.now()
        heartbeat.beat("contest-scout", now=t)
        self.assertEqual(heartbeat.stale(t + timedelta(hours=1), paused=frozenset()), [])

    def test_beat_older_than_expected_is_stale(self):
        t = config.now()
        heartbeat.beat("contest-scout", now=t)
        self.assertEqual(heartbeat.stale(t + timedelta(hours=27), paused=frozenset()), ["contest-scout"])

    def test_daily_scout_is_fine_within_a_day(self):
        t = config.now().replace(hour=8, minute=35)
        heartbeat.beat("contest-scout", now=t)
        self.assertEqual(heartbeat.stale(t + timedelta(hours=24), paused=frozenset()), [])

    def test_never_beaten_job_is_not_stale(self):
        self.assertEqual(heartbeat.stale(config.now() + timedelta(days=5)), [])

    def test_failed_beat_is_reported_as_stale(self):
        t = config.now()
        heartbeat.beat("interview", ok=False, note="claude 시간 초과", now=t)
        self.assertEqual(heartbeat.stale(t + timedelta(minutes=1)), ["interview"])

    def test_status_lines_include_note(self):
        heartbeat.beat("interview", ok=False, note="claude 시간 초과")
        self.assertIn("claude 시간 초과", "\n".join(heartbeat.status_lines()))


class PausedHeartbeatTest(HeartbeatTest):
    def test_paused_job_never_alerts(self):
        t = config.now()
        heartbeat.beat("contest-scout", now=t)
        self.assertEqual(heartbeat.stale(t + timedelta(days=3)), [])

    def test_status_marks_paused_jobs(self):
        heartbeat.beat("contest-scout")
        lines = heartbeat.status_lines()
        self.assertIn("contest-scout: 중지됨", lines)
        self.assertIn("fund-scout: 중지됨", lines)


if __name__ == "__main__":
    unittest.main()
