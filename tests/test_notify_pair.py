import os
import tempfile
import unittest
from unittest import mock

from kangtwin import notify, pair, store


class NotifyPairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_falls_back_to_macos_without_token(self):
        with mock.patch("kangtwin.config.bot_token", return_value=None), \
                mock.patch("subprocess.run") as run:
            self.assertEqual(notify.send("스카우트 끝"), "macos")
        self.assertEqual(run.call_args[0][0][0], "osascript")

    def test_macos_fallback_keeps_one_line(self):
        with mock.patch("kangtwin.config.bot_token", return_value=None), \
                mock.patch("subprocess.run") as run:
            notify.send("첫 줄\\n둘째 줄")
        self.assertNotIn("\n", run.call_args[0][0][2])

    def test_sends_to_owner_with_token(self):
        store.save("owner", {"chat_id": 77})
        sent = []

        class Bot:
            def __init__(self, token):
                pass

            def send_message(self, chat_id, text, buttons=None):
                sent.append((chat_id, text))

        with mock.patch("kangtwin.config.bot_token", return_value="t"), \
                mock.patch("kangtwin.notify.Bot", Bot):
            self.assertEqual(notify.send("안녕"), "telegram")
        self.assertEqual(sent, [(77, "안녕")])

    def test_escaped_newlines_become_real_line_breaks(self):
        store.save("owner", {"chat_id": 77})
        sent = []

        class Bot:
            def __init__(self, token):
                pass

            def send_message(self, chat_id, text, buttons=None):
                sent.append(text)

        with mock.patch("kangtwin.config.bot_token", return_value="t"), \
                mock.patch("kangtwin.notify.Bot", Bot):
            notify.send("[스카우트] A 2건\\n\\n- 외주 158835")
        self.assertEqual(sent, ["[스카우트] A 2건\n\n- 외주 158835"])

    def test_issue_stores_six_digit_code(self):
        code = pair.issue()
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual(store.load("pairing", {})["code"], code)


if __name__ == "__main__":
    unittest.main()
