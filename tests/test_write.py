import tempfile
import unittest
from pathlib import Path

from kangtwin import llm, write

GOOD = "합류했을 때 회사는 3명이었고, 저는 개발자로 들어가 제품을 만들었습니다."
BAD = "저는 결제 구조를 설계했다."


class FakeAsk:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, mode, payload, skill="kang-twin-interview", deny=(), timeout=420):
        self.calls.append({"mode": mode, "payload": payload, "skill": skill, "deny": list(deny), "timeout": timeout})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ["voice/registers/apply.md", "voice/registers/message.md",
                    "voice/exemplars/apply-2026-09-modoodoc.md", "voice/exemplars/apply-2026-09-kakaopay.md",
                    "facts/profile.md", "projects/namo.md", "stories/dify.md", "claims/ai.md", "inbox/memos.md"]:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("# x\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()


class WriterTest(Base):
    def test_reading_list_excludes_and_inherits_apply_exemplars(self):
        apply = write.reading_list("apply", self.root, exclude=["voice/exemplars/apply-2026-09-modoodoc.md"])
        self.assertEqual(apply["guide"], "voice/registers/apply.md")
        self.assertEqual(apply["exemplars"], ["voice/exemplars/apply-2026-09-kakaopay.md"])
        self.assertIn("projects/namo.md", apply["sources"])
        self.assertNotIn("inbox/memos.md", apply["sources"])
        message = write.reading_list("message", self.root)
        self.assertEqual(len(message["exemplars"]), 2)

    def test_clean_draft_is_returned_without_rewrite(self):
        ask = FakeAsk({"text": GOOD, "sources": ["projects/namo.md"], "unknowns": []})
        out = write.Writer(ask=ask, root=self.root).write("apply", "3인 스타트업 합류", length=200,
                                                          exclude=["voice/exemplars/apply-2026-09-modoodoc.md"])
        self.assertEqual(out["text"], GOOD)
        self.assertEqual(out["rewrites"], 0)
        call = ask.calls[0]
        self.assertEqual((call["mode"], call["skill"]), ("write", "kang-twin-write"))
        self.assertEqual(call["payload"]["length"], 200)
        self.assertEqual(call["payload"]["me"], str(self.root))
        self.assertEqual(call["deny"], [str(self.root / "voice/exemplars/apply-2026-09-modoodoc.md")])
        self.assertEqual(call["timeout"], write.TIMEOUT)

    def test_error_triggers_one_rewrite_with_issues(self):
        ask = FakeAsk({"text": BAD}, {"text": GOOD})
        out = write.Writer(ask=ask, root=self.root).write("apply", "결제 구조")
        self.assertEqual(out["text"], GOOD)
        self.assertEqual(out["rewrites"], 1)
        rewrite = ask.calls[1]
        self.assertEqual(rewrite["mode"], "rewrite")
        self.assertEqual(rewrite["payload"]["text"], BAD)
        self.assertIn("plain-end", [i["code"] for i in rewrite["payload"]["issues"]])

    def test_gives_up_after_one_rewrite(self):
        ask = FakeAsk({"text": BAD}, {"text": BAD})
        out = write.Writer(ask=ask, root=self.root).write("apply", "결제 구조")
        self.assertEqual(out["rewrites"], 1)
        self.assertTrue(any(i[0] == "ERROR" for i in out["issues"]))

    def test_empty_text_is_an_error(self):
        with self.assertRaises(llm.LLMError):
            write.Writer(ask=FakeAsk({"text": "  "}), root=self.root).write("apply", "x")

    def test_unknown_register_is_rejected(self):
        with self.assertRaises(ValueError):
            write.Writer(ask=FakeAsk(), root=self.root).write("blog", "x")


DRAFT = GOOD + " 그래서 매출이 3배로 늘었고, 사용자 경험의 새로운 지평을 열었습니다."
CLEAN_REVIEW = {"facts": [], "criteria": [{"criterion": "창의성 30", "status": "다룸", "note": "제안 배경"}],
                "tone": [], "summary": "고칠 것 없음"}
FINDINGS = {"facts": [{"quote": "매출이 3배로 늘었고", "problem": "근거 없음", "source": "", "note": "매출 숫자 없음"}],
            "criteria": [{"criterion": "창의성 30", "status": "다룸", "note": "제안 배경"},
                         {"criterion": "실현 가능성 30", "status": "빠짐", "note": "구현 계획 없음"}],
            "tone": [{"quote": "사용자 경험의 새로운 지평을 열었습니다", "kind": "AI 말투", "why": "내용 없는 미사여구",
                      "fix": "지운다"},
                     {"quote": "회사는 3명이었고", "kind": "어색한 표현", "why": "예시", "fix": "회사 인원은 3명이었고"},
                     {"quote": "초안에 없는 문장", "kind": "어색한 표현", "why": "예시", "fix": "-"}],
            "summary": "근거 없는 숫자, 실현 가능성 빠짐"}


class ReviewTest(Base):
    def test_clean_review_keeps_the_draft(self):
        ask = FakeAsk({"text": GOOD, "sources": ["projects/namo.md"]}, CLEAN_REVIEW)
        out = write.Writer(ask=ask, root=self.root).write("apply", "공모전 제출물", review=True, criteria=["창의성 30"])
        self.assertEqual((out["text"], out["rewrites"]), (GOOD, 0))
        call = ask.calls[1]
        self.assertEqual((call["mode"], call["skill"]), ("review", "kang-twin-review"))
        self.assertEqual(call["payload"]["text"], GOOD)
        self.assertEqual(call["payload"]["criteria"], ["창의성 30"])
        self.assertEqual(call["payload"]["used"], ["projects/namo.md"])
        self.assertEqual(call["payload"]["brief"], "공모전 제출물")
        self.assertIn("projects/namo.md", call["payload"]["sources"])
        self.assertEqual(out["review"]["criteria"][0]["status"], "다룸")

    def test_findings_trigger_one_rewrite_and_mark_what_was_fixed(self):
        ask = FakeAsk({"text": DRAFT, "unknowns": []}, FINDINGS, {"text": GOOD, "unknowns": ["매출 숫자 확인 필요"]})
        out = write.Writer(ask=ask, root=self.root).write("apply", "공모전 제출물", length=2500, review=True,
                                                          criteria=["창의성 30", "실현 가능성 30"])
        self.assertEqual((out["text"], out["rewrites"]), (GOOD, 1))
        rewrite = ask.calls[2]
        self.assertEqual((rewrite["mode"], rewrite["skill"]), ("rewrite", "kang-twin-write"))
        self.assertEqual(rewrite["payload"]["text"], DRAFT)
        self.assertEqual(rewrite["payload"]["length"], 2500)
        self.assertEqual(rewrite["payload"]["review"]["facts"][0]["quote"], "매출이 3배로 늘었고")
        review = out["review"]
        self.assertEqual(review["facts"][0]["state"], "고침")
        self.assertEqual([t["state"] for t in review["tone"]], ["고침", "남음", "초안에 없는 인용"])
        self.assertIn("매출 숫자 확인 필요", out["unknowns"])

    def test_weak_criterion_alone_triggers_a_rewrite(self):
        weak = {"facts": [], "tone": [], "criteria": [{"criterion": "실현 가능성", "status": "약함", "note": "일정 없음"}]}
        ask = FakeAsk({"text": DRAFT}, weak, {"text": GOOD})
        out = write.Writer(ask=ask, root=self.root).write("apply", "x", review=True)
        self.assertEqual(out["rewrites"], 1)

    def test_malformed_findings_are_dropped(self):
        junk = {"facts": [{"quote": "x", "problem": "괜찮음"}, "문자열"], "tone": [{"quote": "", "kind": "AI 말투"}],
                "criteria": [{"criterion": "c", "status": "모름"}]}
        ask = FakeAsk({"text": GOOD}, junk)
        out = write.Writer(ask=ask, root=self.root).write("apply", "x", review=True)
        self.assertEqual(out["rewrites"], 0)
        self.assertEqual((out["review"]["facts"], out["review"]["tone"], out["review"]["criteria"]), ([], [], []))

    def test_rewrite_that_fails_the_voice_check_is_discarded(self):
        ask = FakeAsk({"text": DRAFT}, FINDINGS, {"text": BAD})
        out = write.Writer(ask=ask, root=self.root).write("apply", "x", review=True)
        self.assertEqual((out["text"], out["rewrites"]), (DRAFT, 0))
        self.assertIn("말투 점검", out["review"]["error"])
        self.assertEqual(out["review"]["facts"][0]["state"], "남음")

    def test_review_failure_keeps_the_draft(self):
        ask = FakeAsk({"text": GOOD}, llm.LLMError("claude 시간 초과 (600s)"))
        out = write.Writer(ask=ask, root=self.root).write("apply", "x", review=True)
        self.assertEqual(out["text"], GOOD)
        self.assertIn("시간 초과", out["review"]["error"])

    def test_review_lines_list_findings_for_the_note(self):
        ask = FakeAsk({"text": DRAFT}, FINDINGS, {"text": GOOD})
        out = write.Writer(ask=ask, root=self.root).write("apply", "x", review=True)
        lines = "\n".join(write.review_lines(out["review"]))
        for part in ("[고침] 사실 근거 없음: \"매출이 3배로 늘었고\"", "심사 기준 빠짐: 실현 가능성 30",
                     "[남음] 어색한 표현: \"회사는 3명이었고\"", "→ 회사 인원은 3명이었고"):
            self.assertIn(part, lines)
        self.assertLess(lines.index("빠짐"), lines.index("다룸"))
        self.assertEqual(write.review_counts(out["review"]), "검토: 사실 1 · 기준 빠짐·약함 1 · 말투 3 → 고쳐 씀, 남은 것 1")
        self.assertEqual(write.review_lines({}), [])
        self.assertEqual(write.review_counts({}), "")


if __name__ == "__main__":
    unittest.main()
