import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from kangtwin import config, daemon, heartbeat, store
from kangtwin.telegram import TelegramError

KST = timezone(timedelta(hours=9))
OWNER = 1001


class FakeBot:
    def __init__(self, updates=None, fail_get=False, fail_send=False):
        self.updates = updates or []
        self.fail_get = fail_get
        self.fail_send = fail_send
        self.sent = []
        self.acked = []
        self.cleared = []

    def get_updates(self, offset, timeout=50):
        if self.fail_get:
            raise TelegramError("getUpdates failed: HTTP 409")
        self.offset_seen = offset
        return self.updates

    def send_message(self, chat_id, text, buttons=None):
        if self.fail_send:
            raise TelegramError("sendMessage failed: HTTP 500")
        self.sent.append((chat_id, text, buttons))
        return {"message_id": 1}

    def answer_callback(self, callback_id, text=""):
        self.acked.append(callback_id)

    def clear_buttons(self, chat_id, message_id):
        self.cleared.append((chat_id, message_id))


def text(chat, body, uid):
    return {"update_id": uid, "message": {"message_id": 5, "chat": {"id": chat}, "text": body}}


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": self.tmp.name})
        self.env.start()
        self.spawned = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def spawn(self, args):
        self.spawned.append(args)

    def test_network_error_keeps_offset_and_reports_false(self):
        store.save("offset", {"next": 40})
        ok = daemon.step(FakeBot(fail_get=True), spawn=self.spawn, timeout=0)
        self.assertFalse(ok)
        self.assertEqual(store.load("offset", {}), {"next": 40})

    def test_offset_advances_and_status_is_answered(self):
        store.save("owner", {"chat_id": OWNER})
        bot = FakeBot([text(OWNER, "/status", 40)])
        self.assertTrue(daemon.step(bot, spawn=self.spawn, timeout=0))
        self.assertEqual(store.load("offset", {}), {"next": 41})
        self.assertIn("contest-scout", bot.sent[-1][1])

    def test_pairing_saves_owner_and_clears_code(self):
        store.save("pairing", {"code": "Zq8-pairing-code", "at": config.now().isoformat()})
        bot = FakeBot([text(5555, "/start Zq8-pairing-code", 7)])
        daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(store.load("owner", {}), {"chat_id": 5555})
        self.assertEqual(store.load("pairing", {}), {})
        self.assertEqual(bot.sent[-1][0], 5555)

    def test_expired_pairing_code_is_ignored(self):
        old = (config.now() - timedelta(minutes=11)).isoformat()
        store.save("pairing", {"code": "Zq8-pairing-code", "at": old})
        bot = FakeBot([text(5555, "/start Zq8-pairing-code", 8)])
        daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(store.load("owner", {}), {})

    def test_llm_actions_are_spawned(self):
        store.save("owner", {"chat_id": OWNER})
        store.save("interview", {"id": "a1", "status": "awaiting_answer"})
        daemon.step(FakeBot([text(OWNER, "게임 동아리", 8)]), spawn=self.spawn, timeout=0)
        self.assertEqual(self.spawned, [["answer", "--text=게임 동아리"]])

    def test_text_starting_with_dash_is_passed_safely(self):
        store.save("owner", {"chat_id": OWNER})
        store.save("interview", {"id": "a1", "status": "awaiting_answer"})
        daemon.step(FakeBot([text(OWNER, "-_-", 8)]), spawn=self.spawn, timeout=0)
        from kangtwin import jobs
        args = jobs.parse_args(self.spawned[0])
        self.assertEqual((args.action, args.text), ("answer", "-_-"))

    def test_unexpected_error_in_action_is_reported_and_loop_continues(self):
        store.save("owner", {"chat_id": OWNER})
        bot = FakeBot([text(OWNER, "메모 하나", 20), text(OWNER, "/ask", 21)])
        calls = []

        def flaky(args):
            calls.append(args)
            if args[0] == "memo":
                raise OSError("프로세스 못 띄움")

        daemon.step(bot, spawn=flaky, timeout=0)
        self.assertIn("오류", bot.sent[0][1])
        self.assertEqual(calls[-1], ["ask"])

    def test_send_failure_does_not_block_next_update(self):
        store.save("owner", {"chat_id": OWNER})
        bot = FakeBot([text(OWNER, "/status", 9), text(OWNER, "/ask", 10)], fail_send=True)
        daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(self.spawned, [["ask"]])
        self.assertEqual(store.load("offset", {}), {"next": 11})

    def test_callback_is_acked_and_buttons_cleared(self):
        store.save("owner", {"chat_id": OWNER})
        store.save("interview", {"id": "a1", "status": "proposed"})
        bot = FakeBot([{"update_id": 12, "callback_query": {
            "id": "cb1", "data": "iv:revise:a1", "message": {"message_id": 33, "chat": {"id": OWNER}}}}])
        daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(bot.acked, ["cb1"])
        self.assertEqual(bot.cleared, [(OWNER, 33)])
        self.assertEqual(self.spawned, [["mark_revise"]])

    def test_vault_actions_are_spawned_not_run_in_daemon(self):
        store.save("owner", {"chat_id": OWNER})
        store.save("interview", {"id": "a1", "status": "proposed"})

        def cb(uid, data):
            return {"update_id": uid, "callback_query": {
                "id": "c%d" % uid, "data": data, "message": {"message_id": uid, "chat": {"id": OWNER}}}}

        bot = FakeBot([text(OWNER, "-오늘 메모", 30), cb(31, "iv:apply:a1"), cb(32, "iv:drop:a1")])
        daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(self.spawned, [["memo", "--text=-오늘 메모"], ["apply"], ["close", "--reason=drop"]])

    def test_scheduled_jobs_launch_once_per_slot(self):
        launched = []
        t = datetime(2026, 10, 7, 22, 0, 30, tzinfo=KST)
        store.save("schedule", {"contest-scout": "2026-10-07 08:30"})
        daemon.run_schedule(t, launched.append)
        daemon.run_schedule(t + timedelta(minutes=1), launched.append)
        self.assertEqual(launched, ["interview"])
        self.assertEqual(store.load("schedule", {})["interview"], "2026-10-07 22:00")

    def test_unknown_job_is_not_launched(self):
        launched = []
        with mock.patch.object(daemon.subprocess, "Popen", side_effect=lambda cmd, **kw: launched.append(cmd)):
            daemon.launch_scheduled("linkedin-scout")
        self.assertEqual(launched, [])

    def test_contest_scout_is_launched_as_its_own_job(self):
        launched = []
        with mock.patch.object(daemon.subprocess, "Popen", side_effect=lambda cmd, **kw: launched.append(cmd)):
            daemon.launch_scheduled("contest-scout")
        self.assertEqual(launched[0][1:], ["-m", "kangtwin.contestscout"])

    def test_fund_scout_is_launched_as_its_own_job(self):
        launched = []
        with mock.patch.object(daemon.subprocess, "Popen", side_effect=lambda cmd, **kw: launched.append(cmd)):
            daemon.launch_scheduled("fund-scout")
        self.assertEqual(launched[0][1:], ["-m", "kangtwin.fundscout"])

    def test_funds_command_launches_fund_scout(self):
        store.save("owner", {"chat_id": OWNER})
        launched = []
        bot = FakeBot([text(OWNER, "/funds", 52)])
        with mock.patch.object(daemon, "launch_scheduled", side_effect=launched.append):
            daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(launched, ["fund-scout"])

    def test_contests_command_launches_contest_scout(self):
        store.save("owner", {"chat_id": OWNER})
        launched = []
        bot = FakeBot([text(OWNER, "/contests", 51)])
        with mock.patch.object(daemon, "launch_scheduled", side_effect=launched.append):
            daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(launched, ["contest-scout"])

    def test_contests_command_launches_scout(self):
        store.save("owner", {"chat_id": OWNER})
        launched = []
        bot = FakeBot([text(OWNER, "/contests", 50)])
        with mock.patch.object(daemon, "launch_scheduled", side_effect=launched.append):
            daemon.step(bot, spawn=self.spawn, timeout=0)
        self.assertEqual(launched, ["contest-scout"])

    def test_stale_alert_once_per_day(self):
        store.save("owner", {"chat_id": OWNER})
        t = datetime(2026, 10, 8, 12, 0, tzinfo=KST)
        heartbeat.beat("interview", now=t - timedelta(hours=30))
        bot = FakeBot()
        daemon.check_stale(bot, t)
        daemon.check_stale(bot, t + timedelta(hours=1))
        self.assertEqual(len(bot.sent), 1)
        self.assertIn("interview", bot.sent[0][1])
        daemon.check_stale(bot, t + timedelta(days=1))
        self.assertEqual(len(bot.sent), 2)


if __name__ == "__main__":
    unittest.main()
