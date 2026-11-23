"""봇 소유자 페어링 코드 발급. 텔레그램에서 `/start <코드>`를 보내면 연결된다."""
import secrets

from . import config, store


def issue() -> str:
    code = "%06d" % secrets.randbelow(10 ** 6)
    store.save("pairing", {"code": code, "at": config.now().isoformat()})
    return code


if __name__ == "__main__":
    if store.load("owner", {}).get("chat_id"):
        print("이미 연결돼 있음. 다시 하려면 %s/owner.json을 지우고 실행" % config.state_dir())
    else:
        print("텔레그램에서 봇에게 보내기:  /start %s" % issue())
