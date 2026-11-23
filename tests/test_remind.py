import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from kangtwin import daemon, remind, store
from kangtwin.telegram import TelegramError

KST = timezone(timedelta(hours=9))
OWNER = 1001


def at(month, day, h=9, m=0):
    return datetime(2026, month, day, h, m, tzinfo=KST)


class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_message(self, chat_id, text, buttons=None):
        if self.fail:
            raise TelegramError("sendMessage failed: HTTP 500")
        self.sent.append((chat_id, text))
        return {"message_id": 1}


class RemindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_add_keeps_order_and_ids(self):
        remind.add(remind.parse_at("2026-11-12 12:00"), "KIC 투표 시작")
        remind.add(remind.parse_at("2026-11-01 10:00"), "본선 발표")
        rows = store.load("reminders", [])
        self.assertEqual([(r["id"], r["at"]) for r in rows], [(2, "2026-11-01 10:00"), (1, "2026-11-12 12:00")])
        self.assertIsNone(rows[0]["sent"])

    def test_parse_at_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            remind.parse_at("11/12 12시")

    def test_fires_due_once(self):
        remind.add(at(11, 1, 10), "본선 발표")
        remind.add(at(11, 12, 12), "KIC 투표 시작")
        bot = FakeBot()
        self.assertEqual(remind.fire(bot, OWNER, at(11, 1, 9, 59)), 0)
        self.assertEqual(remind.fire(bot, OWNER, at(11, 1, 10)), 1)
        self.assertEqual(remind.fire(bot, OWNER, at(11, 1, 10, 1)), 0)
        self.assertEqual(bot.sent, [(OWNER, "[알림] 본선 발표")])
        rows = store.load("reminders", [])
        self.assertTrue(rows[0]["sent"].startswith("2026-11-01T10:00"))
        self.assertIsNone(rows[1]["sent"])

    def test_late_reminder_says_so(self):
        remind.add(at(11, 1, 10), "본선 발표")
        bot = FakeBot()
        remind.fire(bot, OWNER, at(11, 2, 8))
        self.assertIn("2026-11-01 10:00에 보낼 거였는데 늦었음", bot.sent[0][1])

    def test_send_failure_retries_next_time(self):
        remind.add(at(11, 1, 10), "본선 발표")
        with self.assertRaises(TelegramError):
            remind.fire(FakeBot(fail=True), OWNER, at(11, 1, 10))
        bot = FakeBot()
        self.assertEqual(remind.fire(bot, OWNER, at(11, 1, 10, 1)), 1)

    def test_upcoming_lists_next_unsent(self):
        for day in (1, 12, 18, 20):
            remind.add(at(11, day), "알림 %d일\n둘째 줄" % day)
        remind.fire(FakeBot(), OWNER, at(11, 1, 9))
        self.assertEqual(remind.upcoming(at(11, 2), limit=2),
                         ["11/12(목) 09:00 알림 12일", "11/18(수) 09:00 알림 18일"])

    def test_remove(self):
        row = remind.add(at(11, 1), "본선 발표")
        self.assertTrue(remind.remove(row["id"]))
        self.assertFalse(remind.remove(row["id"]))
        self.assertEqual(store.load("reminders", []), [])

    def test_status_shows_next_reminders(self):
        remind.add(at(11, 12, 12), "KIC 투표 시작")
        with mock.patch.object(daemon.config, "now", return_value=at(10, 13)):
            text = daemon.status_text()
        self.assertIn("다음 알림:\n• 11/12(목) 12:00 KIC 투표 시작", text)


if __name__ == "__main__":
    unittest.main()
