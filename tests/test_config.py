import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock


class ConfigTest(unittest.TestCase):
    def test_state_dir_follows_env(self):
        with mock.patch.dict(os.environ, {"KANGTWIN_STATE": "/tmp/kt-state-test"}):
            from kangtwin import config
            self.assertEqual(config.state_dir(), Path("/tmp/kt-state-test"))

    def test_bot_token_none_when_keychain_lookup_fails(self):
        from kangtwin import config
        err = subprocess.CalledProcessError(44, ["security"])
        with mock.patch("subprocess.run", side_effect=err), \
                mock.patch.dict(os.environ, {"KANGTWIN_TOKEN_FILE": "/nonexistent/kt-token"}):
            self.assertIsNone(config.bot_token())

    def test_bot_token_strips_newline(self):
        from kangtwin import config
        done = subprocess.CompletedProcess(["security"], 0, stdout="123:abc\n", stderr="")
        with mock.patch("subprocess.run", return_value=done):
            self.assertEqual(config.bot_token(), "123:abc")

    def test_bot_token_falls_back_to_token_file(self):
        import tempfile
        from kangtwin import config
        err = subprocess.CalledProcessError(44, ["security"])
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("999:file-token\n")
        with mock.patch("subprocess.run", side_effect=err), \
                mock.patch.dict(os.environ, {"KANGTWIN_TOKEN_FILE": f.name}):
            self.assertEqual(config.bot_token(), "999:file-token")
        os.unlink(f.name)

    def test_now_is_seoul_time(self):
        from kangtwin import config
        self.assertEqual(config.now().utcoffset().total_seconds(), 9 * 3600)


if __name__ == "__main__":
    unittest.main()
