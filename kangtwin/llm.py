"""`claude -p`로 스킬을 부르고 답에서 JSON을 꺼낸다. 읽기 도구만 허용한다."""
import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, Sequence

from . import config

FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


class LLMError(Exception):
    pass


def extract_json(text: str) -> Dict[str, Any]:
    for block in reversed(FENCE.findall(text)):
        try:
            obj = json.loads(block)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
        raise LLMError("JSON이 객체가 아님")
    decoder = json.JSONDecoder()
    found = None
    i = text.find("{")
    while i >= 0:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found = obj
        i = text.find("{", end)
    if found is None:
        raise LLMError("답에 JSON 객체가 없음")
    return found


def _claude_bin() -> str:
    return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def run_claude(prompt: str, timeout: int = 420, deny: Sequence[str] = ()) -> str:
    """deny: Me 안이라도 읽으면 안 되는 절대 경로 (블라인드 테스트의 원문 등)."""
    # dontAsk: 허용 목록 밖 도구는 묻지 않고 거부한다. 사용자 기본 모드(auto)를 물려받지 않게 고정.
    # Bash는 늘 막는다. 사용자 설정의 Bash(rg:*) 같은 허용을 물려받아 Read 금지를 우회할 수 있다(실험으로 확인).
    # 모델은 opus로 고정한다. 지정하지 않으면 계정 기본값이 가끔 Fable·Mythos로 바뀌어 그 한도에 걸린다.
    cmd = [_claude_bin(), "-p", prompt, "--model", "opus", "--permission-mode", "dontAsk",
           "--allowedTools", "Read(/%s/**)" % config.ME, "--add-dir", str(config.ME),
           "--disallowedTools", "Bash"] + ["Read(/%s)" % path for path in deny]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(config.REPO))
    except subprocess.TimeoutExpired:
        raise LLMError("claude 시간 초과 (%ds)" % timeout) from None
    if done.returncode != 0:
        # 로그인 만료 같은 오류는 stdout에만 찍힌다.
        detail = done.stderr.strip() or done.stdout.strip()
        raise LLMError("claude 종료 코드 %d: %s" % (done.returncode, detail[-300:]))
    return done.stdout


def ask_skill(mode: str, payload: Dict[str, Any], skill: str = "kang-twin-interview",
              deny: Sequence[str] = (), timeout: int = 420) -> Dict[str, Any]:
    prompt = "/%s %s\n기록 폴더: %s\n\n입력:\n%s" % (skill, mode, config.ME, json.dumps(payload, ensure_ascii=False))
    return extract_json(run_claude(prompt, timeout=timeout, deny=deny))
