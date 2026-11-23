import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kangtwin import vault

TODAY = datetime(2026, 10, 7, 22, 10, tzinfo=timezone(timedelta(hours=9)))

EDU = """---
type: fact
status: active
visibility: private
updated: 2026-09-24
---

# 교육

## 한빛고등학교

- 특성화고에서 개발을 시작.
- 한빛고등학교 수석 졸업.

## 한빛대학교

- 1학년 수석.
"""


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Me"
        (self.root / "facts").mkdir(parents=True)
        (self.root / "facts" / "education.md").write_text(EDU, encoding="utf-8")
        self.backups = Path(self.tmp.name) / "backups"

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, edits):
        return vault.apply_edits(edits, self.root, self.backups, today=TODAY)

    def text(self, rel="facts/education.md"):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_line_goes_to_end_of_heading_section(self):
        self.apply([{"file": "facts/education.md", "heading": "## 한빛고등학교", "line": "- 게임개발 동아리 픽셀 공방."}])
        body = self.text()
        self.assertIn("- 한빛고등학교 수석 졸업.\n- 게임개발 동아리 픽셀 공방.\n\n## 한빛대학교", body)

    def test_missing_heading_is_appended_at_end(self):
        self.apply([{"file": "facts/education.md", "heading": "## 취미", "line": "- 바이올린."}])
        self.assertTrue(self.text().rstrip().endswith("## 취미\n\n- 바이올린."))

    def test_duplicate_line_is_skipped(self):
        changed = self.apply([{"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- 1학년 수석."}])
        self.assertEqual(changed, [])
        self.assertEqual(self.text().count("- 1학년 수석."), 1)

    def test_paths_outside_vault_are_rejected(self):
        for bad in ["../outside.md", "/etc/passwd.md", "facts/notes.txt", "facts/../../x.md"]:
            with self.assertRaises(vault.VaultError, msg=bad):
                self.apply([{"file": bad, "heading": "## a", "line": "- b"}])

    def test_rejected_batch_writes_nothing(self):
        before = self.text()
        with self.assertRaises(vault.VaultError):
            self.apply([
                {"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- 새 줄."},
                {"file": "../outside.md", "heading": "## a", "line": "- b"},
            ])
        self.assertEqual(self.text(), before)

    def test_backup_is_written_before_edit(self):
        self.apply([{"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- 새 줄."}])
        backups = list(self.backups.rglob("education.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), EDU)

    def test_new_file_gets_frontmatter(self):
        self.apply([{"file": "facts/hobbies.md", "heading": "## 음악", "line": "- 바이올린 레슨."}])
        body = self.text("facts/hobbies.md")
        self.assertTrue(body.startswith("---\ntype: fact\nstatus: active\nvisibility: private\nupdated: 2026-10-07\n---\n"))
        self.assertIn("## 음악\n\n- 바이올린 레슨.", body)

    def test_updated_field_is_bumped(self):
        self.apply([{"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- 새 줄."}])
        self.assertIn("updated: 2026-10-07", self.text())
        self.assertNotIn("updated: 2026-09-24", self.text())

    def test_multiline_line_is_rejected(self):
        with self.assertRaises(vault.VaultError):
            self.apply([{"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- a\n## 가짜 제목"}])

    def test_validate_checks_without_writing(self):
        before = self.text()
        vault.validate([{"file": "facts/education.md", "heading": "## 한빛대학교", "line": "- 새 줄."}], self.root)
        self.assertEqual(self.text(), before)
        with self.assertRaises(vault.VaultError):
            vault.validate([{"file": "../x.md", "heading": "## a", "line": "- b"}], self.root)

    def test_non_string_fields_are_rejected(self):
        for bad in [{"file": 5, "heading": "## a", "line": "- b"},
                    {"file": "facts/education.md", "heading": None, "line": "- b"},
                    {"file": "facts/education.md", "heading": "## a", "line": 3},
                    {"file": "facts/a\x00b.md", "heading": "## a", "line": "- b"}]:
            with self.assertRaises(vault.VaultError, msg=repr(bad)):
                vault.validate([bad], self.root)

    def test_append_log_creates_monthly_file(self):
        log = self.root / "events" / "2026-10.md"
        vault.append_log(log, "- 2026-10-07 22:10 인터뷰 반영", title="2026-10 사건 로그")
        vault.append_log(log, "- 2026-10-07 22:11 두 번째")
        body = log.read_text(encoding="utf-8")
        self.assertIn("# 2026-10 사건 로그", body)
        self.assertTrue(body.rstrip().endswith("- 2026-10-07 22:10 인터뷰 반영\n- 2026-10-07 22:11 두 번째"))


if __name__ == "__main__":
    unittest.main()
