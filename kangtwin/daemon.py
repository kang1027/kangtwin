"""텔레그램 long polling 수신 루프. launchd KeepAlive로 돈다."""
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, List

from . import config, heartbeat, remind, schedule, store
from .router import route
from .telegram import Bot, TelegramError

Spawn = Callable[[List[str]], None]
# 볼트를 건드리거나 LLM을 부르는 행동은 전부 떼어 낸 작업으로 돌린다.
# 볼트 읽기가 멈춰도(iCloud 다운로드, 권한 확인 창) 수신 루프는 계속 돈다.
JOB_ACTIONS = {"interview_ask": "ask", "interview_answer": "answer", "interview_revise": "revise",
               "interview_more": "more", "interview_apply": "apply", "interview_mark_revise": "mark_revise",
               "interview_close": "close", "memo": "memo",
               "blind_start": "blind_start", "blind_answer": "blind_answer"}


def log(msg: str) -> None:
    print("%s %s" % (config.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def spawn_job(args: List[str]) -> None:
    logs = config.state_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = open(logs / "jobs.log", "a")
    subprocess.Popen([sys.executable, "-m", "kangtwin.jobs"] + args, cwd=str(config.REPO),
                     stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def launch_scheduled(job: str) -> None:
    """정시 작업을 데몬의 자식으로 띄운다. Kang Twin.app 아래라 볼트 접근 권한을 물려받는다."""
    if job == "interview":
        spawn_job(["ask"])
        return
    logs = config.state_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    modules = {"contest-scout": ("kangtwin.contestscout", "contests.log"),
               "fund-scout": ("kangtwin.fundscout", "funds.log")}
    if job in modules:
        module, logname = modules[job]
        subprocess.Popen([sys.executable, "-m", module], cwd=str(config.REPO),
                         stdout=open(logs / logname, "a"), stderr=subprocess.STDOUT, start_new_session=True)
        return
    log("모르는 정시 작업: %s" % job)


def run_schedule(now: datetime, launch: Callable[[str], None] = launch_scheduled) -> None:
    last = store.load("schedule", {})
    for job, key in schedule.due(now, last):
        last[job] = key
        store.save("schedule", last)
        log("정시 작업 시작: %s (%s)" % (job, key))
        launch(job)


def status_text() -> str:
    iv = store.load("interview", {})
    lines = ["[상태]"] + heartbeat.status_lines()
    if iv:
        lines.append("인터뷰: %s (%s)" % (iv.get("status", "-"), iv.get("topic", "-")))
    bt = store.load("blind", {})
    if bt.get("status") == "running":
        lines.append("블라인드: %d/%d 진행 중" % (bt.get("idx", 0), len(bt.get("items", []))))
    elif bt.get("status") == "preparing":
        lines.append("블라인드: 준비 중")
    nxt = remind.upcoming(config.now())
    if nxt:
        lines.append("다음 알림:")
        lines.extend("• " + line for line in nxt)
    return "\n".join(lines)


def execute(bot: Bot, name: str, args: Dict[str, Any], spawn: Spawn) -> None:
    owner = store.load("owner", {}).get("chat_id")
    if name == "pair":
        store.save("owner", {"chat_id": args["chat_id"]})
        store.save("pairing", {})
        bot.send_message(args["chat_id"], "연결됨. 이제 이 채팅으로만 일함.\n/ask 인터뷰 바로 시작, /status 상태 보기. 그냥 보내는 말은 메모로 저장함.")
    elif name == "ack":
        bot.answer_callback(args["callback_id"])
        if args.get("message_id"):
            bot.clear_buttons(args["chat_id"], args["message_id"])
    elif name == "reply":
        bot.send_message(owner, args["text"])
    elif name == "status":
        bot.send_message(owner, status_text())
    elif name == "contest_scout":
        bot.send_message(owner, "공모전 정찰 시작함. A가 있으면 초안까지 써서 몇십 분 걸릴 수 있음")
        launch_scheduled("contest-scout")
    elif name == "fund_scout":
        bot.send_message(owner, "자금 정찰 시작함. 등급까지 몇 분 걸림")
        launch_scheduled("fund-scout")
    elif name in JOB_ACTIONS:
        cmd = [JOB_ACTIONS[name]]
        if "text" in args:
            cmd.append("--text=" + args["text"])
        if "reason" in args:
            cmd.append("--reason=" + args["reason"])
        spawn(cmd)
    else:
        log("모르는 행동: %s" % name)


def step(bot: Bot, spawn: Spawn = spawn_job, timeout: int = 50) -> bool:
    offset = store.load("offset", {}).get("next")
    try:
        updates = bot.get_updates(offset, timeout)
    except TelegramError as e:
        log("수신 실패: %s" % e)
        return False
    for update in updates:
        store.save("offset", {"next": update["update_id"] + 1})
        actions = route(update, store.load("owner", {}).get("chat_id"), store.load("interview", {}),
                        store.load("pairing", {}).get("code"))
        for name, args in actions:
            try:
                execute(bot, name, args, spawn)
            except TelegramError as e:
                log("%s 실행 중 전송 실패: %s" % (name, e))
            except Exception as e:
                log("%s 실행 중 오류: %r" % (name, e))
                owner = store.load("owner", {}).get("chat_id")
                if owner:
                    try:
                        bot.send_message(owner, "처리하다 오류 남 (%s): %s" % (name, type(e).__name__))
                    except TelegramError:
                        pass
    return True


def check_stale(bot: Bot, now: datetime) -> None:
    owner = store.load("owner", {}).get("chat_id")
    alerted = store.load("alerts", {})
    today = now.date().isoformat()
    for job in heartbeat.stale(now):
        if job == "receiver" or alerted.get(job) == today:
            continue
        line = next((l for l in heartbeat.status_lines() if l.startswith(job + ":")), job)
        try:
            bot.send_message(owner, "[경보] %s 하트비트가 끊겼거나 실패함\n%s" % (job, line))
        except TelegramError as e:
            log("경보 전송 실패: %s" % e)
            continue
        alerted[job] = today
    store.save("alerts", alerted)


def main() -> None:
    token = config.bot_token()
    if not token:
        log("키체인에 kang-twin-telegram 토큰이 없음. 5분 뒤 다시 확인")
        time.sleep(300)
        sys.exit(1)
    bot = Bot(token)
    delay, last_check = 5, 0.0
    log("수신 시작")
    while True:
        ok = step(bot)
        heartbeat.beat("receiver")
        try:
            run_schedule(config.now())
        except Exception as e:
            log("정시 작업 실행 오류: %r" % e)
        owner = store.load("owner", {}).get("chat_id")
        if owner:
            try:
                remind.fire(bot, owner, config.now())
            except Exception as e:
                log("알림 전송 오류: %r" % e)
        if time.time() - last_check > 3600 and owner:
            check_stale(bot, config.now())
            last_check = time.time()
        if ok:
            delay = 5
        else:
            time.sleep(delay)
            delay = min(delay * 2, 300)


if __name__ == "__main__":
    main()
