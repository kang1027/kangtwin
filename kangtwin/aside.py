"""aside(브라우저 에이전트) CLI 호출. 공고 원문을 읽기만 할 때 쓴다."""
import shutil
import subprocess
import time
from pathlib import Path

from . import llm


def run_aside(prompt: str, timeout: int = 900) -> str:
    # Aside 앱이 꺼져 있으면 CLI가 'Aside isn't running'으로 실패한다. 켜고 기다린다.
    if subprocess.run(["pgrep", "-x", "Aside"], capture_output=True).returncode != 0:
        subprocess.run(["open", "-a", "Aside"], capture_output=True)
        time.sleep(20)
    binary = shutil.which("aside") or str(Path.home() / ".local/bin/aside")
    done = subprocess.run([binary, prompt], capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise llm.LLMError("aside 종료 코드 %d: %s" % (done.returncode, done.stderr.strip()[-300:]))
    return done.stdout
