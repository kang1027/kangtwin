import subprocess
import unittest
from unittest import mock

from kangtwin import llm


class ExtractJsonTest(unittest.TestCase):
    def test_fenced_block(self):
        text = '질문 골랐음.\n```json\n{"topic": "취미", "question": "운동 하는 거 있음?"}\n```\n'
        self.assertEqual(llm.extract_json(text)["topic"], "취미")

    def test_last_fenced_block_wins(self):
        text = '```json\n{"a": 1}\n```\n고침\n```json\n{"a": 2}\n```'
        self.assertEqual(llm.extract_json(text), {"a": 2})

    def test_bare_object_with_chatter(self):
        text = '알겠음. {"action": "followup", "question": "그 동아리 이름은? {괄호}"} 끝'
        self.assertEqual(llm.extract_json(text)["action"], "followup")

    def test_no_json_raises(self):
        with self.assertRaises(llm.LLMError):
            llm.extract_json("죄송합니다, 답할 수 없습니다.")

    def test_non_object_raises(self):
        with self.assertRaises(llm.LLMError):
            llm.extract_json("```json\n[1, 2]\n```")


class RunClaudeTest(unittest.TestCase):
    def test_command_only_allows_reading_08_me(self):
        done = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch("subprocess.run", return_value=done) as run:
            self.assertEqual(llm.run_claude("hi"), "ok")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[1:3], ["-p", "hi"])
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        # 계정 기본 모델은 가끔 Fable·Mythos로 바뀌어 그 한도에 걸린다(2026-11-23 공모전 정찰 실패).
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        tools = cmd[cmd.index("--allowedTools") + 1:cmd.index("--add-dir")]
        self.assertEqual(tools, ["Read(/%s/**)" % llm.config.ME])
        self.assertFalse(any(t.startswith(("Edit", "Write")) for t in cmd))
        # 사용자 설정의 Bash(rg:*) 같은 허용을 물려받아 Read 금지를 우회하지 못하게 늘 막는다.
        self.assertEqual(cmd[cmd.index("--disallowedTools") + 1:], ["Bash"])

    def test_deny_paths_become_disallowed_read_rules(self):
        done = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch("subprocess.run", return_value=done) as run:
            llm.run_claude("hi", deny=["/abs/Me/voice/exemplars/a.md"])
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("--disallowedTools") + 1:], ["Bash", "Read(//abs/Me/voice/exemplars/a.md)"])

    def test_ask_skill_can_call_other_skill_with_deny(self):
        with mock.patch.object(llm, "run_claude", return_value='{"text": "글"}') as rc:
            out = llm.ask_skill("write", {"register": "apply"}, skill="kang-twin-write", deny=["/x.md"], timeout=600)
        self.assertEqual(out["text"], "글")
        self.assertTrue(rc.call_args[0][0].startswith("/kang-twin-write write"))
        self.assertEqual(rc.call_args[1]["deny"], ["/x.md"])
        self.assertEqual(rc.call_args[1]["timeout"], 600)

    def test_nonzero_exit_raises(self):
        done = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch("subprocess.run", return_value=done):
            with self.assertRaises(llm.LLMError):
                llm.run_claude("hi")

    def test_error_shows_stdout_when_stderr_is_empty(self):
        # 로그인 만료 같은 오류는 claude가 stdout에만 찍는다.
        done = subprocess.CompletedProcess([], 1, stdout="Failed to authenticate: OAuth session expired\n", stderr="")
        with mock.patch("subprocess.run", return_value=done):
            with self.assertRaisesRegex(llm.LLMError, "OAuth session expired"):
                llm.run_claude("hi")

    def test_timeout_raises(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 1)):
            with self.assertRaises(llm.LLMError):
                llm.run_claude("hi", timeout=1)

    def test_ask_skill_sends_mode_and_payload(self):
        with mock.patch.object(llm, "run_claude", return_value='```json\n{"topic":"t","question":"q"}\n```') as rc:
            out = llm.ask_skill("ask", {"asked_recent": ["취미"]})
        self.assertEqual(out["question"], "q")
        prompt = rc.call_args[0][0]
        self.assertTrue(prompt.startswith("/kang-twin-interview ask"))
        self.assertIn('"asked_recent": ["취미"]', prompt)


if __name__ == "__main__":
    unittest.main()
