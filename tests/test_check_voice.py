import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "voice-check" / "scripts" / "check_voice.py"
_spec = importlib.util.spec_from_file_location("check_voice", SCRIPT)
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)


def codes(text, register="blog", section=None):
    return [(level, code) for level, _, code, _, _ in cv.check_text(text, register, section)]


def errors(text, register="apply", section=None):
    return {code for level, code in codes(text, register, section) if level == cv.ERROR}


def warns(text, register="apply", section=None):
    return {code for level, code in codes(text, register, section) if level == cv.WARN}


class BlogDefaultTest(unittest.TestCase):
    def test_blog_still_rejects_formal_endings(self):
        self.assertIn((cv.ERROR, "formal"), codes("이 글은 벤치마크 결과를 정리했습니다.\n"))

    def test_blog_accepts_plain_endings(self):
        self.assertNotIn(cv.ERROR, {l for l, _ in codes("이 글은 벤치마크 결과를 정리했다.\n")})


class ApplyEndingTest(unittest.TestCase):
    def test_plain_and_polite_endings_are_errors(self):
        self.assertIn("plain-end", errors("저는 결제 구조를 설계했다.\n"))
        self.assertIn("polite", errors("저는 결제 구조를 설계했어요.\n"))
        self.assertIn("plain-end", errors("결제 구조는 제가 설계함.\n"))

    def test_formal_and_allowed_endings_pass(self):
        text = ("합류했을 때 회사는 3명이었습니다. 제가 만든 제품이고, 왜 이렇게 만들었는지 제가 제일 잘 알고 "
                "있었으니까요. 그게 제일 잘 먹힌다는 걸요.\n")
        self.assertEqual(errors(text), set())

    def test_nouns_that_look_like_endings(self):
        text = "고등학교 때 만든 건 플랫포머 게임.\n\n3주 정도 소요.\n\n둘 다 긴요.\n"
        self.assertEqual(errors(text), set())
        self.assertIn("plain-end", errors("결제 구조는 제가 설계함.\n"))
        self.assertEqual(errors("배송비 포함.\n"), set())

    def test_whole_line_parenthetical_note_is_skipped(self):
        self.assertEqual(errors("결제 구조를 설계했습니다.\n\n(약 1,400자, 줄바꿈 포함. 수기 추정치)\n"), set())

    def test_greeting_is_not_polite_ending(self):
        self.assertEqual(errors("안녕하세요. 한서윤입니다.\n"), set())

    def test_quoted_speech_keeps_its_own_ending(self):
        text = "\"빠르게 시작하고, 빠르게 실패하고, 낭비 없이 개발해라\"라는 린 개발론을 기준으로 삼고 일합니다.\n"
        self.assertEqual(errors(text), set())

    def test_headings_and_link_lines_are_skipped(self):
        text = "## 지원 동기\n\n포트폴리오: https://example.com\n"
        self.assertEqual(errors(text), set())

    def test_noun_endings_pass_but_list_eumseum_only_warns(self):
        text = ("문자가 휴대폰 안에만 남아 있는 문제, 웹이 느려서 기한 안에 끝낼 수 없는 문제.\n\n"
                "- 결제 연동, 부분 환불, 공급사 정산\n- 유지보수 1개월 포함\n- 사업자 등록 필요\n")
        self.assertEqual(errors(text), set())
        self.assertIn("noun-end", warns(text))


class ApplyRejectedPatternTest(unittest.TestCase):
    def test_pretend_honest_phrases(self):
        found = errors("자사몰 결제를 구축해 운영했고, 원장을 설계해 출시 전 검증까지 마쳤습니다.\n")
        self.assertIn("pretend-honest", found)
        self.assertIn("pretend-honest", errors("이 점은 그대로 인정합니다.\n"))

    def test_weak_labels_and_negative_endings(self):
        self.assertIn("weak-label", errors("경력신입이지만 빠르게 배우겠습니다.\n"))
        self.assertIn("weak-label", errors("프로젝트 자체는 중간에 접었습니다.\n"))

    def test_obvious_reason_but_not_concrete_reason(self):
        self.assertIn("obvious-reason",
                      errors("한 사람이 사업 하나를 맡으려면 사람 손이 가는 일을 줄여야 하니까요.\n"))
        self.assertEqual(errors("물은 한 번 주면 되돌릴 수 없으니까요.\n"), set())

    def test_intensifiers(self):
        self.assertIn("intensifier", errors("최고의 결과를 완벽하게 만들었습니다.\n"))

    def test_really_is_only_a_warning(self):
        text = "그런데 실제로 만나 이야기를 나눠 보면 설명하지 못하는 경우가 적지 않았습니다.\n"
        self.assertEqual(errors(text), set())
        self.assertIn("really", warns(text))

    def test_meta_lesson_and_colloquial_warnings(self):
        self.assertIn("meta", warns("산출물보다 행동 패턴에서 문제가 나온다는 것을 이때 배웠습니다.\n"))
        self.assertIn("colloquial", warns("무엇을 사람이 쥐고 있어야 하는지 기준이 생겼습니다.\n"))


class ApplyRhythmTest(unittest.TestCase):
    def test_long_sentence_warning(self):
        long = "저는 " + "결제와 정산과 환불과 지급이 한 흐름에서 같이 움직이는 구조를 " * 4 + "설계했습니다.\n"
        self.assertIn("long", warns(long))

    def test_average_too_long_and_too_short(self):
        mid = ("결제사 웹훅은 중복으로 오거나 늦게 오거나 순서가 바뀌어 올 수 있어서 이벤트 ID 기준으로 "
               "한 번만 반영되게 했고 같은 이벤트를 두 세션에서 넣는 테스트도 두었습니다. ")
        self.assertIn("rhythm", warns(mid * 8 + "\n"))
        self.assertIn("rhythm", warns("그래도 갔습니다. " * 8 + "\n"))
        ok = "합류했을 때 회사는 3명이었고, 저는 개발자로 들어갔지만 고객 미팅과 영업에도 같이 들어갔습니다. "
        self.assertNotIn("rhythm", warns(ok * 8 + "\n"))

    def test_contrast_overuse(self):
        s = "결과물이 아니라 과정이 중요했습니다. "
        self.assertIn("contrast", warns("## 지원 동기\n\n" + s * 4 + "\n"))
        self.assertNotIn("contrast", warns("## 지원 동기\n\n" + s * 2 + "\n"))


class LinkingTest(unittest.TestCase):
    FLAT = "저는 결제를 맡았습니다. 정산 구조를 설계했습니다. 운영도 직접 했습니다.\n"

    def test_three_unlinked_sentences_are_an_error(self):
        self.assertIn("flat", errors(self.FLAT))

    def test_linked_sentences_pass(self):
        text = ("저는 결제를 맡았고, 정산 구조도 설계했습니다. 그래서 운영까지 직접 하게 됐습니다. "
                "그 과정에서 환불 규칙을 먼저 합의했습니다.\n")
        self.assertEqual(errors(text), set())

    def test_paragraph_break_resets_the_run(self):
        self.assertEqual(errors("저는 결제를 맡았습니다. 정산 구조를 설계했습니다.\n\n운영도 직접 했습니다.\n"), set())

    def test_low_linking_ratio_in_long_text_is_an_error(self):
        text = ("저는 결제를 맡았습니다. 그래서 정산 구조를 설계했습니다. " * 5) + "\n"
        self.assertIn("linking", errors(text))
        short = "저는 결제를 맡았습니다. 그래서 정산 구조를 설계했습니다.\n"
        self.assertNotIn("linking", errors(short) | warns(short))
        linked = ("저는 결제를 맡았고, 정산 구조도 설계했습니다. 그래서 운영까지 직접 하게 됐는데 환불이 어려웠습니다. " * 5) + "\n"
        self.assertNotIn("linking", warns(linked) | errors(linked))

    def test_posting_as_subject_is_an_error(self):
        self.assertIn("posting-subject", errors("공고가 쓰는 Java와 Spring은 제 주력이 아닙니다.\n"))
        self.assertIn("posting-subject", errors("공고가 원하는 경험을 갖췄습니다.\n"))
        self.assertEqual(errors("공고에서 말했듯이 가나다페이는 Spring을 씁니다.\n"), set())


class MessageTest(unittest.TestCase):
    BODY = "공고의 문장을 보고 지원합니다. 결제와 정산 구조를 설계해 운영했습니다.\n\n포트폴리오: https://example.com\n"

    def test_missing_greeting_warns(self):
        self.assertIn("greeting", warns(self.BODY, "message"))

    def test_greeting_present(self):
        self.assertNotIn("greeting", warns("안녕하세요, 한서윤입니다.\n\n" + self.BODY, "message"))

    def test_mail_accepts_named_greeting(self):
        text = "김가나님, 안녕하세요. 한서윤입니다.\n\n일정 확인했습니다.\n"
        self.assertNotIn("greeting", warns(text, "mail"))


class SectionTest(unittest.TestCase):
    def test_only_named_section_is_checked(self):
        text = "## 공고 요약\n\n원격 3개월 건이다.\n\n## 제안서\n\n안녕하세요, 한서윤입니다.\n\n결제 구조를 설계했습니다.\n"
        self.assertEqual(errors(text, "message", section="제안서"), set())
        self.assertIn("plain-end", errors(text, "message"))


class CharCountTest(unittest.TestCase):
    def test_counts_section_without_heading_and_notes(self):
        text = "## 제안서\n\n안녕하세요, 한서윤입니다.\n\n(12자)\n\n## 다음\n\n다른 내용입니다.\n"
        self.assertEqual(cv.text_chars(text, "제안서"), len("안녕하세요, 한서윤입니다."))


class CliTest(unittest.TestCase):
    def test_register_flag_and_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.md")
            p.write_text("저는 결제 구조를 설계했다.\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cv.main(["--register", "apply", str(p)]), 1)
            self.assertIn("plain-end", out.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cv.main(["--register=blog", str(p)]), 0)

    def test_register_without_value_is_usage_error(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cv.main(["x.md", "--register"]), 2)

    def test_unknown_register_is_rejected(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cv.main(["--register", "chat", "x.md"]), 2)


if __name__ == "__main__":
    unittest.main()
