#!/usr/bin/env python3
"""내 글 문체 점검. 블로그(기본)와 지원서·메시지·메일 레지스터.

사용: python3 check_voice.py [--register blog|apply|message|mail] [--section 제목] <글.md> [<글.md> ...]
ERROR는 고치고, WARN은 읽고 판단한다. ERROR가 하나라도 있으면 종료 코드 1.
기준은 옵시디언 `Me/blog/_문체 가이드.md`(blog)와 `Me/voice/registers/<레지스터>.md`.
`--section`을 주면 그 제목 아래만 본다(예: 외주 초안의 '제안서').
"""
import json
import os
import re
import sys
from pathlib import Path

ERROR, WARN = "ERROR", "WARN"

FORMAL_END = re.compile(r"([가-힣])(니다|니까)$")
POLITE_END = re.compile(r"(?<![필중개수주소긴])(요|죠)$")
NOUN_END = re.compile(r"(함|임|됨)$")
EM_DASH = re.compile(r"[—–]")
BOLD_LABEL = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\*\*[^*]+?[:：]\s*\*\*|^\s*(?:[-*+]|\d+\.)\s+\*\*[^*]+?\*\*\s*[:：]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF]")
HANJA = re.compile(r"[一-鿿]+")
HEDGE = re.compile(r"(지 않을까|지 않았나|않나 싶|까 싶다|것 같다|것 같았다|것 같네)")

BANNED = {
    "셈이다": "'~인 셈이다' 대신 '즉, ~인 것이다'",
    "셈이었다": "'~인 셈이었다' 대신 '즉, ~였던 것이다'",
    "결론부터 말하면": "동기부터 쓰고 결론은 마무리에서",
    "결론부터 말하자면": "동기부터 쓰고 결론은 마무리에서",
    "흥미롭게도": "'사실'이나 그냥 빼기",
    "TL;DR": "맨 위 요약 대신 동기로 시작",
    "필자": "1인칭은 '나'",
    "하하": "웃음 표현은 쓰지 않음",
    "XD": "웃음 표현은 쓰지 않음",
    "ㅎㅎ": "웃음 표현은 쓰지 않음",
    "ㅋㅋ": "웃음 표현은 쓰지 않음",
}
SOFT = {
    "중요한 역할": "번역투. '~에 쓰인다' 등으로",
    "할 수 있게 해 준다": "번역투. '~할 수 있다'로",
    "할 수 있게 해준다": "번역투. '~할 수 있다'로",
    "를 가져온다": "번역투. '~이 생긴다/~로 이어진다'로",
    "을 가져온다": "번역투. '~이 생긴다/~로 이어진다'로",
}
OPENER_SUMMARY = re.compile(r"^(정리하면|요약하면|핵심은)")
PRODUCTS = {
    "claude": "Claude", "codex": "Codex", "nextjs": "Next.js", "next.js": "Next.js",
    "slack": "Slack", "github": "GitHub", "notion": "Notion", "obsidian": "Obsidian",
    "typescript": "TypeScript", "javascript": "JavaScript", "python": "Python",
    "docker": "Docker", "chatgpt": "ChatGPT", "playwright": "Playwright",
    "selenium": "Selenium", "rust": "Rust", "neovim": "Neovim",
}
PRODUCT_RE = re.compile(r"(?<![A-Za-z0-9_./@-])(" + "|".join(re.escape(k) for k in PRODUCTS) + r")(?![A-Za-z0-9_/-])")
CONNECTORS = ["사실", "이에", "즉,", "이렇듯", "그렇다면"]
# Notion 원문(2023~2025)에서 1,000자당 1.9~5.6번 나온 말버릇. AI 초안은 0.0~0.8번이었다.
SIGNATURE = re.compile(
    r"((?<![가-힣])사실(?!상)|(?:^|\s)이에 |즉,|이렇듯|그렇다면|지 않을까|않았나|하고자"
    r"|자연스레|자연스럽게|개인적으로|\([^()]{2,60}[.?!]\))"
)


def clean(line):
    """인용·코드·링크 주소처럼 내 문장이 아닌 부분을 지운다."""
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"!\[\[[^\]]*\]\]", " ", line)
    line = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", line)
    line = re.sub(r"\]\([^)]*\)", "]", line)
    line = re.sub(r"https?://\S+", " ", line)
    line = re.sub(r"<[^>]+>", " ", line)
    line = re.sub(r"%%.*?%%", " ", line)
    return line


def unquote(text):
    return re.sub(r"\"[^\"]*\"|“[^”]*”|'[^']*'|‘[^’]*’", " ", text)


def sentences(text):
    for s in re.split(r"(?<=[.!?])\s+", text):
        s = s.strip()
        if s:
            yield s


def tail(s):
    return re.sub(r"[\s.!?…)\]\"'”’~*_" + "\U0001F300-\U0001FAFF☀-➿" + r"]+$", "", s)


def body_rows(text, section=None):
    """(줄 번호, 원문, 정리된 문장) 중 본문 줄만 돌려준다. section이 있으면 그 제목 아래만."""
    lines = text.splitlines()
    i, out, fence = 0, [], False
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1
    for n in range(i, len(lines)):
        raw = lines[n]
        if raw.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        out.append((n + 1, raw, clean(raw)))
    return out if section is None else only_section(out, section)


def only_section(rows, section):
    picked, level = [], None
    for row in rows:
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", row[1])
        if m and level is not None and len(m.group(1)) <= level:
            break
        if level is not None:
            picked.append(row)
        elif m and m.group(2) == section:
            level = len(m.group(1))
    return picked if level is not None else None


def body_lines(path):
    return body_rows(Path(path).read_text(encoding="utf-8"))


def check(path, register="blog", section=None):
    return check_text(Path(path).read_text(encoding="utf-8"), register, section)


def check_text(text, register="blog", section=None):
    rows = body_rows(text, section)
    if rows is None:
        return [(ERROR, 0, "section", f"'{section}' 제목이 없음", "")]
    if register == "blog":
        return check_blog(rows)
    return check_formal(rows, register)


def check_blog(rows):
    issues = []

    def add(level, line_no, code, msg, snippet=""):
        issues.append((level, line_no, code, msg, snippet.strip()[:70]))

    headings, emoji_lines, para, para_start = [], [], [], None
    totals = {"bold": 0, "hanja": 0, "여러분": 0}
    connector_count = {c: 0 for c in CONNECTORS}

    def flush_paragraph():
        if not para:
            return
        text = " ".join(t for _, t in para)
        hedges = HEDGE.findall(unquote(text))
        if len(hedges) > 1:
            add(WARN, para_start, "hedge", f"추측형 끝맺음이 한 문단에 {len(hedges)}번. 한 번까지", text)
        run = 0
        for s in sentences(unquote(text)):
            run = run + 1 if len(tail(s)) <= 20 else 0
            if run == 3:
                add(WARN, para_start, "short-run", "짧은 단문이 3개 이상 연달아 나옴. '~하며', '~인데'로 잇기", text)
        para.clear()

    for line_no, raw, text in rows:
        stripped = raw.strip()
        if not stripped:
            flush_paragraph()
            para_start = None
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            headings.append((line_no, stripped.lstrip("#").strip()))
            continue
        if EM_DASH.search(text):
            add(ERROR, line_no, "em-dash", "긴 줄표(—, –) 대신 쉼표나 두 문장", raw)
        if BOLD_LABEL.search(raw):
            add(ERROR, line_no, "bold-label", "굵은 라벨+콜론 목록. 문단으로 풀기", raw)
        totals["bold"] += len(re.findall(r"\*\*[^*]+\*\*", raw))
        if EMOJI.search(text):
            emoji_lines.append(line_no)
        if stripped.startswith(">") or stripped.startswith("|"):
            continue
        prose = unquote(text)
        totals["hanja"] += len(HANJA.findall(prose))
        totals["여러분"] += prose.count("여러분")
        for c in CONNECTORS:
            connector_count[c] += len(re.findall(r"(?:^|[\s(])" + re.escape(c), prose))
        for word, hint in BANNED.items():
            if word in prose:
                add(ERROR, line_no, "banned", f"'{word}' → {hint}", raw)
        for word, hint in SOFT.items():
            if word in prose:
                add(WARN, line_no, "translationese", f"'{word}' → {hint}", raw)
        for m in PRODUCT_RE.finditer(prose):
            add(WARN, line_no, "product-case", f"'{m.group(1)}' → '{PRODUCTS[m.group(1)]}'", raw)
        is_list = re.match(r"^\s*(?:[-*+]|\d+\.)\s", raw) is not None
        for s in sentences(prose):
            end = tail(s)
            if not re.search(r"[가-힣]$", end):
                continue
            formal = FORMAL_END.search(end)
            # 합니다·습니다·입니까처럼 앞 글자에 ㅂ 받침이 있을 때만. '아니다'는 ~다체다.
            if formal and (ord(formal.group(1)) - 0xAC00) % 28 == 17:
                add(ERROR, line_no, "formal", "습니다체 종결. ~다로", s)
            elif POLITE_END.search(end):
                add(ERROR, line_no, "polite", "해요체 종결. ~다로", s)
            elif NOUN_END.search(end) and not is_list:
                add(WARN, line_no, "noun-end", "본문 문장이 '~함/~임/~됨'으로 끝남. ~다로", s)
            if s.count(",") > 2:
                add(WARN, line_no, "long", f"쉼표 {s.count(',')}개. 두 개 넘으면 끊기", s)
            if OPENER_SUMMARY.match(s):
                add(WARN, line_no, "summary-opener", "'정리하면/요약하면/핵심은'으로 여는 문장", s)
        if para_start is None:
            para_start = line_no
        para.append((line_no, prose))
    flush_paragraph()

    prose_all = " ".join(
        unquote(t) for _, raw, t in rows if raw.strip() and not raw.lstrip().startswith(("#", ">", "|", "!"))
    )
    sent_lens = [len(tail(x)) for x in sentences(prose_all) if re.search(r"[가-힣]", x)]
    if len(prose_all) >= 500:
        density = len(SIGNATURE.findall(prose_all)) / len(prose_all) * 1000
        if density < 1.5:
            add(WARN, 0, "signature",
                f"말버릇(사실·이에·즉·괄호 혼잣말·~지 않을까·~하고자)이 1,000자당 {density:.1f}번. 원문은 2~5번")
        elif density > 6.0 and len(prose_all) >= 1000:
            add(WARN, 0, "signature-high",
                f"말버릇이 1,000자당 {density:.1f}번. 원문은 2~5번. 문단마다 연결어로 시작하지 않기")
    if len(sent_lens) >= 8 and sum(sent_lens) / len(sent_lens) < 38:
        add(WARN, 0, "rhythm", f"문장 평균 {sum(sent_lens) / len(sent_lens):.0f}자. 원문은 40~60자. 짧게 끊어 치는 리듬")
    if headings and headings[-1][1] != "마무리":
        add(WARN, headings[-1][0], "last-heading", f"마지막 소제목이 '{headings[-1][1]}'. '마무리' 권장")
    if len(emoji_lines) > 1:
        add(WARN, emoji_lines[0], "emoji", f"이모지가 {len(emoji_lines)}줄에 있음. 글 끝 하나까지")
    if totals["bold"] > 5:
        add(WARN, 0, "bold", f"굵게가 {totals['bold']}번. 숫자나 핵심어 몇 개만")
    if totals["hanja"] > 2:
        add(WARN, 0, "hanja", f"한자 병기 {totals['hanja']}번. 글당 한두 번")
    if totals["여러분"] > 2:
        add(WARN, 0, "reader", f"'여러분' {totals['여러분']}번. 권할 때만")
    for c, k in connector_count.items():
        if k > 4:
            add(WARN, 0, "connector", f"'{c}'가 {k}번. 한 글에 서너 번까지")
    return issues


# --- 지원서·메시지·메일 (Me/voice/registers) ---

REGISTERS = ("blog", "apply", "message", "mail")
# 사용자가 퇴짜 놓은 표현. 근거는 Me/voice/edits/2026-09.md
PRETEND_HONEST = ["출시 전 검증까지", "그대로 인정", "함께 밝힙니다"]
WEAK_LABEL = ["경력신입", "중고신입", "신입이지만", "비전공자지만", "부족하지만", "부족한 점이 많지만"]
NEGATIVE_END = re.compile(r"접었(습니다|고|지만)")
OBVIOUS_REASON = re.compile(r"[가-힣]+야 하니까요$")
INTENSIFIER = ["최고의", "무제한", "압도적", "획기적"]
COLLOQUIAL = ["쥐고 있", "접을 수 있", "가져다 쓰", "눈치채기 전에"]
META = re.compile(r"(배웠습니다|깨달았습니다|가장 압축된 사례)")
FORMAL_CONNECTORS = ["이 점에서", "이점에서", "다만", "결국", "또한", "특히"]
LABEL_LINE = re.compile(r"^\S[^:：.!?]{0,20}[:：]")
POSTING_SUBJECT = re.compile(r"공고가 (쓰|사용하|원하|요구하|말하|찾)")
# 문장 잇기. 내 글은 문장의 60~75%가 문장 안에서 이어지고, 이어 주는 말 없는 문장이 셋 연달아 붙지 않는다.
LINK_START = re.compile(r"^(그래서|그런데|그래도|그러다|그러나|하지만|다만|결국|이에|즉|사실|또한|특히|반대로|동시에"
                        r"|결과적으로|따라서|오히려|지금은|당시|처음|이후|그|이)")
LINK_INSIDE = re.compile(r"(는데|[었였했았갔왔됐]고|(?<![공최참광])고[ ,]|며[ ,]|면서|지만|해서|[아어]서 |으니|,)")
def _owner_name() -> str:
    """인사말에 쓸 이름. KANGTWIN_NAME, 없으면 설정 파일의 name, 둘 다 없으면 샘플 인물 이름."""
    if os.environ.get("KANGTWIN_NAME"):
        return os.environ["KANGTWIN_NAME"]
    path = Path(os.environ.get("KANGTWIN_CONFIG", str(Path.home() / ".config/kang-twin/config.json")))
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("name") or "한서윤"
    except (OSError, ValueError, AttributeError):
        return "한서윤"


GREETING = "%s입니다" % _owner_name()


def is_formal(end):
    m = FORMAL_END.search(end)
    return bool(m) and (ord(m.group(1)) - 0xAC00) % 28 == 17


def check_formal(rows, register):
    issues = []

    def add(level, line_no, code, msg, snippet=""):
        issues.append((level, line_no, code, msg, snippet.strip()[:70]))

    section_contrast, section_start = 0, 0
    first_prose, prose_parts, sent_lens, linked = None, [], [], 0
    connector_count = {c: 0 for c in FORMAL_CONNECTORS}

    def flush_section():
        if section_contrast > 3:
            add(WARN, section_start, "contrast", f"'~아니라' 대비가 한 섹션에 {section_contrast}번. 한두 번까지")

    for line_no, raw, text in rows:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            flush_section()
            section_contrast, section_start = 0, line_no
            continue
        if stripped.startswith(("|", "!")) or (stripped.startswith("(") and stripped.endswith(")")):
            continue
        prose = unquote(text)
        if first_prose is None:
            first_prose = (line_no, raw)
        prose_parts.append(prose)
        section_contrast += prose.count("아니라")
        if EM_DASH.search(prose):
            add(WARN, line_no, "em-dash", "긴 줄표(—) 대신 쉼표나 두 문장", raw)
        for word in PRETEND_HONEST:
            if word in prose:
                add(ERROR, line_no, "pretend-honest", f"'{word}': 정직함을 내세우는 단서. 지우기", raw)
        for word in WEAK_LABEL:
            if word in prose:
                add(ERROR, line_no, "weak-label", f"'{word}': 약점 라벨. 해결한 문제로 말하기", raw)
        if POSTING_SUBJECT.search(prose):
            add(ERROR, line_no, "posting-subject", "공고를 주어로 씀. '공고에서 말했듯이', '공고에 나온'으로", raw)
        if NEGATIVE_END.search(prose):
            add(ERROR, line_no, "weak-label", "'접었다': 부정 결말. 이유 한 구절로 지나가기", raw)
        for word in INTENSIFIER:
            if word in prose:
                add(ERROR, line_no, "intensifier", f"'{word}': 강조 수식어. 숫자나 장면으로", raw)
        for word in COLLOQUIAL:
            if word in prose:
                add(WARN, line_no, "colloquial", f"'{word}': 비유·구어. 평이한 업무 표현으로", raw)
        if "실제로" in prose:
            add(WARN, line_no, "really", "'실제로'를 강조로 썼으면 빼기", raw)
        for c in FORMAL_CONNECTORS:
            connector_count[c] += prose.count(c)
        is_list = re.match(r"^\s*(?:[-*+]|\d+\.)\s", raw) is not None
        is_label = LABEL_LINE.match(stripped.lstrip("-*+ ")) is not None and not re.search(r"[.!?]$", stripped)
        flat_run = 0
        for k, s in enumerate(sentences(prose)):
            end = tail(s)
            if not re.search(r"[가-힣]", end):
                continue
            if not is_list and not is_label:
                sent_lens.append(len(end))
                inside = LINK_INSIDE.search(end) is not None
                linked += inside
                if k > 0 and not inside and not LINK_START.match(s):
                    flat_run += 1
                    if flat_run == 2:
                        add(ERROR, line_no, "flat", "이어 주는 말 없는 문장이 셋 연달아 붙음. '그래서', '~했는데'로 잇기", s)
                else:
                    flat_run = 0
            if len(end) > 120:
                add(WARN, line_no, "long", f"{len(end)}자 문장. 120자 넘으면 끊기", s)
            if META.search(end):
                add(WARN, line_no, "meta", "자기 사례에 의미를 매기는 문장. 지우고 사례가 말하게", s)
            if OBVIOUS_REASON.search(end):
                add(ERROR, line_no, "obvious-reason", "당연한 이유를 '~니까요'로 붙임. 지우기", s)
            if not re.search(r"[가-힣]$", end) or is_label:
                continue
            if re.search(r"(니까요|걸요|안녕하세요)$", end) or is_formal(end):
                continue
            if POLITE_END.search(end):
                add(ERROR, line_no, "polite", "해요체 종결. 습니다체로", s)
            elif end.endswith("다"):
                add(ERROR, line_no, "plain-end", "~다체 종결. 습니다체로", s)
            elif NOUN_END.search(end):
                # '~임'은 게임·프레임·모임 같은 명사와 구분이 안 되고, '포함'은 명사다. 그런 건 WARN만.
                if is_list or end.endswith(("임", "포함")):
                    add(WARN, line_no, "noun-end", "'~함/~임/~됨'으로 끝남. 명사가 아니면 습니다체로", s)
                else:
                    add(ERROR, line_no, "plain-end", "'~함/~됨' 종결. 습니다체로", s)
    flush_section()

    body = " ".join(prose_parts)
    if len(sent_lens) >= 6:
        avg = sum(sent_lens) / len(sent_lens)
        if avg > 75 or avg < 45:
            add(WARN, 0, "rhythm", f"문장 평균 {avg:.0f}자. 내 글은 55~70자")
    if len(sent_lens) >= 8 and linked / len(sent_lens) < 0.55:
        add(ERROR, 0, "linking", f"문장 안에서 두 생각을 이은 문장이 {linked}/{len(sent_lens)}. 내 글은 60~75%."
                                 " '~했는데', '~했고,', '~지만,'으로 잇기")
    chars = len(re.sub(r"\s", "", body))
    if chars >= 300 and body.count("것") / chars * 1000 > 6:
        add(WARN, 0, "thing", f"'것'이 {body.count('것')}번. 줄이되 범위를 부풀리는 말로 바꾸지 않기")
    for c, k in connector_count.items():
        if k > 2:
            add(WARN, 0, "connector", f"'{c}'가 {k}번. 한 글에 두 번까지")
    if register in ("message", "mail") and (first_prose is None or GREETING not in first_prose[1]):
        add(WARN, first_prose[0] if first_prose else 0, "greeting", "첫 줄은 '안녕하세요, %s.'" % GREETING)
    return issues


def text_chars(text, section=None):
    """입력창에 붙여 넣을 글자 수(공백 포함). 제목과 줄 전체가 괄호인 메모 줄은 뺀다."""
    rows = body_rows(text, section) or []
    keep = [raw for _, raw, _ in rows
            if not raw.strip().startswith("#") and not (raw.strip().startswith("(") and raw.strip().endswith(")"))]
    return len(re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip())


def parse_argv(argv):
    register, section, paths, i = "blog", None, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--register", "--section"):
            if i + 1 >= len(argv):
                return None, None, []
            value, i = argv[i + 1], i + 2
        elif a.startswith(("--register=", "--section=")):
            value, i = a.split("=", 1)[1], i + 1
        else:
            paths.append(a)
            i += 1
            continue
        if a.startswith("--register"):
            register = value
        else:
            section = value
    return register, section, paths


def main(argv):
    register, section, paths = parse_argv(argv)
    if not paths or register not in REGISTERS:
        print(__doc__.strip())
        return 2
    errors = 0
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        issues = check_text(text, register, section)
        n_err = sum(1 for i in issues if i[0] == ERROR)
        errors += n_err
        extra = "" if register == "blog" else f", {register}, 글자 {text_chars(text, section)}"
        print(f"== {path}: ERROR {n_err}, WARN {len(issues) - n_err}{extra}")
        for level, line_no, code, msg, snippet in sorted(issues, key=lambda i: (i[0] != ERROR, i[1])):
            loc = f"{line_no}" if line_no else "-"
            print(f"{level:5} {loc:>4} [{code}] {msg}" + (f" | {snippet}" if snippet else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
