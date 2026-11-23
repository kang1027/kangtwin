import unittest
from datetime import datetime, timedelta, timezone

from kangtwin import schedule

KST = timezone(timedelta(hours=9))


def at(h, m=0, day=7):
    return datetime(2026, 10, day, h, m, tzinfo=KST)


class ScheduleTest(unittest.TestCase):
    def test_nothing_due_before_first_slot(self):
        self.assertEqual(schedule.due(at(8, 29), {}, paused=frozenset()), [])

    def test_contest_scout_at_eight_thirty(self):
        self.assertEqual(schedule.due(at(8, 30), {}, paused=frozenset()), [("contest-scout", "2026-10-07 08:30")])

    def test_slot_runs_once(self):
        last = {"contest-scout": "2026-10-07 08:30"}
        self.assertEqual(schedule.due(at(9, 30), last, paused=frozenset()), [])

    def test_late_wake_within_window_still_runs(self):
        self.assertEqual(schedule.due(at(11, 0), {}, paused=frozenset()),
                         [("contest-scout", "2026-10-07 08:30"), ("fund-scout", "2026-10-07 10:00")])

    def test_fund_scout_at_ten(self):
        last = {"contest-scout": "2026-10-07 08:30"}
        self.assertEqual(schedule.due(at(10, 0), last, paused=frozenset()), [("fund-scout", "2026-10-07 10:00")])

    def test_too_late_slot_is_skipped(self):
        self.assertEqual(schedule.due(at(13, 0), {}, paused=frozenset()), [])

    def test_interview_at_ten_pm(self):
        self.assertEqual(schedule.due(at(22, 1), {}, paused=frozenset()), [("interview", "2026-10-07 22:00")])

    def test_interview_window_crosses_midnight(self):
        self.assertEqual(schedule.due(at(0, 30, day=8), {}, paused=frozenset()), [("interview", "2026-10-07 22:00")])

    def test_yesterdays_record_does_not_block_today(self):
        last = {"contest-scout": "2026-10-06 08:30"}
        self.assertEqual(schedule.due(at(8, 35), last, paused=frozenset()), [("contest-scout", "2026-10-07 08:30")])


class DefaultJobsTest(unittest.TestCase):
    """설정 파일이 없으면 밤 인터뷰만 켜진다."""

    def test_scouts_are_off_by_default(self):
        self.assertEqual(schedule.due(at(8, 30), {}), [])
        self.assertEqual(schedule.due(at(10, 0), {}), [])

    def test_interview_runs_by_default(self):
        self.assertEqual(schedule.due(at(22, 1), {}), [("interview", "2026-10-07 22:00")])


if __name__ == "__main__":
    unittest.main()
