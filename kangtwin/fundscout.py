"""자금 정찰(10:00, /funds). 출처 → 새 공고 → 규칙 거르기 → 등급 → 기록·알림 → A 마감 3일 전 알림.

지원금과 IR(투자자 앞 발표 기회)만 본다. 대출·보증·융자는 규칙 단계에서 빼고 건수만 센다(2026-10-19 사용자 결정).
"""
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, fundsources, heartbeat, llm, notify, remind, store, vault

Notice = Dict[str, Any]

# 업력 계산용 개업 달. 정확한 날짜는 사업자등록증으로 확인 전이라 1일로 둔다.
OPENED = date(2025, 7, 1)
SEEN_TTL = timedelta(days=400)
GRADE_BATCH = 40
CARDS = 6
SUMMARY_B = 5
SOON_DAYS = 7
REMIND_DAYS = 3
HEALTH_DAYS = 3
# 투자 유치는 사용자 숫자가 생길 때까지 보류하고 지원금만 노린다(2026-10-30 팀 11월 실행 계획).
# IR은 계속 모아 기록에 남기되 카드·마감 알림·마감 다가옴에는 올리지 않는다. 투자를 다시 보면 False.
IR_PAUSED = True
VERDICTS = {"A": "지금 낼 만함", "B": "준비하면 됨", "C": "해당 없음"}
KINDS = (("grant", "지원금"), ("ir", "IR"))

LOAN = re.compile(r"융자|대출|보증|이차보전|이자 ?지원|정책자금")
IR = re.compile(r"(?<![A-Za-z])IR(?![A-Za-z])|데모데이|피칭|투자유치|투자 ?연계|투자 ?상담|인베스터|투자설명회")
PRE_ONLY = re.compile(r"사업자\s?등록\s?\(?\s?개인\s?[,·ㆍ]?\s?법인\s?\)?\s?이?\s?없는|사업자\s?등록이\s?없는|예비창업자\s?(만|전용)")
MOVE = re.compile(r"이전\s?조건|이전\s?의무|이전하는\s?조건|이전해야")
CORP = re.compile(r"법인(사업자)?만|법인\s?기업만|법인에\s?한[함하정]|법인사업자\s?대상")
ONCE = re.compile(r"초기창업패키지|창업도약패키지|청년창업사관학교|창업중심대학")
SECTOR = re.compile(r"음식점|외식|도소매|제조기업|제조업|소공인|뿌리기업|농업인|어업인")
NON_CAPITAL = re.compile(r"비수도권")
# 교육·포럼·참관 모집은 돈이나 IR로 이어지지 않아 하루 수십 건씩 등급 단계만 무겁게 한다.
EDU = re.compile(r"교육생|수강생|교육\s?과정|특강|세미나|포럼|참관|아카데미|설명회|강연|웨비나|교육$")
EDU_BUT = re.compile(r"사업화|지원금|입주|선발|데모데이|경진|공모전|오디션|배치")
REGIONS = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "충청", "전북", "전남",
           "전라", "경북", "경남", "경상", "제주")
# 사는 곳. 설정의 home_regions 앞 두 개는 광역(예: 경기, 수도권), 그 뒤는 시군.
HOME = ("전국",) + tuple(config.SETTINGS.get("home_regions", ["경기", "수도권"])) + ("권역구분없음",)
TITLE_REGION = re.compile(r"^\s*[\[(【]\s*(%s)" % "|".join(REGIONS))


def years_open(today: date) -> float:
    return (today - OPENED).days / 365.25


def _norm(title: str) -> str:
    """같은 사업을 출처끼리 묶는 열쇠. 괄호 안 기관명과 기호를 지운다."""
    t = re.sub(r"[\[(【][^\])】]{0,30}[\])】]", "", title)
    return re.sub(r"[^0-9a-z가-힣]", "", t.lower())[:40]


def _days_left(n: Notice, today: date) -> Optional[int]:
    if not n.get("end"):
        return None
    return (datetime.strptime(n["end"], "%Y-%m-%d").date() - today).days


def _when(n: Notice, today: date) -> str:
    left = _days_left(n, today)
    if left is None:
        return "마감 모름"
    end = datetime.strptime(n["end"], "%Y-%m-%d").date()
    return "%d/%d (%s) 마감 · D-%d" % (end.month, end.day, remind.WEEKDAYS[end.weekday()], left)


def _text(n: Notice) -> str:
    return " ".join(str(n.get(k) or "") for k in ("title", "field", "target", "years", "summary"))


def rules(n: Notice, today: date) -> Tuple[Optional[str], Optional[str], List[str], str]:
    """(뺄 이유, C 이유, 표시, 종류). 뺄 이유가 있으면 기록에 건수만 남는다."""
    title, field, text = n.get("title", ""), n.get("field", ""), _text(n)
    left = _days_left(n, today)
    is_ir = bool(IR.search(title)) or ("행사" in field and bool(IR.search(str(n.get("summary", ""))[:600])))
    if left is not None and left < 0:
        return "마감 지남", None, [], "grant"
    if not is_ir and (LOAN.search(title) or re.search(r"융자|보증|정책자금", field) or field == "금융"):
        return "대출·보증", None, [], "grant"
    tags = ["IR"] if is_ir else []
    if ONCE.search(title):
        tags.append("평생 한 번")
    if MOVE.search(text):
        tags.append("주소 이전 필요")
    if CORP.search(text):
        tags.append("법인 필요")
    kind = "ir" if is_ir else "grant"
    years = set(re.findall(r"예비창업자|\d+년미만|\d+년이상", str(n.get("years") or "")))
    if years:
        age = years_open(today)
        fits = {y for y in years if (y.endswith("년미만") and age < int(y[:-3])) or y.endswith("년이상") and age >= int(y[:-3])}
        if not fits:
            return None, "예비 전용" if years == {"예비창업자"} else "업력 안 맞음", tags, kind
    # 자격 문구는 제목과 신청 대상에서만 본다. 본문에는 '예비창업자(사업자등록이 없는 자) 및 7년 이내'처럼
    # 여러 트랙이 같이 적혀 있어서, 본문까지 보면 기창업자도 받는 사업을 예비 전용으로 잘못 거른다.
    head = "%s %s" % (title, n.get("target", ""))
    if PRE_ONLY.search(head) and not re.search(r"\d+\s?년\s?(이내|미만)|기창업|창업기업|초기", head):
        return None, "예비 전용", tags, kind
    region = str(n.get("region") or "")
    # 경기기업비서는 설정한 시군의 접수 목록이라 지역이 이미 맞다. '(광주)'는 경기 광주시일 수도 있다.
    if n.get("source") != "egbiz" and TITLE_REGION.search(title) and not any(h in title for h in HOME[:3]):
        return None, "지역 안 맞음", tags, kind
    if region and not any(h in region for h in HOME) and any(r in region for r in REGIONS):
        return None, "지역 안 맞음", tags, kind
    if NON_CAPITAL.search(head) and "우대" not in head:
        return None, "지역 안 맞음", tags, kind
    ages = str(n.get("ages") or "")
    if "40세 이상" in ages and "39세" not in ages:
        return None, "대상 안 맞음", tags, kind
    if SECTOR.search(title):
        return None, "대상 안 맞음", tags, kind
    if not is_ir and EDU.search(title) and not EDU_BUT.search(title):
        return None, "교육·행사만", tags, kind
    return None, None, tags, kind


class FundScout:
    def __init__(self, bot, chat_id: int, http: Optional[fundsources.Http] = None,
                 ask: Callable[..., Dict[str, Any]] = llm.ask_skill, outputs: Path = config.OUTPUTS,
                 clock: Callable[[], datetime] = config.now, key: Optional[str] = None,
                 add_reminder: Callable[[datetime, str], Any] = remind.add):
        self.bot = bot
        self.chat_id = chat_id
        self.http = http or fundsources.Http()
        self.ask = ask
        self.outputs = outputs
        self.clock = clock
        self.key = config.datagokr_key() if key is None else key
        self.add_reminder = add_reminder
        self.grade_error: Optional[str] = None

    def _send(self, text: str) -> None:
        self.bot.send_message(self.chat_id, text)

    def run(self) -> None:
        try:
            with store.lock("fund-scout"):
                self._run()
        except store.Busy:
            return

    # --- 모으기와 거르기 ---

    def _fresh(self, notices: List[Notice], seen: Dict[str, str]) -> List[Notice]:
        """처음 보는 공고만, 같은 사업은 원본에 가까운 출처 하나로."""
        order = {s: i for i, s in enumerate(fundsources.SOURCES)}
        groups: Dict[str, List[Notice]] = {}
        for n in notices:
            if n["key"] in seen:
                continue
            groups.setdefault("t:%s|%s" % (_norm(n["title"]), n.get("end", "")), []).append(n)
        out = []
        for tkey, group in groups.items():
            group.sort(key=lambda n: order.get(n["source"], len(order)))
            first = group[0]
            first["tkey"] = tkey
            first["also"] = sorted({fundsources.NAMES.get(n["source"], n["source"]) for n in group[1:]})
            first["dupes"] = [n["key"] for n in group[1:]]
            if tkey in seen:
                # 다른 출처로 이미 알린 사업. 기록만 막고 다시 알리지 않는다.
                for k in [first["key"]] + first["dupes"]:
                    seen[k] = seen[tkey]
                continue
            out.append(first)
        return out

    def _grade(self, items: List[Notice], today: date) -> Dict[str, Dict[str, Any]]:
        grades: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(items), GRADE_BATCH):
            batch = items[i:i + GRADE_BATCH]
            payload = {"today": today.isoformat(), "years_open": round(years_open(today), 1), "notices": [
                {"id": n["key"], "title": n["title"], "org": n.get("org", ""),
                 "source": fundsources.NAMES.get(n["source"], n["source"]), "kind": n["kind"], "tags": n["tags"],
                 "field": n.get("field", ""), "region": n.get("region", ""), "target": n.get("target", ""),
                 "years": n.get("years", ""), "ages": n.get("ages", ""), "start": n.get("start", ""),
                 "end": n.get("end", ""), "days_left": _days_left(n, today), "summary": str(n.get("summary") or "")[:800]}
                for n in batch]}
            try:
                res = self.ask("grade", payload, skill="kang-twin-funds", timeout=600)
            except llm.LLMError as e:
                self.grade_error = str(e)
                continue
            ids = {n["key"] for n in batch}
            for g in res.get("grades") or []:
                if isinstance(g, dict) and str(g.get("id")) in ids and g.get("grade") in VERDICTS:
                    grades[str(g["id"])] = g
        return grades

    def _health(self, counts: Dict[str, int], errors: Dict[str, str], today: date) -> List[str]:
        """출처가 며칠째 0건이거나 실패하면 주소·형식이 바뀐 걸로 본다."""
        health = store.load("fund_health", {})
        warn = []
        for source in fundsources.SOURCES:
            rec = health.get(source) or {}
            if rec.get("date") == today.isoformat():
                continue
            # 벤처스퀘어는 새로 걸린 것만 세서 0건이 흔하다. 목록을 못 읽을 때만 오류로 온다.
            bad = source in errors or (source != "venturesquare" and counts.get(source) == 0)
            days = rec.get("days", 0) + 1 if bad else 0
            health[source] = {"days": days, "date": today.isoformat()}
            if days >= HEALTH_DAYS:
                warn.append("%s %d일째 0건이거나 실패 (주소나 형식이 바뀌었는지 확인)" % (fundsources.NAMES[source], days))
        store.save("fund_health", health)
        return warn

    def _run(self) -> None:
        now = self.clock()
        today = now.date()
        seen = store.load("fund_seen", {})
        notices, counts, errors = fundsources.collect(self.http, self.key, seen=lambda k: k in seen)
        fresh = self._fresh(notices, seen)
        dropped: Dict[str, int] = {}
        graded: List[Notice] = []
        rule_c: List[Notice] = []
        for n in fresh:
            drop, c_reason, tags, kind = rules(n, today)
            n["tags"], n["kind"] = tags, kind
            if drop:
                dropped[drop] = dropped.get(drop, 0) + 1
            elif c_reason:
                n["grade"] = {"grade": "C", "reason": c_reason}
                rule_c.append(n)
            else:
                graded.append(n)
        grades = self._grade(graded, today)
        buckets: Dict[str, List[Notice]] = {"A": [], "B": [], "C": list(rule_c), "-": []}
        for n in graded:
            g = grades.get(n["key"])
            n["grade"] = g
            if g and g.get("kind") in ("grant", "ir"):
                n["kind"] = g["kind"]
            buckets[g["grade"] if g else "-"].append(n)
        buckets["hold"] = []
        for key in ("A", "B"):
            buckets[key].sort(key=lambda n: (n.get("end") or "9999", n["title"]))
            if IR_PAUSED:
                buckets["hold"] += [n for n in buckets[key] if n["kind"] == "ir"]
                buckets[key] = [n for n in buckets[key] if n["kind"] != "ir"]

        rel = self._record(now, fresh, buckets, dropped, errors) if fresh or errors else None
        reminded = self._remind(buckets["A"], today, rel)
        soon = self._track(buckets, today)
        warn = self._health(counts, errors, today)
        if buckets["A"] or buckets["B"] or buckets["-"] or errors or warn or soon or self.grade_error:
            self._send(self._summary(now, fresh, buckets, dropped, errors, warn, soon, rel))
            for n in buckets["A"][:CARDS]:
                self._send(self._card(n, today, reminded.get(n["key"]), rel))

        for n in fresh:
            for k in [n["key"], n.get("tkey")] + n.get("dupes", []):
                if k:
                    seen[k] = today.isoformat()
        cutoff = (today - SEEN_TTL).isoformat()
        store.save("fund_seen", {k: v for k, v in seen.items() if v >= cutoff})
        failed = len(errors) == len(fundsources.SOURCES)
        problem = "; ".join(x for x in (self.grade_error and "등급 실패: %s" % self.grade_error,
                                        failed and "모든 출처 실패") if x)
        heartbeat.beat("fund-scout", ok=not problem, note=problem[:200])

    # --- 알림 예약과 추적 ---

    def _remind(self, items: List[Notice], today: date, rel: Optional[str]) -> Dict[str, str]:
        done = store.load("fund_reminded", {})
        out = {}
        for n in items:
            left = _days_left(n, today)
            if n["key"] in done or left is None or left <= REMIND_DAYS:
                continue
            end = datetime.strptime(n["end"], "%Y-%m-%d")
            at = (end - timedelta(days=REMIND_DAYS)).replace(hour=10, tzinfo=config.SEOUL)
            text = "%s 마감 %d일 남음\n%s%s" % (n["title"], REMIND_DAYS, n.get("url", ""),
                                            "\n노트: %s" % rel if rel else "")
            self.add_reminder(at, text)
            done[n["key"]] = at.strftime(remind.FMT)
            out[n["key"]] = at.strftime(remind.FMT)
        store.save("fund_reminded", done)
        return out

    def _track(self, buckets: Dict[str, List[Notice]], today: date) -> List[Notice]:
        """A·B로 알린 공고를 마감까지 들고 있다가 마감이 다가오면 요약에 다시 띄운다. 오늘 새로 온 것은 뺀다."""
        active = store.load("fund_active", {})
        soon = []
        for item in active.values():
            left = _days_left(item, today)
            if left is not None and 0 <= left <= SOON_DAYS:
                soon.append(item)
        for key in ("A", "B"):
            for n in buckets[key]:
                if n.get("end"):
                    active[n["key"]] = {"title": n["title"], "end": n["end"], "grade": key, "kind": n["kind"]}
        store.save("fund_active", {k: v for k, v in active.items() if (_days_left(v, today) or 0) >= 0})
        return sorted(soon, key=lambda v: v["end"])

    # --- 기록과 알림 ---

    @staticmethod
    def _counts(fresh: List[Notice], buckets: Dict[str, List[Notice]]) -> str:
        text = "새 공고 %d건 · A %d · B %d · C %d" % (len(fresh), len(buckets["A"]), len(buckets["B"]), len(buckets["C"]))
        text += " · IR 보류 %d" % len(buckets["hold"]) if buckets.get("hold") else ""
        return text + (" · 등급 없음 %d" % len(buckets["-"]) if buckets["-"] else "")

    @staticmethod
    def _dropped(dropped: Dict[str, int]) -> str:
        return ", ".join("%s %d건" % (k, v) for k, v in sorted(dropped.items()))

    @staticmethod
    def _items(g: Dict[str, Any], key: str) -> List[str]:
        v = g.get(key) or []
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]

    def _line(self, n: Notice, today: date) -> List[str]:
        g = n.get("grade") or {}
        lines = ["- [%s](%s) · %s · %s · %s" % (n["title"], n.get("url", ""), n.get("org", "") or "-", _when(n, today),
                                               fundsources.NAMES.get(n["source"], n["source"]))]
        for label, key in (("왜", "reason"), ("받을 것", "gain"), ("낼 거리", "entry")):
            if g.get(key):
                lines.append("  - %s: %s" % (label, g[key]))
        if self._items(g, "prep"):
            lines.append("  - 준비물: %s" % ", ".join(self._items(g, "prep")))
        if n.get("tags"):
            lines.append("  - 표시: %s" % ", ".join(n["tags"]))
        lines += ["  - 확인 필요: %s" % x for x in self._items(g, "check")]
        if n.get("also"):
            lines.append("  - 같이 실린 곳: %s" % ", ".join(n["also"]))
        return lines

    def _record(self, now: datetime, fresh: List[Notice], buckets: Dict[str, List[Notice]],
                dropped: Dict[str, int], errors: Dict[str, str]) -> str:
        today = now.date()
        lines = ["---", "type: output", "status: active", "visibility: private", "source_kind: fund-scout",
                 "captured: %s" % now.strftime("%Y-%m-%d %H:%M"), "---", "",
                 "# 자금 정찰 %s" % now.strftime("%Y-%m-%d %H:%M"), "", self._counts(fresh, buckets)]
        if dropped:
            lines.append("규칙으로 뺌: %s" % self._dropped(dropped))
        lines.append("")
        for kind, label in KINDS:
            for key in ("A", "B"):
                items = [n for n in buckets[key] if n["kind"] == kind]
                if items:
                    lines += ["## %s %s" % (label, key), ""]
                    for n in items:
                        lines += self._line(n, today)
                    lines.append("")
        if buckets.get("hold"):
            lines += ["## IR 보류 (투자 보류 중이라 기록만)", ""]
            for n in buckets["hold"]:
                lines += self._line(n, today)[:1] + ["  - 등급: %s" % (n.get("grade") or {}).get("grade", "-")] + \
                    self._line(n, today)[1:]
            lines.append("")
        if buckets["-"]:
            lines += ["## 등급 없음", ""]
            for n in buckets["-"]:
                lines += self._line(n, today)
            lines.append("")
        if buckets["C"]:
            lines += ["## C", ""]
            lines += ["- [%s](%s) · %s · %s" % (n["title"], n.get("url", ""), fundsources.NAMES.get(n["source"], n["source"]),
                                               (n.get("grade") or {}).get("reason", "")) for n in buckets["C"]]
            lines.append("")
        if errors:
            lines += ["## 못 읽은 출처", ""] + ["- %s: %s" % (fundsources.NAMES[s], e) for s, e in errors.items()] + [""]
        lines += ["출처: %s. 공고 원문과 출처 이름을 함께 남긴다." % ", ".join(fundsources.NAMES.values())]
        rel, n = "funds/%s.md" % today.isoformat(), 1
        while (self.outputs / rel).exists():
            n += 1
            rel = "funds/%s-%d.md" % (today.isoformat(), n)
        vault.create_note(rel, "\n".join(lines) + "\n", self.outputs)
        return rel

    def _summary(self, now: datetime, fresh: List[Notice], buckets: Dict[str, List[Notice]], dropped: Dict[str, int],
                 errors: Dict[str, str], warn: List[str], soon: List[Notice], rel: Optional[str]) -> str:
        today = now.date()
        lines = ["[자금 정찰] %d/%d (%s) %s" % (now.month, now.day, remind.WEEKDAYS[now.weekday()], now.strftime("%H:%M"))]
        if fresh:
            lines.append(self._counts(fresh, buckets))
            extra = [x for x in (dropped and "%s 뺐음" % self._dropped(dropped),
                                 buckets["C"] and "C %d건은 기록만" % len(buckets["C"])) if x]
            if extra:
                lines.append(", ".join(extra))
        else:
            lines.append("새 공고 없음")
        for kind, label in KINDS:
            rows = []
            for key in ("A", "B"):
                items = [n for n in buckets[key] if n["kind"] == kind]
                # B는 첫날처럼 많이 몰리면 요약이 길어진다. 마감 가까운 것만 보이고 나머지는 기록에 둔다.
                shown = items if key == "A" else items[:SUMMARY_B]
                for n in shown:
                    g = n.get("grade") or {}
                    note = self._items(g, "check")[:1] or [g.get("reason", "")]
                    rows += ["%s %s" % (key, n["title"]), "  %s%s" % (_when(n, today), " · " + note[0] if note[0] else "")]
                if len(items) > len(shown):
                    rows.append("B %d건 더 (기록에)" % (len(items) - len(shown)))
            if rows:
                lines += ["", label] + rows
        if buckets.get("hold"):
            lines += ["", "IR %d건은 기록만 (투자 보류 중)" % len(buckets["hold"])]
        if buckets["-"]:
            lines += ["", "등급 없음 %d건 (기록에 목록)" % len(buckets["-"])]
        if soon:
            lines += ["", "마감 다가옴"] + ["• %s · %s" % (v["title"], _when(v, today)) for v in soon]
        if self.grade_error:
            lines += ["", "등급 매기기 실패: %s" % self.grade_error]
        if errors:
            lines += ["", "못 읽은 출처"] + ["• %s: %s" % (fundsources.NAMES[s], e[:120]) for s, e in errors.items()]
        if warn:
            lines += ["", "출처 경보"] + ["• " + w for w in warn]
        if rel:
            lines += ["", "기록: %s/%s" % (self.outputs.name, rel)]
        return "\n".join(lines)

    def _card(self, n: Notice, today: date, reminded: Optional[str], rel: Optional[str]) -> str:
        g = n.get("grade") or {}
        lines = ["[A %s] %s" % (VERDICTS["A"], n["title"]), _when(n, today),
                 " · ".join(x for x in (n.get("org", ""), g.get("gain", "")) if x)]
        if g.get("reason"):
            lines.append("왜: %s" % g["reason"])
        if g.get("entry"):
            lines.append("낼 거리: %s" % g["entry"])
        if self._items(g, "prep"):
            lines.append("준비물: %s" % ", ".join(self._items(g, "prep")))
        if n.get("tags"):
            lines.append("표시: %s" % ", ".join(n["tags"]))
        if self._items(g, "check"):
            lines += ["확인 필요"] + ["- " + x for x in self._items(g, "check")]
        if reminded:
            at = datetime.strptime(reminded, remind.FMT)
            lines.append("알림: %d/%d (%s) %s D-%d 알림 걸어 둠" % (at.month, at.day, remind.WEEKDAYS[at.weekday()],
                                                           at.strftime("%H:%M"), REMIND_DAYS))
        lines += ["출처: %s" % fundsources.NAMES.get(n["source"], n["source"]), n.get("url", "")]
        return "\n".join(l for l in lines if l)


def main() -> None:
    from .jobs import _bot_and_owner
    try:
        bot, owner = _bot_and_owner()
        FundScout(bot, owner).run()
    except SystemExit:
        raise
    except Exception as e:
        notify.send("자금 정찰이 죽었음: %s: %s" % (type(e).__name__, e))
        heartbeat.beat("fund-scout", ok=False, note="예외: %s" % type(e).__name__)
        raise


if __name__ == "__main__":
    main()
