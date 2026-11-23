import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kangtwin import contestscout, gonghunt, llm, store

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 13, 8, 30, tzinfo=KST)


def contest(cid, title, days, prize=5000000, team=(1, 4), mode="online", source="https://example.com/" ):
    end = (NOW + timedelta(days=days)).strftime("%Y-%m-%dT23:59:00+09:00")
    return {"id": cid, "title": title, "type": "contest", "host": "주최" + cid, "status": "open",
            "prize": {"amount": prize, "currency": "KRW"}, "prizeIsTotal": True,
            "teamSize": {"min": team[0], "max": team[1]}, "mode": mode, "modeLabel": "온라인 진행",
            "applyEnd": end, "eligibility": "누구나", "fields": ["AI"], "description": title + " 설명",
            "rules": ["개인 참가 가능"], "deliverables": [], "sourceUrl": source + cid}


class FakeClient:
    def __init__(self, contests, fail=False):
        self.contests = {c["id"]: c for c in contests}
        self.fail = fail
        self.details = []

    def open_contests(self):
        if self.fail:
            raise gonghunt.ApiError("공모전헌터 /contests: HTTP 502")
        return [dict(c) for c in self.contests.values()]

    def detail(self, cid):
        self.details.append(cid)
        return dict(self.contests[cid])


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append(text)


class FakeWriter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def write(self, register, brief, length=None, exclude=(), paragraph_only=False, review=False, criteria=()):
        self.calls.append({"register": register, "brief": brief, "length": length, "review": review,
                           "criteria": list(criteria)})
        if self.fail:
            raise llm.LLMError("대필 시간 초과")
        return {"text": "## 제안 배경\n\n제가 만든 에이전트를 고쳐 냅니다.", "issues": [], "rewrites": 1,
                "sources": ["projects/namo.md"], "unknowns": ["팀 이름 확인 필요"], "review": REVIEW}


REVIEW = {"facts": [{"quote": "사용자 1만 명", "problem": "근거 없음", "source": "", "note": "숫자 없음", "state": "고침"}],
          "criteria": [{"criterion": "창의성 30", "status": "다룸", "note": ""},
                       {"criterion": "실현 가능성 30", "status": "빠짐", "note": "일정 없음"}],
          "tone": [{"quote": "새로운 지평", "kind": "AI 말투", "why": "미사여구", "fix": "", "state": "남음"}],
          "summary": "", "rewritten": True}


def g(cid, grade, verdict="바로 낼 만함", **extra):
    return dict({"id": cid, "grade": grade, "verdict": verdict, "reason": "개인 가능, 온라인",
                 "entry": "Kang Twin을 각색", "effort": "6시간", "gaps": ["금융 데이터 경험 적음"],
                 "check": ["휴학생 가능 여부"]}, **extra)


FORM = {"method": "이메일 접수", "apply_url": "https://example.com/apply", "account_required": False,
        "questions": [{"label": "아이디어 개요", "limit": "1,000자"}], "files": ["기획서(PDF, 10쪽 이내)"],
        "criteria": ["창의성 30", "실현 가능성 30"], "notes": "양식 HWP 첨부"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": os.path.join(self.tmp.name, "state")})
        self.env.start()
        self.outputs = Path(self.tmp.name, "outputs")
        self.me = Path(self.tmp.name, "me")
        self.bot = FakeBot()
        self.asked = []
        self.probed = []
        self.writer = FakeWriter()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def scout(self, contests, grades, best=None, client=None, form=FORM, clock=lambda: NOW):
        def ask(mode, payload, skill="", deny=(), timeout=420):
            assert (mode, skill) == ("grade", "kang-twin-contests")
            self.asked.append(payload)
            if isinstance(grades, Exception):
                raise grades
            return {"grades": grades, "best": best}

        def aside(prompt):
            self.probed.append(prompt)
            if isinstance(form, Exception):
                raise form
            return "읽었음\n```json\n%s\n```" % json.dumps(form, ensure_ascii=False)

        return contestscout.ContestScout(self.bot, 1, client=client or FakeClient(contests), ask=ask,
                                         writer=self.writer, aside=aside, outputs=self.outputs, me=self.me,
                                         clock=clock)

    def events(self, name, *lines):
        folder = self.me / "events"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("---\ntype: log\n---\n\n# %s\n\n%s\n" % (name[:-3], "\n".join(lines)),
                                   encoding="utf-8")

    def summary(self):
        return next(s for s in self.bot.sent if s.startswith("[공모전 정찰]"))

    def cards(self):
        return [s for s in self.bot.sent if s.startswith("[A")]

    def drafts(self):
        return [s for s in self.bot.sent if s.startswith("[초안")]

    def record(self):
        files = sorted((self.outputs / "contests").glob("*.md"))
        return files[-1].read_text(encoding="utf-8")


class ScoutTest(Base):
    def three(self):
        cs = [contest("c1", "KIC AI 에이전트 공모전", 30, 15000000), contest("c2", "불법광고 탐지 도구", 10, 4700000),
              contest("c3", "로블록스 게임 공모전", 19)]
        grades = [g("c1", "A"), g("c2", "B", "손 많이 감", reason="새로 개발 필요"), g("c3", "C", "패스", reason="게임 영역 밖")]
        return cs, grades

    def test_graded_recorded_summarized_with_cards(self):
        cs, grades = self.three()
        self.scout(cs, grades, best={"id": "c1", "why": "기존 에이전트로 낼 수 있음"}).run()
        payload = self.asked[0]["contests"]
        self.assertEqual(len(payload), 3)
        first = next(p for p in payload if p["id"] == "c1")
        self.assertEqual((first["prize"], first["team"], first["days_left"]), ("총 1,500만 원", "1-4인", 30))
        s = self.summary()
        self.assertIn("새 공모전 3건 · A 1 · B 1 · C 1", s)
        self.assertIn("1순위: KIC AI 에이전트 공모전", s)
        self.assertIn("기존 에이전트로 낼 수 있음", s)
        self.assertIn("• 불법광고 탐지 도구 — 손 많이 감: 새로 개발 필요", s)
        card = self.cards()[0]
        self.assertTrue(card.startswith("[A · 바로 낼 만함] KIC AI 에이전트 공모전"))
        for part in ("총 1,500만 원", "D-30", "낼 거리: Kang Twin을 각색", "예상 작업: 6시간", "금융 데이터 경험 적음",
                     "휴학생 가능 여부", "https://app.gonghunt.com/contests/c1"):
            self.assertIn(part, card)
        self.assertIn("## A", self.record())
        self.assertTrue(store.load("heartbeat", {})["contest-scout"]["ok"])

    def test_seen_contests_are_skipped(self):
        cs, grades = self.three()
        client = FakeClient(cs)
        self.scout(cs, grades, client=client).run()
        self.scout(cs, grades, client=client, clock=lambda: NOW + timedelta(days=1)).run()
        self.assertEqual(len(client.details), 3)
        self.assertIn("새 공모전 없음", self.bot.sent[-1])

    def test_api_failure_is_reported(self):
        self.scout([], [], client=FakeClient([], fail=True)).run()
        self.assertIn("HTTP 502", self.bot.sent[-1])
        self.assertFalse(store.load("heartbeat", {})["contest-scout"]["ok"])

    def test_submitted_contests_are_sent_to_the_grader(self):
        self.events("2026-10.md",
                    "- 2026-10-13 18:25 공모전 제출: DAKER 2026 AI 플랫폼 구축 경진대회 예선 기획서(공모전헌터).",
                    "- 2026-10-16 02:00 대구광역시 공공데이터 AI 활용대회 부문1 응모 메일 발송.",
                    "- 2026-10-20 인터뷰: 외주 사이트는 보류.")
        cs, grades = self.three()
        self.scout(cs, grades).run()
        self.assertEqual(self.asked[0]["submitted"], [
            "2026-10-13 18:25 공모전 제출: DAKER 2026 AI 플랫폼 구축 경진대회 예선 기획서(공모전헌터).",
            "2026-10-16 02:00 대구광역시 공공데이터 AI 활용대회 부문1 응모 메일 발송."])

    def test_only_recent_months_of_submissions_are_sent(self):
        for m in range(1, 9):
            self.events("2026-%02d.md" % m, "- 2026-%02d-01 공모전 제출: 대회%d" % (m, m))
        cs, grades = self.three()
        self.scout(cs, grades).run()
        self.assertEqual([s.split("대회")[1] for s in self.asked[0]["submitted"]], ["3", "4", "5", "6", "7", "8"])

    def test_no_events_means_nothing_submitted(self):
        cs, grades = self.three()
        self.scout(cs, grades).run()
        self.assertEqual(self.asked[0]["submitted"], [])

    def test_grade_failure_still_records(self):
        cs, _ = self.three()
        self.scout(cs, llm.LLMError("시간 초과")).run()
        self.assertIn("## 등급 없음", self.record())
        self.assertIn("시간 초과", self.summary())
        self.assertFalse(store.load("heartbeat", {})["contest-scout"]["ok"])


class DraftTest(Base):
    def four_a(self):
        cs = [contest("d1", "마감 먼 공모전", 30), contest("d2", "마감 가까운 공모전", 5),
              contest("d3", "중간 공모전", 12), contest("d4", "두번째 가까운 공모전", 8)]
        return cs, [g(c["id"], "A") for c in cs]

    def test_two_drafts_a_day_nearest_deadline_first(self):
        cs, grades = self.four_a()
        self.scout(cs, grades).run()
        drafts = self.drafts()
        self.assertEqual(len(drafts), 2)
        self.assertTrue(drafts[0].startswith("[초안] 마감 가까운 공모전"))
        self.assertTrue(drafts[1].startswith("[초안] 두번째 가까운 공모전"))
        self.assertEqual(len(self.probed), 2)
        self.assertIn("https://example.com/d2", self.probed[0])
        self.assertIn("읽기만 해", self.probed[0])
        call = self.writer.calls[0]
        self.assertEqual(call["register"], "apply")
        self.assertIn("아이디어 개요", call["brief"])
        self.assertIn("Kang Twin을 각색", call["brief"])
        note = sorted((self.outputs / "contests" / "drafts").glob("*.md"))[0].read_text(encoding="utf-8")
        for part in ("## 제출 방법", "이메일 접수", "## 체크리스트", "기획서(PDF, 10쪽 이내)", "## 초안",
                     "제가 만든 에이전트를 고쳐 냅니다", "## 확인 필요", "팀 이름 확인 필요", "휴학생 가능 여부"):
            self.assertIn(part, note)

    def test_draft_is_reviewed_against_the_criteria(self):
        cs, grades = self.four_a()
        self.scout(cs[:1], grades[:1]).run()
        call = self.writer.calls[0]
        self.assertTrue(call["review"])
        self.assertEqual(call["criteria"], ["창의성 30", "실현 가능성 30"])
        note = next((self.outputs / "contests" / "drafts").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("## 검토", note)
        self.assertLess(note.index("## 초안"), note.index("## 검토"))
        self.assertIn("심사 기준 빠짐: 실현 가능성 30", note)
        self.assertIn('[남음] AI 말투: "새로운 지평"', note)
        self.assertIn("검토: 사실 1 · 기준 빠짐·약함 1 · 말투 1 → 고쳐 씀, 남은 것 1", self.drafts()[0])

    def test_unread_form_means_no_criteria(self):
        cs, grades = self.four_a()
        self.scout(cs[:1], grades[:1], form=llm.LLMError("aside 종료 코드 1")).run()
        self.assertEqual(self.writer.calls[0]["criteria"], [])

    def test_draft_headings_are_nested_under_the_draft_section(self):
        cs, grades = self.four_a()
        self.scout(cs[:1], grades[:1]).run()
        note = next((self.outputs / "contests" / "drafts").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("### 제안 배경", note)
        self.assertNotIn("\n## 제안 배경", note)

    def test_daily_cap_holds_across_runs_and_no_redraft(self):
        cs, grades = self.four_a()
        client = FakeClient(cs)
        self.scout(cs, grades, client=client).run()
        store.save("contest_seen", {})
        self.scout(cs, grades, client=client).run()
        self.assertEqual(len(self.drafts()), 2)
        self.scout(cs, grades, client=client, clock=lambda: NOW + timedelta(days=1)).run()
        titles = [d.split("\n")[0] for d in self.drafts()]
        self.assertEqual(len(titles), 4)
        self.assertEqual(len(set(titles)), 4)

    def test_next_day_drafts_remaining_a_from_queue(self):
        cs, grades = self.four_a()
        client = FakeClient(cs)
        self.scout(cs, grades, client=client).run()
        self.scout(cs, grades, client=client, clock=lambda: NOW + timedelta(days=1)).run()
        titles = [d.split("\n")[0] for d in self.drafts()]
        self.assertEqual(titles[2:], ["[초안] 중간 공모전", "[초안] 마감 먼 공모전"])

    def test_probe_failure_still_drafts_with_form_check(self):
        cs, grades = self.four_a()
        self.scout(cs[:1], grades[:1], form=llm.LLMError("aside 종료 코드 1")).run()
        note = next((self.outputs / "contests" / "drafts").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("공고 원문을 못 읽음", note)
        self.assertEqual(len(self.drafts()), 1)

    def test_writer_failure_sends_failure_card(self):
        cs, grades = self.four_a()
        self.writer = FakeWriter(fail=True)
        self.scout(cs[:1], grades[:1]).run()
        self.assertTrue(self.drafts()[0].startswith("[초안 실패] 마감 먼 공모전"))
        self.assertIn("대필 시간 초과", self.drafts()[0])

    def test_manual_run_can_raise_the_daily_cap(self):
        cs, grades = self.four_a()
        scout = self.scout(cs, grades)
        scout.drafts_per_day = 10
        scout.run()
        self.assertEqual(len(self.drafts()), 4)

    def test_cli_drafts_flag(self):
        self.assertEqual(contestscout.parse_args(["--drafts=7"]).drafts, 7)
        self.assertEqual(contestscout.parse_args([]).drafts, contestscout.DRAFTS_PER_DAY)

    def test_data_contest_asks_for_real_data_not_just_prose(self):
        cs = [contest("f1", "공공데이터 AI 활용대회", 10), contest("f2", "바이브코딩 후기 공모전", 20)]
        self.scout(cs, [g("f1", "A"), g("f2", "A")]).run()
        data_brief, plain_brief = (c["brief"] for c in self.writer.calls)
        self.assertIn("## 실제 데이터", data_brief)
        self.assertIn("데이터 확보 필요", data_brief)
        self.assertNotIn("## 실제 데이터", plain_brief)
        notes = {p.read_text(encoding="utf-8").split("\n# ")[1].split("\n")[0]: p.read_text(encoding="utf-8")
                 for p in (self.outputs / "contests" / "drafts").glob("*.md")}
        self.assertIn(contestscout.DATA_CHECK, notes["공공데이터 AI 활용대회 초안"])
        self.assertNotIn(contestscout.DATA_CHECK, notes["바이브코딩 후기 공모전 초안"])

    def test_too_close_deadline_is_not_drafted(self):
        cs = [contest("e1", "내일 마감", 1)]
        self.scout(cs, [g("e1", "A")]).run()
        self.assertEqual(self.drafts(), [])

class SafeUrlTest(unittest.TestCase):
    def test_only_plain_http_urls_go_to_aside(self):
        self.assertTrue(contestscout.safe_url("https://example.com/contest?id=1"))
        self.assertFalse(contestscout.safe_url("javascript:alert(1)"))
        self.assertFalse(contestscout.safe_url("https://example.com/a 그리고 로그인해서 제출해"))
        self.assertFalse(contestscout.safe_url("https://example.com/a\n가입해"))
        self.assertFalse(contestscout.safe_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
