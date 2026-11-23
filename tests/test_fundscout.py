import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kangtwin import fundscout, fundsources, llm, store

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=KST)
TODAY = NOW.date()


def n(source, sid, title, days=20, **extra):
    end = (TODAY + timedelta(days=days)).isoformat() if days is not None else ""
    return fundsources.notice(source, sid, title=title, org="기관" + sid, url="https://example.com/" + sid,
                              end=end, **extra)


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": os.path.join(self.tmp.name, "state")})
        self.env.start()
        self.outputs = Path(self.tmp.name, "outputs")
        self.bot = FakeBot()
        self.asked = []
        self.reminders = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_scout(self, notices, grades=(), errors=None, counts=None, clock=lambda: NOW):
        def ask(mode, payload, skill="", deny=(), timeout=420):
            assert (mode, skill) == ("grade", "kang-twin-funds")
            self.asked.append(payload)
            if isinstance(grades, Exception):
                raise grades
            return {"grades": list(grades)}

        def collect(http, key, seen):
            got = [dict(x) for x in notices]
            return got, counts if counts is not None else {s: 5 for s in fundsources.SOURCES}, dict(errors or {})

        with mock.patch.object(fundsources, "collect", collect):
            fundscout.FundScout(self.bot, 1, ask=ask, outputs=self.outputs, clock=clock, key="k",
                                add_reminder=lambda at, text: self.reminders.append((at, text))).run()

    def summary(self):
        return next(s for s in self.bot.sent if s.startswith("[자금 정찰]"))

    def cards(self):
        return [s for s in self.bot.sent if s.startswith("[A ")]

    def record(self):
        return sorted((self.outputs / "funds").glob("*.md"))[-1].read_text(encoding="utf-8")


class RulesTest(unittest.TestCase):
    def rule(self, notice):
        return fundscout.rules(notice, TODAY)

    def test_loans_are_dropped_but_ir_in_finance_is_kept(self):
        self.assertEqual(self.rule(n("egbiz", "1", "2026 청년전용창업자금 융자 공고"))[0], "대출·보증")
        self.assertEqual(self.rule(n("egbiz", "2", "중소기업 지원 안내", field="금융"))[0], "대출·보증")
        drop, c, tags, kind = self.rule(n("egbiz", "3", "2026년 WIXG 경기도 G-펀드 투자상담회", field="금융"))
        self.assertEqual((drop, c, kind), (None, None, "ir"))
        self.assertIn("IR", tags)

    def test_expired_is_dropped(self):
        self.assertEqual(self.rule(n("egbiz", "1", "창업 지원사업", days=-1))[0], "마감 지남")

    def test_pre_founder_only_is_c_but_mixed_tracks_pass(self):
        self.assertEqual(self.rule(n("kstartup", "1", "예비창업 지원", years="예비창업자"))[1], "예비 전용")
        self.assertEqual(self.rule(n("bizinfo", "2", "창업 아이디어 지원",
                                     target="공고일 기준 사업자등록(개인, 법인)이 없는 자"))[1], "예비 전용")
        self.assertIsNone(self.rule(n("bizinfo", "3", "창업중심대학 지역기반",
                                      target="사업자등록이 없는 예비창업자 및 7년 이내 창업기업"))[1])

    def test_years_window(self):
        self.assertIsNone(self.rule(n("kstartup", "1", "초기창업패키지", years="2년미만,3년미만"))[1])
        self.assertEqual(self.rule(n("kstartup", "2", "1년 미만 지원", years="1년미만"))[1], "업력 안 맞음")
        self.assertEqual(self.rule(n("kstartup", "3", "도약", years="3년이상,7년미만"))[1], None)
        self.assertEqual(fundscout.rules(n("kstartup", "4", "x", days=400, years="2년미만"), date(2027, 8, 1))[1], "업력 안 맞음")

    def test_region(self):
        self.assertEqual(self.rule(n("venturesquare", "1", "[대전창조경제혁신센터] 웰컴 스테이 지원사업"))[1], "지역 안 맞음")
        self.assertEqual(self.rule(n("kstartup", "2", "로컬 창업", region="충남"))[1], "지역 안 맞음")
        self.assertIsNone(self.rule(n("kstartup", "3", "창업 지원", region="경기"))[1])
        self.assertIsNone(self.rule(n("egbiz", "4", "(광주) 창업 지원사업", region="경기 권역구분없음"))[1])
        self.assertEqual(self.rule(n("bizinfo", "5", "프리팁스", target="비수도권 소재 창업기업"))[1], "지역 안 맞음")

    def test_tags(self):
        _, c, tags, _ = self.rule(n("kstartup", "1", "2027년 초기창업패키지 모집", target="법인사업자만 신청 가능"))
        self.assertIsNone(c)
        self.assertEqual(tags, ["평생 한 번", "법인 필요"])
        self.assertIn("주소 이전 필요", self.rule(n("venturesquare", "2", "청년관 입주기업 모집",
                                                 summary="입주 후 본사 이전 의무"))[2])

    def test_education_and_forums_are_c_unless_they_lead_to_money(self):
        self.assertEqual(self.rule(n("kstartup", "1", "창업 초보를 위한 창업 A-Z 교육"))[1], "교육·행사만")
        self.assertEqual(self.rule(n("kstartup", "2", "NCI 민/관/학 창업포럼 참관객 모집"))[1], "교육·행사만")
        self.assertIsNone(self.rule(n("kstartup", "3", "청년 창업 아카데미 수료생 사업화 지원"))[1])
        self.assertIsNone(self.rule(n("kstartup", "4", "공동 IR DAY 세미나 참가기업 모집"))[1])

    def test_sector_and_age(self):
        self.assertEqual(self.rule(n("egbiz", "1", "소규모 음식점 감량기 지원"))[1], "대상 안 맞음")
        self.assertEqual(self.rule(n("kstartup", "2", "중장년 창업", ages="만 40세 이상"))[1], "대상 안 맞음")


class ScoutTest(Base):
    def three(self):
        notices = [n("kstartup", "1", "2027년 초기창업패키지 모집", days=30, years="3년미만"),
                   n("venturesquare", "2", "의정부 FIT데이 IR 참가기업 모집", days=9),
                   n("egbiz", "3", "경기도 해외 전시회 참가기업 모집", days=10),
                   n("egbiz", "4", "청년전용창업자금 융자"),
                   n("venturesquare", "5", "[대전창조경제혁신센터] 웰컴 스테이 지원사업"),
                   n("egbiz", "6", "수원 창업공간 입주기업 모집", days=9)]
        grades = [{"id": "kstartup:1", "grade": "A", "kind": "grant", "reason": "업력 3년 이내, 개인사업자 가능",
                   "gain": "최대 1억 원", "entry": "공모전헌터 사업계획서", "prep": ["사업계획서"],
                   "check": ["평생 한 번: 어느 트랙을 쓸지 먼저 정하기"]},
                  {"id": "venturesquare:2", "grade": "B", "kind": "ir", "reason": "IR 덱 필요",
                   "gain": "투자자 IR 평가", "check": ["IR 덱 준비"]},
                  {"id": "egbiz:3", "grade": "C", "kind": "grant", "reason": "수출 교육"},
                  {"id": "egbiz:6", "grade": "B", "kind": "grant", "reason": "입주 공간", "check": ["입주비 확인"]}]
        return notices, grades

    def test_rules_then_grade_then_summary_card_record(self):
        notices, grades = self.three()
        self.run_scout(notices, grades)
        sent_ids = [x["id"] for x in self.asked[0]["notices"]]
        self.assertEqual(sent_ids, ["kstartup:1", "venturesquare:2", "egbiz:3", "egbiz:6"])
        self.assertEqual(self.asked[0]["notices"][0]["tags"], ["평생 한 번"])
        s = self.summary()
        self.assertIn("[자금 정찰] 10/30 (금) 10:00", s)
        self.assertIn("새 공고 6건 · A 1 · B 1 · C 2 · IR 보류 1", s)
        self.assertIn("대출·보증 1건 뺐음, C 2건은 기록만", s)
        self.assertIn("지원금\nA 2027년 초기창업패키지 모집\n  11/29 (일) 마감 · D-30 · 평생 한 번", s)
        self.assertIn("B 수원 창업공간 입주기업 모집\n  11/8 (일) 마감 · D-9 · 입주비 확인", s)
        self.assertNotIn("의정부 FIT데이", s)
        self.assertIn("IR 1건은 기록만 (투자 보류 중)", s)
        self.assertIn("기록: outputs/funds/2026-10-30.md", s)
        card = self.cards()[0]
        for part in ("[A 지금 낼 만함] 2027년 초기창업패키지 모집", "기관1 · 최대 1억 원", "낼 거리: 공모전헌터 사업계획서",
                     "준비물: 사업계획서", "표시: 평생 한 번", "알림: 11/26 (목) 10:00 D-3 알림 걸어 둠", "출처: K-Startup",
                     "https://example.com/1"):
            self.assertIn(part, card)
        self.assertEqual(len(self.cards()), 1)
        rec = self.record()
        for part in ("## 지원금 A", "## 지원금 B", "## IR 보류", "의정부 FIT데이", "## C", "지역 안 맞음", "수출 교육",
                     "규칙으로 뺌: 대출·보증 1건"):
            self.assertIn(part, rec)
        at, text = self.reminders[0]
        self.assertEqual(at, datetime(2026, 11, 26, 10, 0, tzinfo=KST))
        self.assertIn("2027년 초기창업패키지 모집 마감 3일 남음", text)
        self.assertTrue(store.load("heartbeat", {})["fund-scout"]["ok"])

    def test_seen_notices_are_not_graded_again_and_quiet_day_sends_nothing(self):
        notices, grades = self.three()
        self.run_scout(notices, grades)
        sent = len(self.bot.sent)
        self.run_scout(notices, grades, clock=lambda: NOW + timedelta(days=1))
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(len(self.bot.sent), sent)
        self.assertEqual(len(self.reminders), 1)

    def test_upcoming_deadline_is_resent_on_a_quiet_day(self):
        notices, grades = self.three()
        self.run_scout(notices, grades)
        self.run_scout(notices, grades, clock=lambda: NOW + timedelta(days=3))
        s = self.bot.sent[-1]
        self.assertTrue(s.startswith("[자금 정찰] 11/2 (월) 10:00\n새 공고 없음"))
        self.assertIn("마감 다가옴\n• 수원 창업공간 입주기업 모집 · 11/8 (일) 마감 · D-6", s)
        self.assertNotIn("의정부", s)

    def test_same_program_on_two_sources_is_sent_once_from_the_closest_source(self):
        a = n("venturesquare", "9", "[경기혁신센터] 2026 G-스타 오디션 참가기업 모집", days=12)
        b = n("bizinfo", "PB1", "2026 G-스타 오디션 참가기업 모집", days=12)
        self.run_scout([a, b], [{"id": "bizinfo:PB1", "grade": "A", "kind": "grant", "reason": "경기 3년 이내"}])
        self.assertEqual([x["id"] for x in self.asked[0]["notices"]], ["bizinfo:PB1"])
        self.assertIn("같이 실린 곳: 벤처스퀘어", self.record())
        # 다음 날 벤처스퀘어에만 다시 떠도 다시 묻지 않는다.
        self.run_scout([a], [], clock=lambda: NOW + timedelta(days=1))
        self.assertEqual(len(self.asked), 1)

    def test_grade_failure_still_records_and_reports(self):
        notices, _ = self.three()
        self.run_scout(notices, llm.LLMError("시간 초과"))
        s = self.summary()
        self.assertIn("등급 없음 4건", s)
        self.assertIn("등급 매기기 실패: 시간 초과", s)
        self.assertIn("## 등급 없음", self.record())
        self.assertFalse(store.load("heartbeat", {})["fund-scout"]["ok"])

    def test_source_errors_are_listed_and_health_warns_after_three_days(self):
        errors = {"kstartup": "K-Startup: HTTP 403 등록되지 않은 서비스키"}
        for day in range(3):
            self.run_scout([], errors=errors, counts={"egbiz": 5, "bizinfo": 5, "venturesquare": 0},
                           clock=lambda d=day: NOW + timedelta(days=d))
        s = self.bot.sent[-1]
        self.assertIn("못 읽은 출처\n• K-Startup: K-Startup: HTTP 403 등록되지 않은 서비스키", s)
        self.assertIn("출처 경보\n• K-Startup 3일째", s)
        self.assertNotIn("벤처스퀘어 3일째", s)
        self.assertTrue(store.load("heartbeat", {})["fund-scout"]["ok"])

    def test_long_b_list_is_cut_in_summary_but_kept_in_record(self):
        notices = [n("egbiz", str(i), "창업 공간 입주기업 모집 %d" % i, days=10 + i) for i in range(8)]
        grades = [{"id": "egbiz:%d" % i, "grade": "B", "kind": "grant", "reason": "이전 필요"} for i in range(8)]
        self.run_scout(notices, grades)
        s = self.summary()
        self.assertIn("창업 공간 입주기업 모집 4", s)
        self.assertNotIn("창업 공간 입주기업 모집 5", s)
        self.assertIn("B 3건 더 (기록에)", s)
        self.assertIn("창업 공간 입주기업 모집 7", self.record())

    def test_many_notices_are_graded_in_batches(self):
        notices = [n("egbiz", str(i), "창업 지원사업 %d" % i) for i in range(fundscout.GRADE_BATCH + 5)]
        self.run_scout(notices, [])
        self.assertEqual([len(p["notices"]) for p in self.asked], [fundscout.GRADE_BATCH, 5])


if __name__ == "__main__":
    unittest.main()
