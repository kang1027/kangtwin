"""봇 소유자 페어링 코드 발급. 텔레그램에서 `/start <코드>`를 보내면 연결된다."""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from . import config, store


TTL = timedelta(minutes=10)


def issue() -> str:
    code = secrets.token_urlsafe(12)
    store.save("pairing", {"code": code, "at": config.now().isoformat()})
    return code


def current_code(now: Optional[datetime] = None) -> Optional[str]:
    """아직 살아 있는 페어링 코드. 발급하고 TTL이 지났으면 None."""
    pairing = store.load("pairing", {})
    code, at = pairing.get("code"), pairing.get("at")
    if not code or not at:
        return None
    try:
        if (now or config.now()) - datetime.fromisoformat(at) > TTL:
            return None
    except (TypeError, ValueError):
        return None
    return code


if __name__ == "__main__":
    if store.load("owner", {}).get("chat_id"):
        print("이미 연결돼 있음. 다시 하려면 %s/owner.json을 지우고 실행" % config.state_dir())
    else:
        print("10분 안에 텔레그램에서 봇에게 보내기:  /start %s" % issue())
