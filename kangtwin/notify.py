"""소유자에게 한 줄 알림. 토큰이나 페어링이 없으면 macOS 알림으로 대신한다."""
import subprocess
import sys

from . import config, store
from .telegram import Bot, TelegramError


def _macos(text: str) -> str:
    safe = text.replace("\n", " / ")[:200].replace('"', "'").replace("\\", "/")
    subprocess.run(["osascript", "-e", 'display notification "%s" with title "Kang Twin"' % safe],
                   capture_output=True, timeout=10)
    return "macos"


def send(text: str) -> str:
    # 셸에서 여러 줄을 넘기기 어려워 스킬은 "\\n"으로 줄바꿈을 적는다.
    text = text.replace("\\n", "\n")
    token = config.bot_token()
    owner = store.load("owner", {}).get("chat_id")
    if token and owner:
        try:
            Bot(token).send_message(owner, text)
            return "telegram"
        except TelegramError:
            pass
    return _macos(text)


if __name__ == "__main__":
    print(send(" ".join(sys.argv[1:]) or sys.stdin.read()))
