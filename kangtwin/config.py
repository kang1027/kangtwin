"""경로, 비밀값 조회, 시간 같은 공통 설정."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


def _settings() -> dict:
    """~/.config/kang-twin/config.json (KANGTWIN_CONFIG로 바꿀 수 있음). 없으면 빈 설정."""
    path = Path(os.environ.get("KANGTWIN_CONFIG", str(Path.home() / ".config/kang-twin/config.json")))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


SETTINGS = _settings()
# 기록 볼트. 환경 변수가 설정 파일보다 앞선다. 둘 다 없으면 저장소의 샘플 볼트로 돈다.
VAULT = Path(os.path.expanduser(os.environ.get("KANGTWIN_VAULT") or SETTINGS.get("vault") or str(REPO / "sample-vault")))
ME = VAULT / SETTINGS.get("me_dir", "Me")
OUTPUTS = VAULT / SETTINGS.get("outputs_dir", "Outputs")
KEYCHAIN_SERVICE = SETTINGS.get("keychain_service", "kang-twin-telegram")
SEOUL = timezone(timedelta(hours=int(SETTINGS.get("utc_offset_hours", 9))))
# 켤 정시 작업. interview만 기본으로 켠다. 정찰은 확장이라 설정에서 켠다.
ENABLED_JOBS = frozenset(SETTINGS.get("jobs", ["interview"]))


def state_dir() -> Path:
    return Path(os.environ.get("KANGTWIN_STATE", str(Path.home() / ".local/state/kang-twin")))


def token_file() -> Path:
    return Path(os.environ.get("KANGTWIN_TOKEN_FILE", str(Path.home() / ".config/kang-twin/telegram-token")))


def datagokr_key() -> str:
    """공공데이터포털 인증키(Decoding 키). 권한 600 파일에만 둔다. 없으면 빈 문자열."""
    path = Path(os.environ.get("KANGTWIN_DATAGOKR_KEY_FILE", str(Path.home() / ".config/kang-twin/datagokr-key")))
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def bot_token() -> Optional[str]:
    """키체인에서 봇 토큰을 읽고, 안 되면 권한 600 토큰 파일을 읽는다. 둘 다 없으면 None.

    서버로 쓰는 맥은 SSH로 키체인에 쓸 수 없어서 파일을 쓴다.
    """
    try:
        done = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        token = done.stdout.strip()
        if token:
            return token
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    try:
        return token_file().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def now() -> datetime:
    return datetime.now(SEOUL)
