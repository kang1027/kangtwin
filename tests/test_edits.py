import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kangtwin import edits, vault

TODAY = datetime(2026, 10, 9, 14, 0, tzinfo=timezone(timedelta(hours=9)))

DRAFT = """운영은 최대한 자동화하겠습니다. 한 사람이 사업 하나를 맡으려면 사람 손이 가는 일을 줄여야 하니까요.

자사몰 결제를 구축해 실제로 운영했습니다.
"""
FINAL = """운영은 최대한 자동화하겠습니다.

자사몰 결제를 구축해 운영했습니다.

가나다랩에서 결실을 내 보고 싶습니다.
"""


class ChangeRateTest(unittest.TestCase):
    def test_same_text_is_zero_and_ignores_whitespace(self):
        self.assertEqual(edits.change_rate("가나다 라마", "가나다\n\n라마"), 0.0)

    def test_rewritten_text_is_one(self):
        self.assertEqual(edits.change_rate("가나다", "라마바"), 1.0)

    def test_partial_change_is_between(self):
        rate = edits.change_rate(DRAFT, FINAL)
        self.assertTrue(0.2 < rate < 0.8, rate)


class ChangedSentencesTest(unittest.TestCase):
    def test_pairs_removed_changed_and_added_sentences(self):
        pairs = edits.changed_sentences(DRAFT, FINAL)
        self.assertIn(("한 사람이 사업 하나를 맡으려면 사람 손이 가는 일을 줄여야 하니까요.", ""), pairs)
        self.assertIn(("자사몰 결제를 구축해 실제로 운영했습니다.", "자사몰 결제를 구축해 운영했습니다."), pairs)
        self.assertIn(("", "가나다랩에서 결실을 내 보고 싶습니다."), pairs)
        self.assertNotIn(("운영은 최대한 자동화하겠습니다.", "운영은 최대한 자동화하겠습니다."), pairs)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_new_note_with_front_matter_and_pairs(self):
        path = edits.record("apply", "가나다랩 \"자소서\": 포부", DRAFT, FINAL, self.root, TODAY, slug="ganada")
        self.assertEqual(path, self.root.resolve() / "voice" / "edits" / "2026-10-09-ganada.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("register: apply\n", text)
        self.assertIn('target: "가나다랩 \\"자소서\\": 포부"\n', text)
        self.assertIn("change_rate: ", text)
        self.assertIn("- 전: 자사몰 결제를 구축해 실제로 운영했습니다.\n  후: 자사몰 결제를 구축해 운영했습니다.", text)
        self.assertIn("- 삭제: 한 사람이", text)
        self.assertIn("- 추가: 가나다랩에서", text)
        self.assertIn("## 규칙 후보", text)

    def test_never_overwrites_existing_note(self):
        first = edits.record("apply", "가나다랩", DRAFT, FINAL, self.root, TODAY, slug="ganada")
        second = edits.record("apply", "가나다랩", DRAFT, FINAL, self.root, TODAY, slug="ganada")
        self.assertNotEqual(first, second)
        self.assertEqual(second.name, "2026-10-09-ganada-2.md")

    def test_default_slug_from_target(self):
        path = edits.record("message", "그룹바이 6576 / AI 엔지니어", DRAFT, FINAL, self.root, TODAY)
        self.assertEqual(path.name, "2026-10-09-그룹바이-6576-AI-엔지니어.md")

    def test_given_slug_cannot_escape_edits_folder(self):
        path = edits.record("apply", "x", DRAFT, FINAL, self.root, TODAY, slug="a/../../facts/b")
        self.assertEqual(path.parent, (self.root / "voice" / "edits").resolve())
        self.assertFalse((self.root / "facts").exists())

    def test_rejects_unknown_register(self):
        with self.assertRaises(ValueError):
            edits.record("blog", "x", DRAFT, FINAL, self.root, TODAY)


class CreateNoteTest(unittest.TestCase):
    def test_create_note_refuses_existing_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            vault.create_note("voice/edits/a.md", "x\n", root)
            with self.assertRaises(vault.VaultError):
                vault.create_note("voice/edits/a.md", "y\n", root)
            with self.assertRaises(vault.VaultError):
                vault.create_note("../outside.md", "y\n", root)
            self.assertEqual((root / "voice/edits/a.md").read_text(), "x\n")


class CliTest(unittest.TestCase):
    def test_record_from_files(self):
        with tempfile.TemporaryDirectory() as d:
            draft, final = Path(d, "d.md"), Path(d, "f.md")
            draft.write_text(DRAFT, encoding="utf-8")
            final.write_text(FINAL, encoding="utf-8")
            root = Path(d, "me")
            with redirect_stdout(io.StringIO()) as out:
                edits.main(["record", "--register", "apply", "--target", "가나다랩", "--slug", "m",
                            "--draft", str(draft), "--final", str(final)], root=root, today=TODAY)
            self.assertIn("2026-10-09-m.md", out.getvalue())
            self.assertIn("수정률", out.getvalue())


if __name__ == "__main__":
    unittest.main()
