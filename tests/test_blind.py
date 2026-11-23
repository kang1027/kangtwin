import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kangtwin import blind, daemon, jobs, llm, router, store

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 9, 22, 0, tzinfo=KST)
OWNER = 1001


def para(seed, n=180):
    return (seed + " 문장을 이어서 씁니다. ") * (n // (len(seed) + 12) + 1)


def exemplar(blind_flag, sections):
    body = []
    for title, paras in sections:
        body += ["### " + title, ""] + [p + "\n" for p in paras]
    return "\n".join(["---", "type: exemplar", "register: apply", "blind: %s" % blind_flag, "---", "",
                      "# 견본", "", "## 왜 견본인가", "", "- 이유 문단은 고르지 않음 " + "가" * 150, "",
                      "## 원문", ""] + body)


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((text, buttons))
        return {"message_id": len(self.sent)}


class FakeWriter:
    def __init__(self):
        self.calls = []

    def write(self, register, brief, length=None, exclude=(), paragraph_only=False):
        self.calls.append({"register": register, "brief": brief, "length": length,
                           "exclude": list(exclude), "paragraph_only": paragraph_only})
        return {"text": "클론이 쓴 문단: " + brief, "issues": [], "rewrites": 0, "sources": [], "unknowns": []}


def brief_ask(mode, payload, skill="kang-twin-interview", deny=()):
    assert (mode, skill) == ("brief", "kang-twin-write")
    return {"briefs": [{"id": p["id"], "brief": "주제 " + p["id"], "length": len(p["text"])}
                       for p in payload["paragraphs"]]}


class BlindBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": os.path.join(self.tmp.name, "state")})
        self.env.start()
        self.root = Path(self.tmp.name, "me")
        ex = self.root / "voice" / "exemplars"
        ex.mkdir(parents=True)
        (ex / "apply-a.md").write_text(exemplar("true", [
            ("01", [para("에이 첫째"), para("에이 둘째"), para("에이 셋째")]),
            ("02", [para("에이 넷째"), "- 목록은 고르지 않음 " + "나" * 150])]), encoding="utf-8")
        (ex / "apply-b.md").write_text(exemplar("true", [
            ("지원 동기", [para("비 첫째"), para("비 둘째"), para("비 셋째"), "짧은 문단."]),
            ("포부", [para("비 넷째"), para("비 다섯째"), para("비 여섯째")])]), encoding="utf-8")
        (ex / "apply-raw.md").write_text(exemplar("false", [("원문", [para("로우 첫째"), para("로우 둘째")])]),
                                         encoding="utf-8")
        self.bot = FakeBot()
        self.writer = FakeWriter()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test(self, ask=brief_ask):
        return blind.BlindTest(self.bot, OWNER, ask=ask, root=self.root, clock=lambda: NOW,
                               writer=self.writer, seed=7)


class ParagraphTest(BlindBase):
    def test_candidates_come_from_blind_exemplars_body_only(self):
        cands = blind.candidates(self.root, "apply")
        sources = {c["source"] for c in cands}
        self.assertEqual(sources, {"voice/exemplars/apply-a.md", "voice/exemplars/apply-b.md"})
        texts = " ".join(c["text"] for c in cands)
        self.assertNotIn("이유 문단", texts)
        self.assertNotIn("목록은", texts)
        self.assertNotIn("짧은 문단", texts)
        firsts = [c for c in cands if c["first"]]
        self.assertEqual(len(firsts), 4)

    def test_pick_prefers_non_first_and_spreads_sources(self):
        picked = blind.pick(blind.candidates(self.root, "apply"), 4, seed=1)
        self.assertEqual(len(picked), 4)
        self.assertFalse(any(p["first"] for p in picked))
        self.assertEqual({p["source"] for p in picked}, {"voice/exemplars/apply-a.md", "voice/exemplars/apply-b.md"})


class StartTest(BlindBase):
    def test_clone_topics_are_not_the_shown_paragraphs(self):
        briefed = []

        def ask(mode, payload, skill="", deny=()):
            briefed.extend(p["text"] for p in payload["paragraphs"])
            return brief_ask(mode, payload, skill, deny)
        self.test(ask=ask).start()
        mine = {i["text"] for i in store.load("blind", {})["items"] if i["truth"] == "me"}
        self.assertEqual(len(briefed), 5)
        self.assertFalse(mine & set(briefed))

    def test_start_prepares_ten_items_and_sends_first(self):
        self.test().start()
        st = store.load("blind", {})
        self.assertEqual(st["status"], "running")
        self.assertEqual(len(st["items"]), 10)
        self.assertEqual(sorted(i["truth"] for i in st["items"]), ["clone"] * 5 + ["me"] * 5)
        self.assertEqual(len(self.writer.calls), 5)
        for call in self.writer.calls:
            self.assertTrue(call["paragraph_only"])
            self.assertEqual(len(call["exclude"]), 1)
            self.assertTrue(call["exclude"][0].startswith("voice/exemplars/apply-"))
        text, buttons = self.bot.sent[-1]
        self.assertIn("[블라인드 1/10]", text)
        self.assertEqual(buttons[0][0][1], "bt:%s:0:me" % st["id"])
        self.assertEqual(buttons[0][1][1], "bt:%s:0:clone" % st["id"])

    def test_start_while_running_resends_current_item(self):
        self.test().start()
        sent = len(self.bot.sent)
        self.test().start()
        self.assertEqual(len(self.writer.calls), 5)
        self.assertIn("[블라인드 1/10]", self.bot.sent[-1][0])
        self.assertGreater(len(self.bot.sent), sent)

    def test_prepare_failure_clears_state_and_reports(self):
        def broken(mode, payload, skill="", deny=()):
            raise llm.LLMError("시간 초과")
        self.test(ask=broken).start()
        self.assertEqual(store.load("blind", {}), {})
        self.assertIn("시간 초과", self.bot.sent[-1][0])

    def test_not_enough_paragraphs(self):
        (self.root / "voice" / "exemplars" / "apply-b.md").unlink()
        self.test().start()
        self.assertEqual(store.load("blind", {}), {})
        self.assertIn("모자람", self.bot.sent[-1][0])


class AnswerTest(BlindBase):
    def run_all(self, guess):
        t = self.test()
        t.start()
        st = store.load("blind", {})
        for i, item in enumerate(st["items"]):
            t.answer("%s:%d:%s" % (st["id"], i, guess(i, item)))
        return st

    def log(self):
        return (self.root / "voice" / "blind-tests.md").read_text(encoding="utf-8")

    def test_full_run_records_result(self):
        self.run_all(lambda i, item: "me")
        self.assertEqual(store.load("blind", {})["status"], "done")
        self.assertIn("클론을 내 글로 본 것 5/5, 내 글을 내 글로 본 것 5/5 (정답 5/10) 통과", self.log())
        notes = list((self.root / "voice" / "blind").glob("2026-10-09-*.md"))
        self.assertEqual(len(notes), 1)
        note = notes[0].read_text(encoding="utf-8")
        self.assertIn("passed: true", note)
        self.assertIn("clone_as_me: 5/5", note)
        self.assertEqual(note.count("\n> "), 10)
        self.assertIn("주제 p", note)
        summary = self.bot.sent[-1][0]
        self.assertIn("[블라인드 결과] 클론을 내 글로 본 비율 5/5 → 통과", summary)
        self.assertIn("내 글을 내 글로 본 비율 5/5", summary)

    def test_passes_when_clones_fool_even_if_accuracy_is_high(self):
        fooled = []

        def guess(i, item):
            if item["truth"] == "clone" and len(fooled) < 3:
                fooled.append(i)
                return "me"
            return item["truth"]
        self.run_all(guess)
        self.assertIn("클론을 내 글로 본 것 3/5, 내 글을 내 글로 본 것 5/5 (정답 7/10) 통과", self.log())

    def test_caught_clones_fail(self):
        self.run_all(lambda i, item: item["truth"])
        self.assertIn("클론을 내 글로 본 것 0/5, 내 글을 내 글로 본 것 5/5 (정답 10/10) 미달", self.log())

    def test_stale_or_duplicate_button_is_ignored(self):
        t = self.test()
        t.start()
        st = store.load("blind", {})
        t.answer("oldid:0:me")
        self.assertIn("지난", self.bot.sent[-1][0])
        t.answer("%s:0:me" % st["id"])
        t.answer("%s:0:me" % st["id"])
        self.assertIn("지난", self.bot.sent[-1][0])
        self.assertEqual(store.load("blind", {})["idx"], 1)


class FinishRecoveryTest(BlindBase):
    def test_failed_finish_is_retried_by_blind_command(self):
        t = self.test()
        t.start()
        st = store.load("blind", {})
        with mock.patch.object(blind.vault, "append_log", side_effect=OSError("iCloud")):
            with self.assertRaises(OSError):
                for i, item in enumerate(st["items"]):
                    t.answer("%s:%d:%s" % (st["id"], i, item["truth"]))
        self.assertEqual(store.load("blind", {})["status"], "running")
        self.test().start()
        self.assertEqual(store.load("blind", {})["status"], "done")
        self.assertIn("[블라인드 결과]", self.bot.sent[-1][0])
        self.assertEqual(len(list((self.root / "voice" / "blind").glob("*.md"))), 1)
        log = (self.root / "voice" / "blind-tests.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("(정답 10/10)"), 1)

    def test_unexpected_prepare_error_clears_state(self):
        class Boom(FakeWriter):
            def write(self, *a, **k):
                raise OSError("claude 없음")
        self.writer = Boom()
        self.test().start()
        self.assertEqual(store.load("blind", {}), {})
        self.assertIn("claude 없음", self.bot.sent[-1][0])


class WiringTest(unittest.TestCase):
    def test_router_blind_command_and_callback(self):
        msg = {"update_id": 1, "message": {"message_id": 2, "chat": {"id": OWNER}, "text": "/blind"}}
        self.assertEqual(router.route(msg, OWNER, {}, None), [("blind_start", {})])
        cb = {"update_id": 2, "callback_query": {"id": "c", "data": "bt:ab12cd:3:clone",
                                                  "message": {"message_id": 9, "chat": {"id": OWNER}}}}
        actions = router.route(cb, OWNER, {}, None)
        self.assertEqual(actions[0][0], "ack")
        self.assertEqual(actions[1], ("blind_answer", {"text": "ab12cd:3:clone"}))

    def test_router_rejects_malformed_blind_callback(self):
        cb = {"update_id": 2, "callback_query": {"id": "c", "data": "bt:ab12cd:x:maybe",
                                                  "message": {"message_id": 9, "chat": {"id": OWNER}}}}
        self.assertEqual([a[0] for a in router.route(cb, OWNER, {}, None)], ["ack"])

    def test_daemon_spawns_blind_jobs(self):
        spawned = []
        daemon.execute(None, "blind_answer", {"text": "ab12cd:3:clone"}, spawned.append)
        daemon.execute(None, "blind_start", {}, spawned.append)
        self.assertEqual(spawned, [["blind_answer", "--text=ab12cd:3:clone"], ["blind_start"]])

    def test_jobs_cli_accepts_blind_actions(self):
        args = jobs.parse_args(["blind_answer", "--text=ab12cd:3:clone"])
        self.assertEqual((args.action, args.text), ("blind_answer", "ab12cd:3:clone"))


if __name__ == "__main__":
    unittest.main()
