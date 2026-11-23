import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kangtwin import store
from kangtwin.jobs import Jobs

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 7, 22, 0, tzinfo=KST)
OWNER = 1001

EDU = "---\ntype: fact\nupdated: 2026-09-24\n---\n\n# 교육\n\n## 한빛고등학교\n\n- 수석 졸업.\n"


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}

    def last(self):
        return self.sent[-1]


class FakeAsk:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, mode, payload):
        self.calls.append((mode, payload))
        return self.replies.pop(0)


PROPOSE = {
    "action": "propose",
    "summary": "고등학교 게임 동아리 이름과 역할",
    "edits": [{"file": "facts/education.md", "heading": "## 한빛고등학교",
               "line": "- 게임개발 동아리 픽셀 공방, 기획·로직 담당."}],
    "story": None,
}


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": os.path.join(self.tmp.name, "state")})
        self.env.start()
        self.root = Path(self.tmp.name) / "Me"
        (self.root / "facts").mkdir(parents=True)
        (self.root / "facts" / "education.md").write_text(EDU, encoding="utf-8")
        self.bot = FakeBot()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def jobs(self, replies, now=NOW):
        self.ask = FakeAsk(replies)
        return Jobs(self.bot, OWNER, ask=self.ask, root=self.root, clock=lambda: now)

    def test_full_flow_ask_followup_propose_apply(self):
        j = self.jobs([
            {"topic": "학창 시절", "question": "그때 개발 말고 제일 시간 많이 쓴 건?"},
            {"action": "followup", "question": "그 동아리 이름은?"},
            PROPOSE,
        ])
        j.ask()
        iv = store.load("interview", {})
        self.assertEqual(iv["status"], "awaiting_answer")
        self.assertIn("그때 개발 말고", self.bot.last()[1])
        self.assertEqual(self.bot.last()[2][0][0][1], "iv:skip:%s" % iv["id"])

        j.answer("게임 동아리")
        self.assertIn("그 동아리 이름은?", self.bot.last()[1])
        self.assertEqual(store.load("interview", {})["followups_left"], 2)

        j.answer("픽셀 공방, 기획이랑 로직")
        iv = store.load("interview", {})
        self.assertEqual(iv["status"], "proposed")
        self.assertEqual(self.bot.last()[2][0][0], ("반영", "iv:apply:%s" % iv["id"]))
        proposal = self.root / "inbox" / ("interview-2026-10-07-%s.md" % iv["id"])
        self.assertTrue(proposal.exists())

        j.apply()
        edu = (self.root / "facts" / "education.md").read_text(encoding="utf-8")
        self.assertIn("- 게임개발 동아리 픽셀 공방, 기획·로직 담당.", edu)
        self.assertEqual(store.load("interview", {})["status"], "closed")
        self.assertIn("학창 시절", store.load("asked", {}))
        events = (self.root / "events" / "2026-10.md").read_text(encoding="utf-8")
        self.assertIn("facts/education.md", events)
        chat = (self.root / "voice" / "corpus" / "chat" / "2026-10.md").read_text(encoding="utf-8")
        self.assertIn("게임 동아리", chat)
        self.assertIn("픽셀 공방, 기획이랑 로직", chat)
        self.assertIn("반영함", self.bot.last()[1])

    def test_followups_run_out_then_propose_is_forced(self):
        j = self.jobs([
            {"topic": "취미", "question": "운동 함?"},
            {"action": "followup", "question": "q1"},
            {"action": "followup", "question": "q2"},
            {"action": "followup", "question": "q3"},
            PROPOSE,
        ])
        j.ask()
        for answer in ["a0", "a1", "a2", "a3"]:
            j.answer(answer)
        self.assertEqual([m for m, _ in self.ask.calls], ["ask", "answer", "answer", "answer", "propose"])
        self.assertEqual(store.load("interview", {})["status"], "proposed")

    def test_bad_edit_path_retries_once_then_reports_and_writes_nothing(self):
        bad = dict(PROPOSE, edits=[{"file": "../../etc/x.md", "heading": "## a", "line": "- b"}])
        j = self.jobs([{"topic": "t", "question": "q"}, bad, bad])
        before = (self.root / "facts" / "education.md").read_text(encoding="utf-8")
        j.ask()
        j.answer("답")
        self.assertEqual(self.ask.calls[-1][0], "revise")
        self.assertIn("형식", self.bot.last()[1])
        self.assertEqual((self.root / "facts" / "education.md").read_text(encoding="utf-8"), before)
        self.assertFalse(Path(self.tmp.name, "etc").exists())
        self.assertEqual(store.load("interview", {})["status"], "closed")

    def test_busy_lock_replies_processing(self):
        j = self.jobs([])
        with store.lock("interview"):
            j.answer("답")
        self.assertIn("처리 중", self.bot.last()[1])

    def test_recent_topics_are_passed_to_skill(self):
        store.save("asked", {
            "취미": {"date": (NOW - timedelta(days=3)).date().isoformat(), "reason": "skip"},
            "군 생활": {"date": (NOW - timedelta(days=20)).date().isoformat(), "reason": "applied"},
            "가치관": {"date": (NOW - timedelta(days=4)).date().isoformat(), "reason": "later"},
        })
        j = self.jobs([{"topic": "창업", "question": "q"}])
        j.ask()
        recent = self.ask.calls[0][1]["asked_recent"]
        self.assertIn("취미", recent)
        self.assertNotIn("군 생활", recent)
        self.assertNotIn("가치관", recent)

    def test_skip_records_topic_and_closes(self):
        j = self.jobs([{"topic": "취미", "question": "q"}])
        j.ask()
        iv = store.load("interview", {})
        j.close("skip")
        self.assertEqual(store.load("interview", {})["status"], "closed")
        self.assertEqual(store.load("asked", {})["취미"]["reason"], "skip")

    def test_revise_flow(self):
        j = self.jobs([{"topic": "t", "question": "q"}, PROPOSE,
                       dict(PROPOSE, summary="고친 변경안")])
        j.ask()
        j.answer("답")
        j.mark_revise()
        self.assertEqual(store.load("interview", {})["status"], "revising")
        j.revise("역할은 빼줘")
        self.assertEqual(self.ask.calls[-1][1]["instruction"], "역할은 빼줘")
        self.assertIn("고친 변경안", self.bot.last()[1])
        self.assertEqual(store.load("interview", {})["status"], "proposed")

    def test_empty_proposal_closes_without_buttons(self):
        j = self.jobs([{"topic": "t", "question": "q"}, dict(PROPOSE, edits=[])])
        j.ask()
        j.answer("모르겠음")
        self.assertEqual(store.load("interview", {})["status"], "closed")
        self.assertIsNone(self.bot.last()[2])

    def test_new_ask_closes_unanswered_session(self):
        j = self.jobs([{"topic": "t1", "question": "q1"}, {"topic": "t2", "question": "q2"}])
        j.ask()
        first = store.load("interview", {})["id"]
        j.ask()
        iv = store.load("interview", {})
        self.assertNotEqual(iv["id"], first)
        self.assertEqual(iv["topic"], "t2")

    def test_memo_is_appended_to_inbox(self):
        j = self.jobs([])
        j.memo("오늘 Sprout 펌웨어 OTA 붙임")
        memos = (self.root / "inbox" / "memos.md").read_text(encoding="utf-8")
        self.assertIn("오늘 Sprout 펌웨어 OTA 붙임", memos)
        self.assertIn("메모", self.bot.last()[1])

    def test_malformed_answer_reports_and_keeps_waiting(self):
        j = self.jobs([{"topic": "취미", "question": "q"}, {"foo": 1}])
        j.ask()
        j.answer("헬스 함")
        self.assertIn("실패", self.bot.last()[1])
        self.assertEqual(store.load("interview", {})["status"], "awaiting_answer")
        self.assertNotIn("취미", store.load("asked", {}))

    def test_followup_in_propose_mode_is_an_error(self):
        j = self.jobs([{"topic": "t", "question": "q"},
                       {"action": "followup", "question": "q1"},
                       {"action": "followup", "question": "q2"},
                       {"action": "followup", "question": "q3"},
                       {"action": "followup", "question": "또?"}])
        j.ask()
        for a in ["a0", "a1", "a2", "a3"]:
            j.answer(a)
        self.assertIn("실패", self.bot.last()[1])
        self.assertNotEqual(store.load("interview", {})["status"], "closed")

    def test_busy_on_proposal_resends_buttons(self):
        j = self.jobs([{"topic": "t", "question": "q"}, PROPOSE])
        j.ask()
        j.answer("답")
        iid = store.load("interview", {})["id"]
        with store.lock("interview"):
            j.apply()
        self.assertIn("처리 중", self.bot.last()[1])
        self.assertEqual(self.bot.last()[2][0][0], ("반영", "iv:apply:%s" % iid))

    def test_apply_failure_resends_buttons(self):
        j = self.jobs([{"topic": "t", "question": "q"}, PROPOSE])
        j.ask()
        j.answer("답")
        iv = store.load("interview", {})
        iv["proposal"]["edits"] = [{"file": "../x.md", "heading": "## a", "line": "- b"}]
        store.save("interview", iv)
        j.apply()
        self.assertIn("반영 실패", self.bot.last()[1])
        self.assertIsNotNone(self.bot.last()[2])

    def test_scheduled_ask_with_pending_proposal_resends_it(self):
        j = self.jobs([{"topic": "t", "question": "q"}, PROPOSE])
        j.ask()
        j.answer("답")
        iid = store.load("interview", {})["id"]
        calls = len(self.ask.calls)
        j.ask()
        self.assertEqual(len(self.ask.calls), calls)
        self.assertEqual(store.load("interview", {})["id"], iid)
        self.assertIn("대기", self.bot.last()[1])
        self.assertEqual(self.bot.last()[2][0][0], ("반영", "iv:apply:%s" % iid))

    def test_cli_reports_crash(self):
        from kangtwin import jobs as jobs_mod
        notes = []

        class Boom:
            def answer(self, text):
                raise RuntimeError("터짐")

        with self.assertRaises(RuntimeError):
            jobs_mod.main(["answer", "--text=x"], build=lambda: Boom(), notify=notes.append)
        self.assertIn("터짐", notes[0])

    def test_apply_without_proposal_explains(self):
        j = self.jobs([])
        j.apply()
        self.assertIn("반영할 변경안이 없음", self.bot.last()[1])


if __name__ == "__main__":
    unittest.main()
