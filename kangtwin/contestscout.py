"""공모전 정찰과 초안. 공모전헌터 → 새 공모전 → 등급 → 기록·알림 → A 초안(하루 2건, 마감 가까운 순)."""
import argparse
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import aside as aside_cli, config, gonghunt, heartbeat, llm, notify, store, vault, write

DRAFTS_PER_DAY = 2
DRAFT_MIN_DAYS = 2
CARDS = 6
SEEN_TTL = timedelta(days=120)
VERDICTS = ["바로 낼 만함", "손 많이 감", "패스"]
DRAFT_LENGTH = 2500
PROBE_PROMPT = (
    "읽기만 해. 가입, 로그인, 제출, 파일 다운로드, 아무 칸에 입력하는 것 금지.\n"
    "공모전 공고 %s 를 열어 이 공모전에 무엇을 어떻게 내야 하는지 읽어. 첨부 양식 이름과 문항은 화면에 보이는 만큼만 적어.\n"
    "모을 것: 접수 방법(이메일·구글폼·자체 사이트·플랫폼 등), 접수 주소, 회원가입이나 본인인증이 필요한지, "
    "제출 양식의 문항과 글자 수, 제출 파일(형식·분량), 심사 기준과 배점.\n"
    "마지막에 JSON 하나만 내: {\"method\": \"\", \"apply_url\": \"\", \"account_required\": false, "
    "\"questions\": [{\"label\": \"\", \"limit\": \"\"}], \"files\": [\"\"], \"criteria\": [\"\"], \"notes\": \"\"}")

Contest = Dict[str, Any]


def _deadline(c: Contest) -> Optional[date]:
    m = re.match(r"(\d{4}-\d\d-\d\d)", str(c.get("applyEnd") or ""))
    return datetime.strptime(m.group(1), "%Y-%m-%d").date() if m else None


def _days_left(c: Contest, today: date) -> Optional[int]:
    end = _deadline(c)
    return (end - today).days if end else None


def _prize(c: Contest) -> str:
    p = c.get("prize") or {}
    amount = p.get("amount") or 0
    if not amount:
        return "상금 없음"
    if p.get("currency", "KRW") == "KRW":
        text = "%s만 원" % format(amount // 10000, ",") if amount >= 10000 else "%s원" % format(amount, ",")
    else:
        text = "%s %s" % (p.get("currency"), format(amount, ","))
    return ("총 " if c.get("prizeIsTotal") else "") + text


def _team(c: Contest) -> str:
    t = c.get("teamSize") or {}
    lo, hi = t.get("min"), t.get("max")
    return "%s-%s인" % (lo, hi) if lo and hi and lo != hi else ("%s인" % (lo or hi) if (lo or hi) else "인원 모름")


def _when(c: Contest, today: date) -> str:
    end, left = _deadline(c), _days_left(c, today)
    if not end:
        return "마감 모름"
    return "%d월 %d일 마감 (D-%d)" % (end.month, end.day, left) if left is not None and left >= 0 else "마감 지남"


def _items(g: Dict[str, Any], key: str) -> List[str]:
    v = g.get(key) or []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


DATA_WORDS = re.compile(r"데이터|통계|분석")
DATA_CHECK = "실제 데이터를 받아 돌린 표·그래프 1~2개 넣기 (출처·기준일·건수 표기, 글만 있는 제안서로 내지 않음)"


def _wants_data(c: Contest, form: Dict[str, Any]) -> bool:
    """데이터를 다루는 공모전이면 계획 문장만으로는 심사에서 밀리니 실제 분석 결과를 요구한다."""
    text = " ".join([str(c.get("title") or ""), str(c.get("description") or ""),
                     " ".join(str(x) for x in c.get("fields") or []), " ".join(str(x) for x in form.get("criteria") or [])])
    return bool(DATA_WORDS.search(text))


SUBMIT_WORDS = re.compile(r"공모전 제출|응모|접수 완료|출품")
SUBMITTED_MONTHS = 6


def _submitted(me: Path) -> List[str]:
    """이미 낸 공모전. Me/events 월별 기록(최근 몇 달)에서 제출 줄만 모아 등급 단계에 넘긴다.
    공모전헌터에 같은 대회가 나중에 올라오면 새 공모전으로 보여서 다시 A로 잡히기 때문이다."""
    lines = []
    for f in sorted((me / "events").glob("*.md"))[-SUBMITTED_MONTHS:]:
        for line in f.read_text(encoding="utf-8").splitlines():
            text = line.strip().lstrip("-").strip()
            if text and SUBMIT_WORDS.search(text):
                lines.append(text[:300])
    return lines


class ContestScout:
    def __init__(self, bot, chat_id: int, client: Optional[Any] = None, ask: Callable[..., Dict[str, Any]] = llm.ask_skill,
                 writer: Optional[Any] = None, aside: Callable[[str], str] = aside_cli.run_aside,
                 outputs: Path = config.OUTPUTS, me: Path = config.ME,
                 clock: Callable[[], datetime] = config.now):
        self.bot = bot
        self.chat_id = chat_id
        self.client = client or gonghunt.Client()
        self.ask = ask
        self.writer = writer or write.Writer()
        self.aside = aside
        self.outputs = outputs
        self.me = me
        self.clock = clock
        self.grade_error: Optional[str] = None
        self.drafts_per_day = DRAFTS_PER_DAY

    def _send(self, text: str) -> None:
        self.bot.send_message(self.chat_id, text)

    def run(self) -> None:
        try:
            with store.lock("contest-scout"):
                self._run()
        except store.Busy:
            return

    # --- 정찰 ---

    def _grade(self, contests: List[Contest], today: date) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        if not contests:
            return {}, {}
        payload = {"today": today.isoformat(), "submitted": _submitted(self.me), "contests": [
            {"id": c["id"], "title": c.get("title", ""), "type": c.get("type", ""), "host": c.get("host", ""),
             "prize": _prize(c), "team": _team(c), "mode": c.get("modeLabel") or c.get("mode", ""),
             "apply_end": str(c.get("applyEnd") or ""), "days_left": _days_left(c, today),
             "eligibility": c.get("eligibility") or "", "fields": c.get("fields") or [],
             "rules": c.get("rules") or [], "deliverables": c.get("deliverables") or [],
             "description": str(c.get("description") or "")[:1500]} for c in contests]}
        try:
            res = self.ask("grade", payload, skill="kang-twin-contests", timeout=600)
        except llm.LLMError as e:
            self.grade_error = str(e)
            return {}, {}
        ids = {c["id"] for c in contests}
        grades = {str(g["id"]): g for g in res.get("grades") or []
                  if isinstance(g, dict) and str(g.get("id")) in ids and g.get("grade") in ("A", "B", "C")}
        best = res.get("best") if isinstance(res.get("best"), dict) else {}
        return grades, ({"id": str(best.get("id", "")), "why": str(best.get("why", ""))} if best else {})

    def _run(self) -> None:
        now = self.clock()
        today = now.date()
        try:
            listing = self.client.open_contests()
        except gonghunt.ApiError as e:
            self._send("[공모전 정찰] 공모전헌터를 못 읽음: %s" % e)
            heartbeat.beat("contest-scout", ok=False, note=str(e)[:200])
            return
        seen = store.load("contest_seen", {})
        details = []
        for c in listing:
            if c["id"] in seen:
                continue
            try:
                details.append(self.client.detail(c["id"]))
            except gonghunt.ApiError:
                continue
            seen[c["id"]] = today.isoformat()
        grades, best = self._grade(details, today)
        buckets: Dict[str, List[Contest]] = {"A": [], "B": [], "C": [], "-": []}
        for c in details:
            c["grade"] = grades.get(c["id"])
            buckets[c["grade"]["grade"] if c["grade"] else "-"].append(c)
        for key in buckets:
            buckets[key].sort(key=lambda c: (c["id"] != best.get("id"), self._verdict_rank(c), _deadline(c) or date.max))
        top = next((c for c in details if c["id"] == best.get("id")), None)

        rel = self._record(now, details, buckets, top, best) if details else None
        self._send(self._summary(now, details, buckets, top, best, rel))
        for c in buckets["A"][:CARDS]:
            self._send(self._card(c, today))

        cutoff = (today - SEEN_TTL).isoformat()
        store.save("contest_seen", {k: v for k, v in seen.items() if v >= cutoff})
        queue = store.load("contest_queue", {})
        for c in buckets["A"]:
            queue[c["id"]] = c
        store.save("contest_queue", queue)
        problem = self.grade_error and "등급 실패: %s" % self.grade_error
        heartbeat.beat("contest-scout", ok=not problem, note=(problem or "")[:200])
        self._drafts(today)

    @staticmethod
    def _verdict_rank(c: Contest) -> int:
        v = (c.get("grade") or {}).get("verdict")
        return VERDICTS.index(v) if v in VERDICTS else len(VERDICTS)

    # --- 기록과 알림 ---

    def _counts(self, details: List[Contest], buckets: Dict[str, List[Contest]]) -> str:
        text = "새 공모전 %d건 · A %d · B %d · C %d" % (len(details), len(buckets["A"]), len(buckets["B"]),
                                                    len(buckets["C"]))
        return text + (" · 등급 없음 %d" % len(buckets["-"]) if buckets["-"] else "")

    def _record(self, now: datetime, details: List[Contest], buckets: Dict[str, List[Contest]],
                top: Optional[Contest], best: Dict[str, str]) -> str:
        today = now.date()
        lines = ["---", "type: output", "status: active", "visibility: private", "source_kind: contest-scout",
                 "captured: %s" % now.strftime("%Y-%m-%d %H:%M"), "---", "",
                 "# 공모전 정찰 %s" % now.strftime("%Y-%m-%d %H:%M"), "", self._counts(details, buckets), ""]
        if top:
            lines += ["1순위: %s. %s" % (top["title"], best.get("why", "")), ""]
        for key, title in (("A", "A"), ("B", "B"), ("C", "C"), ("-", "등급 없음")):
            if not buckets[key]:
                continue
            lines += ["## %s" % title, ""]
            for c in buckets[key]:
                lines.append("- [%s](%s) · %s · %s · %s · %s" % (c["title"], gonghunt.view_url(c["id"]), c.get("host", ""),
                                                                 _prize(c), _team(c), _when(c, today)))
                g = c.get("grade") or {}
                if g:
                    lines.append("  - %s: %s" % (g.get("verdict", "-"), g.get("reason", "")))
                    if g.get("entry"):
                        lines.append("  - 낼 거리: %s (예상 %s)" % (g["entry"], g.get("effort", "-")))
                    lines += ["  - 안 맞는 점: %s" % x for x in _items(g, "gaps")]
                    lines += ["  - 확인 필요: %s" % x for x in _items(g, "check")]
            lines.append("")
        rel, n = "contests/%s.md" % now.strftime("%Y-%m-%d-%H%M"), 1
        while (self.outputs / rel).exists():
            n += 1
            rel = "contests/%s-%d.md" % (now.strftime("%Y-%m-%d-%H%M"), n)
        vault.create_note(rel, "\n".join(lines), self.outputs)
        return rel

    def _summary(self, now: datetime, details: List[Contest], buckets: Dict[str, List[Contest]],
                 top: Optional[Contest], best: Dict[str, str], rel: Optional[str]) -> str:
        lines = ["[공모전 정찰] %s" % now.strftime("%m/%d %H:%M")]
        if not details:
            lines.append("새 공모전 없음")
        else:
            lines.append(self._counts(details, buckets))
            if top:
                lines += ["", "1순위: %s" % top["title"], "  %s" % best.get("why", "")]
            if buckets["A"]:
                lines += ["", "A (아래 카드, 초안은 마감 가까운 순으로 하루 %d건)" % DRAFTS_PER_DAY]
                lines += ["• %s — %s · %s" % (c["title"], _prize(c), _when(c, now.date())) for c in buckets["A"]]
            if buckets["B"]:
                lines += ["", "B"]
                lines += ["• %s — %s: %s" % (c["title"], c["grade"].get("verdict", ""), c["grade"].get("reason", ""))
                          for c in buckets["B"]]
        if self.grade_error:
            lines += ["", "등급 매기기 실패: %s" % self.grade_error]
        if rel:
            lines += ["", "기록: %s/%s" % (self.outputs.name, rel)]
        return "\n".join(lines)

    def _card(self, c: Contest, today: date) -> str:
        g = c.get("grade") or {}
        v = g.get("verdict")
        lines = ["[A%s] %s" % (" · " + v if v else "", c["title"]),
                 " · ".join([_prize(c), _when(c, today), "팀 " + _team(c), c.get("modeLabel") or c.get("mode", "")]),
                 c.get("host", ""), ""]
        if g.get("entry"):
            lines.append("낼 거리: %s" % g["entry"])
        if g.get("effort"):
            lines.append("예상 작업: %s" % g["effort"])
        if _items(g, "gaps"):
            lines += ["안 맞는 점"] + ["- " + x for x in _items(g, "gaps")]
        if _items(g, "check"):
            lines += ["확인 필요"] + ["- " + x for x in _items(g, "check")]
        lines += ["", gonghunt.view_url(c["id"])]
        return "\n".join(lines)

    # --- 초안 ---

    def _drafts(self, today: date) -> None:
        quota = store.load("contest_drafts", {})
        done = quota.get("count", 0) if quota.get("date") == today.isoformat() else 0
        drafted = store.load("contest_drafted", {})
        queue = store.load("contest_queue", {})
        ready = []
        for cid, c in list(queue.items()):
            left = _days_left(c, today)
            if cid in drafted or left is None or left < DRAFT_MIN_DAYS:
                queue.pop(cid)
                continue
            ready.append(c)
        ready.sort(key=lambda c: _deadline(c) or date.max)
        for c in ready[:max(0, self.drafts_per_day - done)]:
            self._draft(c, today)
            drafted[c["id"]] = today.isoformat()
            queue.pop(c["id"], None)
            done += 1
            store.save("contest_drafted", drafted)
            store.save("contest_queue", queue)
            store.save("contest_drafts", {"date": today.isoformat(), "count": done})
        store.save("contest_queue", queue)

    def _probe(self, c: Contest) -> Tuple[Dict[str, Any], Optional[str]]:
        url = c.get("sourceUrl")
        if not url:
            return {}, "공고 원문 주소가 없음"
        try:
            form = llm.extract_json(self.aside(PROBE_PROMPT % url))
        except (llm.LLMError, OSError, subprocess.TimeoutExpired) as e:
            return {}, "공고 원문을 못 읽음 (%s)" % e
        return form, None

    def _brief(self, c: Contest, form: Dict[str, Any], today: date) -> str:
        g = c.get("grade") or {}
        questions = [q for q in form.get("questions") or [] if isinstance(q, dict) and q.get("label")]
        parts = ["%s(%s, 주최 %s)에 낼 제출물 초안. %s, %s, 팀 %s." % (c["title"], c.get("type", ""), c.get("host", ""),
                                                             _prize(c), _when(c, today), _team(c)),
                 "공모전 설명: %s" % str(c.get("description") or "")[:1500],
                 "참가 자격: %s" % (c.get("eligibility") or "-"),
                 "규칙: %s" % " / ".join(str(r) for r in c.get("rules") or []) if c.get("rules") else "",
                 "낼 거리: %s" % g.get("entry", "Me의 프로젝트 중 공모전 주제와 가장 가까운 것"),
                 "심사 기준: %s" % " / ".join(form.get("criteria") or []) if form.get("criteria") else ""]
        if questions:
            parts.append("제출 양식 문항(문항마다 '## 문항 이름' 제목 아래에 답을 쓴다, 글자 수 제한을 지킨다): " +
                         " / ".join("%s(%s)" % (q["label"], q.get("limit") or "제한 없음") for q in questions))
        else:
            parts.append("양식 문항을 모르니 아이디어 제안서로 쓴다. '## 제안 배경', '## 해결 방법', '## 구현 방법', "
                         "'## 기대 효과' 제목 아래 각각 쓴다.")
        parts.append("내 프로젝트에 없는 기능이나 성과를 지어내지 않는다. 새로 만들어야 하는 부분은 계획으로 쓴다.")
        if _wants_data(c, form):
            parts.append("데이터를 다루는 공모전이다. '## 실제 데이터' 제목 아래 쓸 데이터의 정확한 이름·제공기관·주소와 "
                         "그 데이터로 낼 표·그래프를 적는다. 아직 받아 돌리지 않은 데이터의 숫자는 쓰지 않고 '데이터 확보 필요'로 표시한다.")
        return "\n".join(p for p in parts if p)

    def _draft(self, c: Contest, today: date) -> None:
        form, problem = self._probe(c)
        try:
            out = self.writer.write("apply", self._brief(c, form, today), length=DRAFT_LENGTH, review=True,
                                    criteria=[str(x) for x in form.get("criteria") or []])
        except (llm.LLMError, ValueError, OSError) as e:
            self._send("[초안 실패] %s\n%s\n%s" % (c["title"], e, gonghunt.view_url(c["id"])))
            return
        g = c.get("grade") or {}
        checks = (["%s. 양식 확인 필요" % problem] if problem else []) + _items(g, "check") + \
            [str(u) for u in out.get("unknowns") or []] + ([str(form["notes"])] if form.get("notes") else []) + \
            ([DATA_CHECK] if _wants_data(c, form) else [])
        lines = ["---", "type: output", "status: draft", "visibility: private", "source_kind: contest-draft",
                 "contest: %s" % c["id"], "deadline: %s" % (_deadline(c) or ""), "---", "",
                 "# %s 초안" % c["title"], "",
                 "%s · %s · 팀 %s · %s" % (_prize(c), _when(c, today), _team(c), c.get("host", "")),
                 "공모전헌터: %s" % gonghunt.view_url(c["id"]), "공고 원문: %s" % (c.get("sourceUrl") or "-"), "",
                 "## 제출 방법", "",
                 "- 접수: %s" % (form.get("method") or "확인 필요"),
                 "- 주소: %s" % (form.get("apply_url") or c.get("sourceUrl") or "-"),
                 "- 회원가입·인증: %s" % ("필요" if form.get("account_required") else "필요 없음 또는 확인 필요"), "",
                 "## 체크리스트", ""]
        lines += ["- [ ] %s" % f for f in form.get("files") or []] + ["- [ ] 접수 마감 전에 제출 (%s)" % _when(c, today), ""]
        # 초안 안의 제목은 노트의 '## 초안' 아래로 한 단계 내린다. 같은 단계면 노트 구획이 깨진다.
        body = re.sub(r"^(#{1,5}) ", lambda m: "#" * min(len(m.group(1)) + 1, 6) + " ", out["text"], flags=re.M)
        lines += ["## 낼 거리", "", g.get("entry") or "-", "", "## 초안", "", body, ""]
        review = out.get("review") or {}
        if review:
            lines += ["## 검토", "", write.review_counts(review), ""] + write.review_lines(review) + [""]
        lines += ["## 점검", ""]
        issues = out.get("issues") or []
        lines += ["- %s [%s] %s" % (i[0], i[2], i[3]) for i in issues] or ["- 오류·경고 없음"]
        lines += ["", "## 확인 필요", ""] + (["- " + x for x in checks] or ["- 없음"])
        rel = "contests/drafts/%s-%s.md" % (today.isoformat(), c["id"][:8])
        if (self.outputs / rel).exists():
            rel = rel[:-3] + "-2.md"
        vault.create_note(rel, "\n".join(lines) + "\n", self.outputs)
        first = out["text"].strip().split("\n\n")
        lead = next((p for p in first if not p.startswith("#")), first[0])[:300]
        self._send("\n".join(["[초안] %s" % c["title"], "%s · %s" % (_prize(c), _when(c, today)),
                              "제출: %s%s" % (form.get("method") or "확인 필요",
                                              " (회원가입·인증 필요)" if form.get("account_required") else ""),
                              "", lead + ("…" if len(lead) == 300 else ""), "",
                              write.review_counts(review), "노트: %s/%s" % (self.outputs.name, rel)]))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="kt contestscout")
    p.add_argument("--drafts", type=int, default=DRAFTS_PER_DAY,
                   help="오늘 쓸 초안 수 상한. 예약 실행은 기본값, 직접 돌릴 때만 올린다")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    from .jobs import _bot_and_owner
    args = parse_args(argv)
    try:
        bot, owner = _bot_and_owner()
        scout = ContestScout(bot, owner)
        scout.drafts_per_day = args.drafts
        scout.run()
    except SystemExit:
        raise
    except Exception as e:
        notify.send("공모전 정찰이 죽었음: %s: %s" % (type(e).__name__, e))
        heartbeat.beat("contest-scout", ok=False, note="예외: %s" % type(e).__name__)
        raise


if __name__ == "__main__":
    main()
