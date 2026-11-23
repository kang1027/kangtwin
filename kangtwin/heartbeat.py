"""작업별 마지막 실행 기록. 너무 오래됐거나 실패하면 stale."""
import argparse
from datetime import datetime, timedelta
from typing import Dict, FrozenSet, List, Optional

from . import config, schedule, store

EXPECT: Dict[str, timedelta] = {
    "interview": timedelta(hours=26),
    "contest-scout": timedelta(hours=26),
    "fund-scout": timedelta(hours=26),
    "receiver": timedelta(minutes=10),
}


def beat(job: str, ok: bool = True, note: str = "", now: Optional[datetime] = None) -> None:
    beats = store.load("heartbeat", {})
    beats[job] = {"at": (now or config.now()).isoformat(), "ok": ok, "note": note}
    store.save("heartbeat", beats)


def stale(now: datetime, paused: Optional[FrozenSet[str]] = None) -> List[str]:
    paused = schedule.PAUSED if paused is None else paused
    beats = store.load("heartbeat", {})
    out = []
    for job, limit in EXPECT.items():
        if job in paused:
            continue
        rec = beats.get(job)
        if not rec:
            continue
        if not rec.get("ok", True) or now - datetime.fromisoformat(rec["at"]) > limit:
            out.append(job)
    return out


def status_lines() -> List[str]:
    beats = store.load("heartbeat", {})
    lines = []
    for job in EXPECT:
        if job in schedule.PAUSED:
            lines.append("%s: 중지됨" % job)
            continue
        rec = beats.get(job)
        if not rec:
            lines.append("%s: 기록 없음" % job)
            continue
        mark = "ok" if rec.get("ok", True) else "실패"
        note = " (%s)" % rec["note"] if rec.get("note") else ""
        lines.append("%s: %s %s%s" % (job, rec["at"][:16].replace("T", " "), mark, note))
    return lines


def main() -> None:
    p = argparse.ArgumentParser(prog="kt heartbeat")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("beat")
    b.add_argument("job")
    b.add_argument("--fail", action="store_true")
    b.add_argument("--note", default="")
    sub.add_parser("status")
    args = p.parse_args()
    if args.cmd == "beat":
        beat(args.job, ok=not args.fail, note=args.note)
    else:
        print("\n".join(status_lines()))


if __name__ == "__main__":
    main()
