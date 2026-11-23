"""말투 팩으로 글을 쓰고 점검한다. 쓰기는 kang-twin-write 스킬, 점검은 check_voice 스크립트,
검토(사실 근거·심사 기준·AI 말투)는 kang-twin-review 스킬."""
import argparse
import importlib.util
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import config, llm

REGISTERS = ("apply", "message", "mail")
SOURCE_FOLDERS = ("facts", "projects", "stories", "claims")
CHECK_SCRIPT = config.REPO / "skills" / "voice-check" / "scripts" / "check_voice.py"
MAX_REWRITES = 1
# 가이드·견본·원본 노트를 다 읽고 쓰느라 인터뷰보다 오래 걸린다 (시험에서 한 편에 6분 남짓).
TIMEOUT = 600
REVIEW_TIMEOUT = 600
FACT_PROBLEMS = ("근거 없음", "다름")
CRITERIA_STATES = ("빠짐", "약함", "다룸")
TONE_KINDS = ("AI 말투", "어색한 표현")

Issue = Tuple[str, int, str, str, str]
_check_module = None


def check_voice(text: str, register: str) -> List[Issue]:
    global _check_module
    if _check_module is None:
        spec = importlib.util.spec_from_file_location("check_voice", CHECK_SCRIPT)
        _check_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_check_module)
    return _check_module.check_text(text, register)


def errors(issues: List[Issue]) -> List[Issue]:
    return [i for i in issues if i[0] == "ERROR"]


def reading_list(register: str, root: Path, exclude: Sequence[str] = ()) -> Dict[str, Any]:
    """스킬에 넘길 읽을거리. Me 기준 상대 경로. 메시지·메일은 지원서 견본도 같이 본다."""
    prefixes = (register + "-",) + (("apply-",) if register in ("message", "mail") else ())
    exemplar_dir = root / "voice" / "exemplars"
    exemplars = sorted("voice/exemplars/" + p.name for p in exemplar_dir.glob("*.md")
                       if p.name.startswith(prefixes)) if exemplar_dir.is_dir() else []
    sources = []
    for folder in SOURCE_FOLDERS:
        if (root / folder).is_dir():
            sources += sorted("%s/%s" % (folder, p.name) for p in (root / folder).glob("*.md"))
    return {"guide": "voice/registers/%s.md" % register,
            "exemplars": [e for e in exemplars if e not in set(exclude)],
            "sources": sources}


def _text(res: Dict[str, Any]) -> str:
    text = res.get("text")
    if not isinstance(text, str) or not text.strip():
        raise llm.LLMError("글이 비어 있음")
    return text.strip()


def _issue_dicts(issues: List[Issue]) -> List[Dict[str, Any]]:
    return [{"level": l, "code": c, "message": m, "snippet": s} for l, _, c, m, s in issues]


def _rows(res: Dict[str, Any], key: str, field: str, allowed: Sequence[str],
          texts: Sequence[str]) -> List[Dict[str, str]]:
    """texts[0]이 비었거나 field 값이 allowed 밖인 줄은 버린다."""
    rows = []
    for r in res.get(key) or []:
        if not isinstance(r, dict) or r.get(field) not in allowed or not str(r.get(texts[0]) or "").strip():
            continue
        row = {k: str(r.get(k) or "").strip() for k in texts}
        row[field] = r[field]
        rows.append(row)
    return rows


def _findings(res: Dict[str, Any]) -> Dict[str, Any]:
    """검토 스킬의 답에서 모양이 맞는 지적만 남긴다."""
    return {"facts": _rows(res, "facts", "problem", FACT_PROBLEMS, ("quote", "source", "note")),
            "criteria": _rows(res, "criteria", "status", CRITERIA_STATES, ("criterion", "note")),
            "tone": _rows(res, "tone", "kind", TONE_KINDS, ("quote", "why", "fix")),
            "summary": str(res.get("summary") or "")}


def _needs_fix(found: Dict[str, Any]) -> bool:
    return bool(found["facts"] or found["tone"] or any(c["status"] != "다룸" for c in found["criteria"]))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _mark(found: Dict[str, Any], before: str, after: str) -> None:
    """인용한 구간이 최종본에 그대로 있으면 남음. 검토자가 초안에 없는 문장을 인용했으면 따로 표시한다."""
    before, after = _squash(before), _squash(after)
    for row in found["facts"] + found["tone"]:
        quote = _squash(row["quote"])
        row["state"] = "남음" if quote in after else ("고침" if quote in before else "초안에 없는 인용")


def review_lines(review: Dict[str, Any]) -> List[str]:
    """검토 결과를 노트에 넣을 목록 줄로. 심사 기준은 빠짐·약함을 먼저 둔다."""
    if not review:
        return []
    lines = ["- 검토 문제: %s" % review["error"]] if review.get("error") else []
    for f in review.get("facts", []):
        why = ", ".join(x for x in (f["note"], f["source"]) if x)
        lines.append('- [%s] 사실 %s: "%s"%s' % (f["state"], f["problem"], f["quote"], " (%s)" % why if why else ""))
    for c in sorted(review.get("criteria", []), key=lambda c: CRITERIA_STATES.index(c["status"])):
        lines.append("- 심사 기준 %s: %s%s" % (c["status"], c["criterion"], " (%s)" % c["note"] if c["note"] else ""))
    for t in review.get("tone", []):
        lines.append('- [%s] %s: "%s"%s%s' % (t["state"], t["kind"], t["quote"], " (%s)" % t["why"] if t["why"] else "",
                                             " → " + t["fix"] if t["fix"] else ""))
    return lines or (["- 걸린 것 없음"] if "facts" in review else [])


def review_counts(review: Dict[str, Any]) -> str:
    """알림에 붙일 한 줄."""
    if not review:
        return ""
    if "facts" not in review:
        return "검토 실패: %s" % review.get("error", "")
    weak = sum(c["status"] != "다룸" for c in review["criteria"])
    if not (review["facts"] or weak or review["tone"]):
        return "검토: 걸린 것 없음"
    left = sum(r["state"] == "남음" for r in review["facts"] + review["tone"])
    text = "검토: 사실 %d · 기준 빠짐·약함 %d · 말투 %d" % (len(review["facts"]), weak, len(review["tone"]))
    if review.get("rewritten"):
        return text + " → 고쳐 씀, 남은 것 %d" % left
    return text + (" → 못 고침: %s" % review["error"] if review.get("error") else "")


class Writer:
    def __init__(self, ask: Callable[..., Dict[str, Any]] = llm.ask_skill,
                 check: Callable[[str, str], List[Issue]] = check_voice, root: Path = config.ME):
        self.ask = ask
        self.check = check
        self.root = root

    def write(self, register: str, brief: str, length: Optional[int] = None, exclude: Sequence[str] = (),
              paragraph_only: bool = False, review: bool = False, criteria: Sequence[str] = ()) -> Dict[str, Any]:
        """brief대로 쓰고 점검한다. ERROR가 나오면 한 번 다시 쓰게 한다. exclude는 읽으면 안 되는 상대 경로.
        review면 쓴 글을 새 컨텍스트에서 검토하고, 걸린 게 있으면 한 번 더 고쳐 쓴다. criteria는 심사 기준."""
        if register not in REGISTERS:
            raise ValueError("레지스터는 %s 중 하나: %r" % (", ".join(REGISTERS), register))
        deny = [str(self.root / rel) for rel in exclude]
        base = dict(reading_list(register, self.root, exclude), register=register, me=str(self.root))
        res = self.ask("write", dict(base, brief=brief, length=length, paragraph_only=paragraph_only),
                       skill="kang-twin-write", deny=deny, timeout=TIMEOUT)
        text = _text(res)
        issues = self.check(text, register)
        rewrites = 0
        while errors(issues) and rewrites < MAX_REWRITES:
            res2 = self.ask("rewrite", dict(base, brief=brief, length=length, paragraph_only=paragraph_only,
                                            text=text, issues=_issue_dicts(issues)),
                            skill="kang-twin-write", deny=deny, timeout=TIMEOUT)
            text = _text(res2)
            issues = self.check(text, register)
            rewrites += 1
        out = {"text": text, "issues": issues, "rewrites": rewrites,
               "sources": res.get("sources") or [], "unknowns": res.get("unknowns") or []}
        if review:
            job = dict(brief=brief, length=length, paragraph_only=paragraph_only)
            out["review"] = self._review(out, base, job, criteria, deny)
        return out

    def _review(self, out: Dict[str, Any], base: Dict[str, Any], job: Dict[str, Any], criteria: Sequence[str],
                deny: List[str]) -> Dict[str, Any]:
        """쓴 사람과 다른 컨텍스트에서 읽힌다. 검토가 실패하거나 고쳐 쓴 글이 말투 점검에서 더 나쁘면 원래 글을 둔다."""
        reviewed = out["text"]
        try:
            res = self.ask("review", dict(base, brief=job["brief"], text=reviewed, criteria=[str(c) for c in criteria],
                                          used=out["sources"]),
                           skill="kang-twin-review", deny=deny, timeout=REVIEW_TIMEOUT)
        except llm.LLMError as e:
            return {"error": str(e)}
        found = _findings(res)
        if _needs_fix(found):
            try:
                res2 = self.ask("rewrite", dict(base, text=reviewed, issues=_issue_dicts(out["issues"]), review=found,
                                                **job),
                                skill="kang-twin-write", deny=deny, timeout=TIMEOUT)
                text = _text(res2)
            except llm.LLMError as e:
                found["error"] = "고쳐 쓰기 실패: %s" % e
            else:
                issues = self.check(text, base["register"])
                if len(errors(issues)) > len(errors(out["issues"])):
                    found["error"] = "고쳐 쓴 글이 말투 점검에서 더 나빠서 검토 전 글을 둠"
                else:
                    out.update(text=text, issues=issues, rewrites=out["rewrites"] + 1)
                    out["unknowns"] = out["unknowns"] + [u for u in res2.get("unknowns") or []
                                                         if u not in out["unknowns"]]
                    out["sources"] = out["sources"] + [x for x in res2.get("sources") or []
                                                       if x not in out["sources"]]
                    found["rewritten"] = True
        _mark(found, reviewed, out["text"])
        return found


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(prog="kt write", description="말투 팩으로 글 한 편을 써서 출력한다")
    p.add_argument("--register", required=True, choices=REGISTERS)
    p.add_argument("--brief", required=True, help="무엇을 쓸지. 회사, 칸 이름, 질문, 넣을 사례")
    p.add_argument("--length", type=int)
    p.add_argument("--review", action="store_true", help="쓴 뒤 사실 근거·심사 기준·AI 말투를 검토하고 한 번 고쳐 쓴다")
    p.add_argument("--criteria", action="append", default=[], help="심사 기준 (여러 번 줄 수 있음)")
    args = p.parse_args(argv)
    out = Writer().write(args.register, args.brief, args.length, review=args.review, criteria=args.criteria)
    print(out["text"])
    print("\n--- 글자 %d, 다시 쓰기 %d번" % (len(out["text"]), out["rewrites"]))
    for level, _, code, msg, snippet in out["issues"]:
        print("%s [%s] %s%s" % (level, code, msg, " | " + snippet if snippet else ""))
    for u in out["unknowns"]:
        print("확인 필요: %s" % u)
    if out.get("review"):
        print("\n" + "\n".join([review_counts(out["review"])] + review_lines(out["review"])))


if __name__ == "__main__":
    main()
