"""날짜를 정해 둔 한 번짜리 알림. 데몬이 수신 루프마다 확인해 때가 되면 텔레그램으로 보낸다."""
import argparse
from datetime import datetime, timedelta
from typing import Any, Dict, List

from . import config, store

FMT = "%Y-%m-%d %H:%M"
# 맥이 잠들어 있다 깨서 이만큼 넘게 늦으면 늦었다고 붙인다.
LATE = timedelta(hours=1)
WEEKDAYS = "월화수목금토일"


def parse_at(text: str) -> datetime:
    return datetime.strptime(text.strip(), FMT).replace(tzinfo=config.SEOUL)


def _rows() -> List[Dict[str, Any]]:
    return store.load("reminders", [])


def add(at: datetime, text: str) -> Dict[str, Any]:
    with store.lock("reminders"):
        rows = _rows()
        row = {"id": max((r["id"] for r in rows), default=0) + 1, "at": at.strftime(FMT), "text": text, "sent": None}
        rows.append(row)
        rows.sort(key=lambda r: r["at"])
        store.save("reminders", rows)
    return row


def remove(rid: int) -> bool:
    with store.lock("reminders"):
        rows = _rows()
        kept = [r for r in rows if r["id"] != rid]
        store.save("reminders", kept)
    return len(kept) < len(rows)


def _due(rows: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    key = now.strftime(FMT)
    return [r for r in rows if not r.get("sent") and r["at"] <= key]


def fire(bot: Any, owner: int, now: datetime) -> int:
    """때가 된 알림을 보내고 보낸 개수를 돌려준다. 전송이 실패하면 표시하지 않아 다음 루프에서 다시 보낸다."""
    if not _due(_rows(), now):
        return 0
    sent = 0
    with store.lock("reminders"):
        rows = _rows()
        for row in _due(rows, now):
            text = "[알림] " + row["text"]
            if now - parse_at(row["at"]) > LATE:
                text += "\n(%s에 보낼 거였는데 늦었음)" % row["at"]
            bot.send_message(owner, text)
            row["sent"] = now.isoformat()
            store.save("reminders", rows)
            sent += 1
    return sent


def _label(row: Dict[str, Any]) -> str:
    at = parse_at(row["at"])
    head = row["text"].split("\n", 1)[0]
    return "%s(%s) %s %s" % (at.strftime("%m/%d"), WEEKDAYS[at.weekday()], at.strftime("%H:%M"), head)


def upcoming(now: datetime, limit: int = 3) -> List[str]:
    key = now.strftime(FMT)
    return [_label(r) for r in _rows() if not r.get("sent") and r["at"] > key][:limit]


def main() -> None:
    p = argparse.ArgumentParser(prog="kt remind")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("at", type=parse_at, help='"YYYY-MM-DD HH:MM" (서울 시간)')
    a.add_argument("text", help='줄바꿈은 "\\n"으로 적어도 된다')
    r = sub.add_parser("rm")
    r.add_argument("id", type=int)
    sub.add_parser("list")
    args = p.parse_args()
    if args.cmd == "add":
        row = add(args.at, args.text.replace("\\n", "\n"))
        print("추가함 #%d %s" % (row["id"], _label(row)))
    elif args.cmd == "rm":
        print("지움" if remove(args.id) else "그런 번호 없음")
    else:
        for row in _rows():
            mark = "보냄" if row.get("sent") else "대기"
            print("#%d [%s] %s" % (row["id"], mark, _label(row)))


if __name__ == "__main__":
    main()
