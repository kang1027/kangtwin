"""매일 인터뷰와 메모 작업. 판단은 스킬(LLM)이, 저장과 전송은 여기서 한다."""
import argparse
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config, heartbeat, llm, store, vault

MAX_FOLLOWUPS = 3
QUIET_DAYS = {"later": 3}
DEFAULT_QUIET_DAYS = 14
ACTIVE = ("awaiting_answer", "proposed", "revising")

Ask = Callable[[str, Dict[str, Any]], Dict[str, Any]]


class Jobs:
    def __init__(self, bot, chat_id: int, ask: Ask = llm.ask_skill, root: Path = config.ME,
                 clock: Callable[[], datetime] = config.now):
        self.bot = bot
        self.chat_id = chat_id
        self.ask_skill = ask
        self.root = root
        self.clock = clock

    # --- 공통 ---

    def _send(self, text: str, buttons=None) -> None:
        self.bot.send_message(self.chat_id, text, buttons)

    def _send_keep(self, text: str) -> None:
        """대기 중인 변경안이 있으면 버튼을 다시 붙여 보낸다. 누른 버튼은 이미 지워졌기 때문."""
        iv = self._state()
        buttons = self._buttons(iv["id"]) if iv.get("status") == "proposed" else None
        self._send(text, buttons)

    def _locked(self, fn: Callable[[], None]) -> None:
        try:
            with store.lock("interview"):
                fn()
        except store.Busy:
            self._send_keep("처리 중임. 끝나고 다시 보내줘")

    def _state(self) -> Dict[str, Any]:
        return store.load("interview", {})

    def _stamp(self) -> str:
        return self.clock().strftime("%Y-%m-%d %H:%M")

    def _month_file(self, *parts: str) -> Path:
        return self.root.joinpath(*parts, self.clock().strftime("%Y-%m") + ".md")

    def _remember_topic(self, topic: str, reason: str) -> None:
        asked = store.load("asked", {})
        asked[topic] = {"date": self.clock().date().isoformat(), "reason": reason}
        store.save("asked", asked)

    def _recent_topics(self) -> List[str]:
        today = self.clock().date()
        recent = []
        for topic, rec in store.load("asked", {}).items():
            days = QUIET_DAYS.get(rec.get("reason"), DEFAULT_QUIET_DAYS)
            when = datetime.fromisoformat(rec["date"]).date()
            if today - when < timedelta(days=days):
                recent.append(topic)
        return recent

    def _buttons(self, iid: str):
        return [[("반영", "iv:apply:%s" % iid), ("고쳐줘", "iv:revise:%s" % iid)],
                [("버리기", "iv:drop:%s" % iid), ("더 물어봐", "iv:more:%s" % iid)]]

    # --- 질문 ---

    def ask(self) -> None:
        self._locked(self._ask)

    def _ask(self) -> None:
        old = self._state()
        if old.get("status") in ("proposed", "revising") and old.get("proposal"):
            old["status"] = "proposed"
            store.save("interview", old)
            self._send("변경안이 아직 대기 중임. 이거 먼저 정리하고 새 질문 받자\n\n" + self._proposal_text(old),
                       self._buttons(old["id"]))
            return
        if old.get("status") in ACTIVE:
            self._remember_topic(old.get("topic", ""), "later")
        try:
            res = self.ask_skill("ask", {"asked_recent": self._recent_topics(),
                                         "today": self.clock().date().isoformat()})
            topic, question = str(res["topic"]).strip(), str(res["question"]).strip()
            if not topic or not question:
                raise llm.LLMError("주제나 질문이 비어 있음")
        except (llm.LLMError, KeyError, TypeError) as e:
            heartbeat.beat("interview", ok=False, note=str(e)[:200])
            self._send("오늘 인터뷰 질문 만들다 실패함: %s" % e)
            return
        iid = secrets.token_hex(3)
        store.save("interview", {
            "id": iid, "topic": topic, "question": question, "turns": [],
            "status": "awaiting_answer", "followups_left": MAX_FOLLOWUPS,
            "started": self.clock().isoformat(),
        })
        self._send("[오늘의 질문 · %s]\n%s" % (topic, question),
                   [[("패스", "iv:skip:%s" % iid), ("나중에", "iv:later:%s" % iid)]])
        heartbeat.beat("interview")

    # --- 답 ---

    def answer(self, text: str) -> None:
        self._locked(lambda: self._answer(text))

    def _answer(self, text: str) -> None:
        iv = self._state()
        if iv.get("status") != "awaiting_answer":
            self._send("지금 기다리는 질문이 없음. 메모로 남기려면 그냥 다시 보내줘")
            return
        iv["turns"].append({"q": iv["question"], "a": text})
        vault.append_log(self._month_file("voice", "corpus", "chat"),
                         "- %s [%s] Q: %s / A: %s" % (self._stamp(), iv["topic"], iv["question"], text),
                         title="%s 인터뷰 답 원문" % self.clock().strftime("%Y-%m"))
        payload = {"topic": iv["topic"], "turns": iv["turns"], "followups_left": iv["followups_left"]}
        mode = "answer" if iv["followups_left"] > 0 else "propose"
        self._next(iv, mode, payload)

    def _next(self, iv: Dict[str, Any], mode: str, payload: Dict[str, Any]) -> None:
        try:
            res = self.ask_skill(mode, payload)
        except llm.LLMError as e:
            store.save("interview", iv)
            self._send_keep("다음 단계 만들다 실패함: %s\n답은 저장해 둠. 다시 답하거나 /ask로 새로 시작" % e)
            heartbeat.beat("interview", ok=False, note=str(e)[:200])
            return
        action = res.get("action")
        question = res.get("question")
        if action == "followup" and mode == "answer" and isinstance(question, str) and question.strip():
            iv["question"] = question.strip()
            iv["followups_left"] -= 1
            iv["status"] = "awaiting_answer"
            store.save("interview", iv)
            self._send("꼬리 %d/%d\n%s" % (MAX_FOLLOWUPS - iv["followups_left"], MAX_FOLLOWUPS, iv["question"]))
            return
        if action == "propose" and isinstance(res.get("edits"), list):
            self._propose(iv, res, retried=False)
            return
        store.save("interview", iv)
        self._send_keep("다음 단계 만들다 실패함: 답 모양이 이상함 (%s 모드, action=%r)\n답은 저장해 둠. 다시 답하거나 /ask로 새로 시작"
                        % (mode, action))
        heartbeat.beat("interview", ok=False, note="답 모양 이상: %s/%r" % (mode, action))

    # --- 변경안 ---

    def _edits(self, res: Dict[str, Any]) -> List[Dict[str, str]]:
        edits = list(res.get("edits") or [])
        if res.get("story"):
            edits.append(res["story"])
        return edits

    def _propose(self, iv: Dict[str, Any], res: Dict[str, Any], retried: bool) -> None:
        edits = self._edits(res)
        try:
            vault.validate(edits, self.root)
        except vault.VaultError as e:
            if not retried:
                try:
                    fixed = self.ask_skill("revise", {
                        "topic": iv["topic"], "turns": iv["turns"], "proposal": res,
                        "instruction": "편집 형식 오류: %s. Me 안 .md 상대 경로, '#' 제목 한 줄, 내용 한 줄로 다시" % e,
                    })
                except llm.LLMError as e2:
                    fixed = None
                    e = e2
                if fixed is not None:
                    self._propose(iv, fixed, retried=True)
                    return
            iv["status"] = "closed"
            store.save("interview", iv)
            self._send("변경안 형식이 이상해서 버렸음: %s\n답은 원문 기록에 남아 있음" % e)
            heartbeat.beat("interview", ok=False, note=str(e)[:200])
            return

        if not edits:
            iv["status"] = "closed"
            store.save("interview", iv)
            self._remember_topic(iv["topic"], "applied")
            self._send("이번 답은 원본에 넣을 사실이 없음. 답은 기록해 둠")
            return

        iv["proposal"] = {"summary": str(res.get("summary", "")), "edits": edits}
        iv["status"] = "proposed"
        path = self.root / "inbox" / ("interview-%s-%s.md" % (self.clock().date().isoformat(), iv["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._proposal_note(iv), encoding="utf-8")
        iv["proposal_path"] = str(path)
        store.save("interview", iv)
        self._send(self._proposal_text(iv), self._buttons(iv["id"]))

    def _proposal_note(self, iv: Dict[str, Any]) -> str:
        lines = ["---", "type: proposal", "status: pending", "visibility: private",
                 "topic: %s" % iv["topic"], "created: %s" % self._stamp(), "---", "",
                 "# 인터뷰 변경안: %s" % iv["topic"], "", iv["proposal"]["summary"], "", "## 문답", ""]
        for t in iv["turns"]:
            lines += ["- Q: %s" % t["q"], "  A: %s" % t["a"]]
        lines += ["", "## 변경안", ""]
        for e in iv["proposal"]["edits"]:
            lines.append("- `%s` › %s → %s" % (e["file"], e["heading"], e["line"]))
        return "\n".join(lines) + "\n"

    def _proposal_text(self, iv: Dict[str, Any]) -> str:
        out = ["[변경안] %s" % iv["proposal"]["summary"]]
        for e in iv["proposal"]["edits"]:
            out.append("\n%s › %s\n%s" % (e["file"], e["heading"].lstrip("# "), e["line"]))
        return "\n".join(out)

    def more(self) -> None:
        self._locked(self._more)

    def _more(self) -> None:
        iv = self._state()
        if iv.get("status") != "proposed":
            self._send("더 물어볼 변경안이 없음")
            return
        iv["followups_left"] = max(iv.get("followups_left", 0), 1)
        self._next(iv, "answer", {"topic": iv["topic"], "turns": iv["turns"],
                                  "followups_left": iv["followups_left"], "force_followup": True})

    def mark_revise(self) -> None:
        self._locked(self._mark_revise)

    def _mark_revise(self) -> None:
        iv = self._state()
        if iv.get("status") != "proposed":
            self._send("고칠 변경안이 없음")
            return
        iv["status"] = "revising"
        store.save("interview", iv)
        self._send("어떻게 고칠지 적어줘")

    def revise(self, text: str) -> None:
        self._locked(lambda: self._revise(text))

    def _revise(self, text: str) -> None:
        iv = self._state()
        if iv.get("status") != "revising":
            self._send("고치는 중인 변경안이 없음")
            return
        try:
            res = self.ask_skill("revise", {"topic": iv["topic"], "turns": iv["turns"],
                                            "proposal": iv.get("proposal"), "instruction": text})
        except llm.LLMError as e:
            iv["status"] = "proposed"
            store.save("interview", iv)
            self._send("고치다 실패함: %s\n이전 변경안 그대로 둠" % e, self._buttons(iv["id"]))
            return
        self._propose(iv, res, retried=False)

    def apply(self) -> None:
        self._locked(self._apply)

    def _apply(self) -> None:
        iv = self._state()
        if iv.get("status") != "proposed" or not iv.get("proposal"):
            self._send("반영할 변경안이 없음")
            return
        try:
            changed = vault.apply_edits(iv["proposal"]["edits"], self.root,
                                        config.state_dir() / "backups", today=self.clock())
        except (vault.VaultError, OSError) as e:
            self._send_keep("반영 실패: %s" % e)
            return
        vault.append_log(self._month_file("events"),
                         "- %s 인터뷰 반영 [%s]: %s" % (self._stamp(), iv["topic"], ", ".join(changed) or "변경 없음"),
                         title="%s 사건 로그" % self.clock().strftime("%Y-%m"))
        if iv.get("proposal_path"):
            vault.append_log(Path(iv["proposal_path"]), "- 반영됨 %s" % self._stamp())
        iv["status"] = "closed"
        store.save("interview", iv)
        self._remember_topic(iv["topic"], "applied")
        heartbeat.beat("interview")
        self._send("반영함: %s" % (", ".join(changed) or "이미 있는 내용이라 바뀐 파일 없음"))

    def close(self, reason: str) -> None:
        self._locked(lambda: self._close(reason))

    def _close(self, reason: str) -> None:
        iv = self._state()
        if iv.get("status") not in ACTIVE:
            return
        iv["status"] = "closed"
        store.save("interview", iv)
        self._remember_topic(iv.get("topic", ""), reason)
        self._send({"skip": "ㅇㅋ 넘김", "later": "ㅇㅋ 며칠 뒤에 다시 물어봄", "drop": "변경안 버림"}.get(reason, "닫음"))

    # --- 메모 ---

    def memo(self, text: str) -> None:
        vault.append_log(self.root / "inbox" / "memos.md", "- %s %s" % (self._stamp(), text), title="텔레그램 메모")
        self._send("메모 저장함. 사서가 나중에 원본에 정리함")


def _bot_and_owner():
    from .telegram import Bot
    token = config.bot_token()
    owner = store.load("owner", {}).get("chat_id")
    if not token or not owner:
        sys.exit("봇 토큰이나 소유자 페어링이 없음 (kt pair 먼저)")
    return Bot(token), owner


def build() -> Jobs:
    return Jobs(*_bot_and_owner())


def build_blind():
    from .blind import BlindTest
    return BlindTest(*_bot_and_owner())


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="kt jobs")
    p.add_argument("action", choices=["ask", "answer", "more", "mark_revise", "revise", "apply", "close", "memo",
                                      "blind_start", "blind_answer"])
    p.add_argument("--text", default="", help="'-'로 시작할 수 있으니 --text=값 형태로 넘긴다")
    p.add_argument("--reason", default="skip")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None, build: Callable[[], Any] = build,
         notify: Optional[Callable[[str], Any]] = None, build_blind: Callable[[], Any] = build_blind) -> None:
    args = parse_args(argv)
    is_blind = args.action.startswith("blind_")
    try:
        if is_blind:
            test = build_blind()
            if args.action == "blind_start":
                test.start()
            else:
                test.answer(args.text)
            return
        jobs = build()
        if args.action in ("answer", "revise", "memo"):
            getattr(jobs, args.action)(args.text)
        elif args.action == "close":
            jobs.close(args.reason)
        else:
            getattr(jobs, args.action)()
    except SystemExit:
        raise
    except Exception as e:
        if notify is None:
            from .notify import send as notify
        notify("%s 작업(%s)이 죽었음: %s: %s" % ("블라인드" if is_blind else "인터뷰", args.action,
                                              type(e).__name__, e))
        if not is_blind:
            heartbeat.beat("interview", ok=False, note="%s 작업 예외: %s" % (args.action, type(e).__name__))
        raise


if __name__ == "__main__":
    main()
