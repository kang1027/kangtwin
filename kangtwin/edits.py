"""결재 때 고친 초안을 Me/voice/edits/에 수정 기록으로 남기고 수정률을 잰다."""
import argparse
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional, Tuple

from . import config, vault

REGISTERS = ("apply", "message", "mail")
MAX_PAIRS = 60
SIMILAR = 0.5


def _norm(text: str) -> str:
    return re.sub(r"[\s`*#>|-]", "", text)


def change_rate(draft: str, final: str) -> float:
    """공백과 마크다운 기호를 뺀 글자 기준으로 바뀐 비율. 0이면 그대로, 1이면 전부 다시 씀."""
    a, b = _norm(draft), _norm(final)
    if not a and not b:
        return 0.0
    return round(1 - SequenceMatcher(None, a, b, autojunk=False).ratio(), 2)


def _sentences(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return out


def _pair(olds: List[str], news: List[str]) -> List[Tuple[str, str]]:
    pairs, used = [], set()
    for old in olds:
        best, score = None, SIMILAR
        for k, new in enumerate(news):
            if k in used:
                continue
            r = SequenceMatcher(None, old, new, autojunk=False).ratio()
            if r > score:
                best, score = k, r
        if best is None:
            pairs.append((old, ""))
        else:
            used.add(best)
            pairs.append((old, news[best]))
    return pairs + [("", new) for k, new in enumerate(news) if k not in used]


def changed_sentences(draft: str, final: str) -> List[Tuple[str, str]]:
    """바뀐 문장 (전, 후). 지운 문장은 후가 "", 새로 쓴 문장은 전이 ""."""
    a, b = _sentences(draft), _sentences(final)
    pairs: List[Tuple[str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            pairs += _pair(a[i1:i2], b[j1:j2])
    return pairs[:MAX_PAIRS]


def _slug(target: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "-", target).strip("-")[:40] or "edit"


def _note(register: str, target: str, draft: str, final: str, today: datetime) -> str:
    rate = change_rate(draft, final)
    lines = ["---", "type: edit", "status: active", "visibility: private", "register: %s" % register,
             "target: %s" % json.dumps(target, ensure_ascii=False), "date: %s" % today.strftime("%Y-%m-%d"),
             "draft_chars: %d" % len(draft.strip()), "final_chars: %d" % len(final.strip()),
             "change_rate: %.2f" % rate, "updated: %s" % today.strftime("%Y-%m-%d"), "---", "",
             "# %s: 초안 → 최종본" % target, "",
             "수정률 %d%% (공백 제외 글자 기준)." % round(rate * 100), "", "## 바뀐 문장", ""]
    for old, new in changed_sentences(draft, final):
        if old and new:
            lines += ["- 전: %s" % old, "  후: %s" % new]
        elif old:
            lines.append("- 삭제: %s" % old)
        else:
            lines.append("- 추가: %s" % new)
    lines += ["", "## 규칙 후보", ""]
    return "\n".join(lines)


def record(register: str, target: str, draft: str, final: str, root: Path = config.ME,
           today: Optional[datetime] = None, slug: Optional[str] = None) -> Path:
    if register not in REGISTERS:
        raise ValueError("레지스터는 %s 중 하나: %r" % (", ".join(REGISTERS), register))
    today = today or config.now()
    base = "voice/edits/%s-%s" % (today.strftime("%Y-%m-%d"), _slug(slug or target))
    rel, n = base + ".md", 1
    while (root / rel).exists():
        n += 1
        rel = "%s-%d.md" % (base, n)
    return vault.create_note(rel, _note(register, target, draft, final, today), root)


def main(argv: Optional[List[str]] = None, root: Path = config.ME, today: Optional[datetime] = None) -> None:
    p = argparse.ArgumentParser(prog="kt edits")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="초안과 최종본을 수정 기록으로 남김")
    r.add_argument("--register", required=True, choices=REGISTERS)
    r.add_argument("--target", required=True)
    r.add_argument("--draft", required=True)
    r.add_argument("--final", required=True)
    r.add_argument("--slug")
    args = p.parse_args(argv)
    draft = Path(args.draft).read_text(encoding="utf-8")
    final = Path(args.final).read_text(encoding="utf-8")
    path = record(args.register, args.target, draft, final, root, today, args.slug)
    print("%s (수정률 %d%%)" % (path, round(change_rate(draft, final) * 100)))


if __name__ == "__main__":
    main()
