"""길포일 블라인드 테스트. 승인본 문단과 같은 주제로 클론이 쓴 문단을 섞어 텔레그램으로 고르게 한다."""
import random
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config, llm, store, vault, write

N_EACH = 5
MIN_CHARS, MAX_CHARS = 120, 450
# 통과: 클론을 내 글로 본 비율이 이 이상. 정답률로 재면 내 글을 기억해서 맞힌 것까지 클론 탓이 된다
# (2026-10-10 세 번째 테스트: 정답 7/10이었지만 클론 5개 중 3개를 내 글로 봤다).
PASS_RATE = 0.5
WORKERS = 3
# 견본 frontmatter에 blind: true인 것(내가 직접 쓰거나 문장 단위로 고친 글)만 '내 글'로 쓴다.
# Claude가 쓰고 내가 승인만 한 글은 나도 클론으로 본다(2026-10-09 두 번째 테스트).
BLIND = re.compile(r"^blind:\s*true\s*$", re.M)


def _body_paragraphs(text: str) -> List[Dict[str, Any]]:
    body = text.split("\n## 원문\n", 1)[1] if "\n## 원문\n" in text else ""
    out, first = [], True
    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            first = True
            continue
        if block.startswith(("-", "|", ">", "---", "•")):
            continue
        joined = " ".join(line.strip() for line in block.splitlines())
        if MIN_CHARS <= len(joined) <= MAX_CHARS:
            out.append({"text": joined, "first": first})
        first = False
    return out


def candidates(root: Path, register: str) -> List[Dict[str, Any]]:
    out = []
    folder = root / "voice" / "exemplars"
    for path in sorted(folder.glob("%s-*.md" % register)) if folder.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        if not BLIND.search(text.split("\n---\n", 1)[0]):
            continue
        for p in _body_paragraphs(text):
            out.append(dict(p, source="voice/exemplars/" + path.name))
    return out


def pick(cands: List[Dict[str, Any]], n: int, seed: Any = None) -> List[Dict[str, Any]]:
    """첫 문단(기억하기 쉬움)은 뒤로 미루고, 견본마다 돌아가며 고른다."""
    rng = random.Random(seed)
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for c in cands:
        by_source.setdefault(c["source"], []).append(c)
    for items in by_source.values():
        rng.shuffle(items)
        items.sort(key=lambda c: c["first"])
    order = sorted(by_source)
    rng.shuffle(order)
    picked: List[Dict[str, Any]] = []
    for want_first in (False, True):
        progress = True
        while len(picked) < n and progress:
            progress = False
            for src in order:
                pool = [c for c in by_source[src] if c["first"] == want_first and c not in picked]
                if pool and len(picked) < n:
                    picked.append(pool[0])
                    progress = True
    return picked


def _result(items: List[Dict[str, Any]], answers: List[str]) -> Dict[str, Any]:
    pairs = list(zip(items, answers))
    clones = [i + 1 for i, (item, _) in enumerate(pairs) if item["truth"] == "clone"]
    fooled = [i + 1 for i, (item, a) in enumerate(pairs) if item["truth"] == "clone" and a == "me"]
    doubted = [i + 1 for i, (item, a) in enumerate(pairs) if item["truth"] == "me" and a == "clone"]
    n_clone, n_me = len(clones), len(items) - len(clones)
    return {"correct": sum(1 for item, a in pairs if item["truth"] == a), "clones": clones, "fooled": fooled,
            "doubted": doubted, "n_clone": n_clone, "n_me": n_me, "clone_as_me": len(fooled),
            "me_as_me": n_me - len(doubted), "passed": n_clone > 0 and len(fooled) / n_clone >= PASS_RATE}


class BlindTest:
    def __init__(self, bot, chat_id: int, ask: Callable[..., Dict[str, Any]] = llm.ask_skill,
                 root: Path = config.ME, clock: Callable[[], datetime] = config.now,
                 writer: Optional[Any] = None, seed: Any = None, register: str = "apply"):
        self.bot = bot
        self.chat_id = chat_id
        self.ask = ask
        self.root = root
        self.clock = clock
        self.writer = writer or write.Writer(ask=ask, root=root)
        self.seed = seed
        self.register = register

    def _send(self, text: str, buttons=None) -> None:
        self.bot.send_message(self.chat_id, text, buttons)

    def _locked(self, fn: Callable[[], None]) -> None:
        try:
            with store.lock("blind"):
                fn()
        except store.Busy:
            self._send("블라인드 테스트 준비 중임. 끝나면 첫 문단이 옴")

    def _send_item(self, st: Dict[str, Any]) -> None:
        i = st["idx"]
        self._send("[블라인드 %d/%d]\n\n%s" % (i + 1, len(st["items"]), st["items"][i]["text"]),
                   [[("내 글", "bt:%s:%d:me" % (st["id"], i)), ("클론", "bt:%s:%d:clone" % (st["id"], i))]])

    # --- 시작 ---

    def start(self) -> None:
        self._locked(self._start)

    def _start(self) -> None:
        st = store.load("blind", {})
        if st.get("status") == "running":
            if st["idx"] >= len(st["items"]):
                self._finish(st)
                return
            self._send("하던 블라인드 테스트 이어서 함")
            self._send_item(st)
            return
        self._send("블라인드 테스트 준비함. 승인본 문단 %d개 고르고, 클론은 다른 문단 %d개의 주제로 씀. 10~20분 걸림"
                   % (N_EACH, N_EACH))
        tid = secrets.token_hex(3)
        store.save("blind", {"id": tid, "status": "preparing", "register": self.register,
                             "started": self.clock().isoformat()})
        try:
            items = self._prepare(tid)
        except Exception as e:
            store.save("blind", {})
            self._send("블라인드 테스트 준비 실패: %s: %s" % (type(e).__name__, e))
            return
        st = {"id": tid, "status": "running", "register": self.register, "started": self.clock().isoformat(),
              "items": items, "idx": 0, "answers": []}
        store.save("blind", st)
        self._send("준비 끝. 문단마다 내가 쓴 건지 클론이 쓴 건지 골라줘. 내 글 %d개, 클론 %d개 섞여 있음"
                   % (N_EACH, N_EACH))
        self._send_item(st)

    def _prepare(self, tid: str) -> List[Dict[str, Any]]:
        # 보여 줄 내 문단과 클론 주제로 쓸 문단을 따로 고른다. 같은 문단을 둘 다 쓰면 짝끼리 비교하는
        # 문제가 되고, 클론은 원문을 바꿔 말하기만 한다(2026-10-09 첫 테스트에서 그랬음).
        picked = pick(candidates(self.root, self.register), 2 * N_EACH,
                      seed=self.seed if self.seed is not None else tid)
        if len(picked) < 2 * N_EACH:
            raise ValueError("고를 승인본 문단이 모자람 (%d/%d)" % (len(picked), 2 * N_EACH))
        mine, seeds = picked[0::2], picked[1::2]
        res = self.ask("brief", {"paragraphs": [{"id": "p%d" % i, "text": p["text"], "source": p["source"]}
                                                for i, p in enumerate(seeds)]}, skill="kang-twin-write")
        briefs = {b["id"]: b for b in res.get("briefs") or [] if isinstance(b, dict)}

        def clone(i: int) -> Dict[str, Any]:
            p, b = seeds[i], briefs.get("p%d" % i)
            if not b or not str(b.get("brief", "")).strip():
                raise llm.LLMError("p%d 브리프가 없음" % i)
            out = self.writer.write(self.register, str(b["brief"]), length=b.get("length") or len(p["text"]),
                                    exclude=[p["source"]], paragraph_only=True)
            return {"text": out["text"], "truth": "clone", "source": p["source"], "brief": str(b["brief"]),
                    "errors": len(write.errors(out["issues"]))}

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            clones = list(pool.map(clone, range(len(seeds))))
        items = [{"text": p["text"], "truth": "me", "source": p["source"]} for p in mine] + clones
        random.Random(tid).shuffle(items)
        return items

    # --- 답 ---

    def answer(self, text: str) -> None:
        self._locked(lambda: self._answer(text))

    def _answer(self, text: str) -> None:
        tid, idx, guess = (text.split(":") + ["", "", ""])[:3]
        st = store.load("blind", {})
        if st.get("status") != "running" or st.get("id") != tid or not idx.isdigit() \
                or int(idx) != st.get("idx") or guess not in ("me", "clone"):
            self._send("지난 문항 버튼임")
            return
        st["answers"].append(guess)
        st["idx"] += 1
        store.save("blind", st)
        if st["idx"] < len(st["items"]):
            self._send_item(st)
        else:
            self._finish(st)

    def _finish(self, st: Dict[str, Any]) -> None:
        items, answers = st["items"], st["answers"]
        n = len(items)
        r = _result(items, answers)
        verdict = "통과" if r["passed"] else "미달"
        now = self.clock()
        # 기록이 중간에 실패하면 상태를 running으로 두고, 다음 /blind가 여기부터 다시 한다.
        rel = st.setdefault("note", "voice/blind/%s-%s.md" % (now.strftime("%Y-%m-%d"), st["id"]))
        if not (self.root / rel).exists():
            vault.create_note(rel, self._note(st, r), self.root)
        store.save("blind", st)
        log = self.root / "voice" / "blind-tests.md"
        if not (log.exists() and ("[[%s/%s]]" % (self.root.name, rel[:-3])) in log.read_text(encoding="utf-8")):
            vault.append_log(log,
                             "- %s %s 클론을 내 글로 본 것 %d/%d, 내 글을 내 글로 본 것 %d/%d (정답 %d/%d) %s. [[%s/%s]]"
                             % (now.strftime("%Y-%m-%d %H:%M"), st["register"], r["clone_as_me"], r["n_clone"],
                                r["me_as_me"], r["n_me"], r["correct"], n, verdict, self.root.name, rel[:-3]),
                             title="블라인드 테스트 기록")
        st["status"] = "done"
        st["result"] = {"correct": r["correct"], "n": n, "clone_as_me": r["clone_as_me"], "passed": r["passed"]}
        store.save("blind", st)
        lines = ["[블라인드 결과] 클론을 내 글로 본 비율 %d/%d → %s (통과선 %d%% 이상)"
                 % (r["clone_as_me"], r["n_clone"], verdict, round(PASS_RATE * 100)),
                 "내 글을 내 글로 본 비율 %d/%d, 정답 %d/%d" % (r["me_as_me"], r["n_me"], r["correct"], n),
                 "", "클론이었던 것: %s" % ", ".join("%d번" % i for i in r["clones"]),
                 "클론인데 내 글로 본 것: %s" % (", ".join("%d번" % i for i in r["fooled"]) or "없음"),
                 "내 글인데 클론으로 본 것: %s" % (", ".join("%d번" % i for i in r["doubted"]) or "없음"),
                 "", "자세한 건 %s/%s" % (self.root.name, rel)]
        self._send("\n".join(lines))

    def _note(self, st: Dict[str, Any], r: Dict[str, Any]) -> str:
        n = len(st["items"])
        lines = ["---", "type: blind-test", "status: active", "visibility: private",
                 "register: %s" % st["register"], "date: %s" % self.clock().strftime("%Y-%m-%d"),
                 "items: %d" % n, "correct: %d" % r["correct"],
                 "clone_as_me: %d/%d" % (r["clone_as_me"], r["n_clone"]), "me_as_me: %d/%d" % (r["me_as_me"], r["n_me"]),
                 "passed: %s" % ("true" if r["passed"] else "false"), "---", "",
                 "# 블라인드 테스트 %s (%s)" % (self.clock().strftime("%Y-%m-%d"), st["register"]), "",
                 "클론을 내 글로 본 것 %d/%d, 내 글을 내 글로 본 것 %d/%d, 정답 %d/%d. 통과선은 클론을 내 글로 본 비율 %d%% 이상."
                 % (r["clone_as_me"], r["n_clone"], r["me_as_me"], r["n_me"], r["correct"], n,
                    round(PASS_RATE * 100)), ""]
        for i, (item, a) in enumerate(zip(st["items"], st["answers"])):
            truth = "내 글" if item["truth"] == "me" else "클론"
            guess = "내 글" if a == "me" else "클론"
            mark = "맞힘" if item["truth"] == a else "틀림"
            lines += ["## %d. %s · 고른 답 %s · %s" % (i + 1, truth, guess, mark), "",
                      "- 원문 견본: [[%s/%s]]" % (self.root.name, item["source"][:-3])]
            if item["truth"] == "clone":
                lines.append("- 브리프: %s" % item["brief"])
                if item.get("errors"):
                    lines.append("- 점검 ERROR %d개 남음" % item["errors"])
            lines += ["", "> " + item["text"].replace("\n", "\n> "), ""]
        return "\n".join(lines)
