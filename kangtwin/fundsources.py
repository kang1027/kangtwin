"""자금 정찰 출처. 출처마다 접수 중인 공고를 받아 공통 형태(Notice)로 바꾼다.

출처는 원본에 가까운 순서(SOURCES)로 둔다. 같은 사업이 여러 곳에 실리면 앞쪽 하나만 알린다.
"""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config

Notice = Dict[str, Any]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) kang-twin/1.0"
KSTARTUP_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
BIZINFO_URL = "https://apis.data.go.kr/1421000/bizinfo/pblancBsnsService"
EGBIZ_URL = "https://www.egbiz.or.kr/sp/selectSupportPrjListAjax.do"
EGBIZ_VIEW = "https://www.egbiz.or.kr/sp/supportPrjDtl.do?listUrl=supportPrjAreaList&bizCyclId=%s"
EGBIZ_AREA = config.SETTINGS.get("egbiz_area", "")  # 경기기업비서 시군 코드. 비우면 이 출처를 건너뛴다
VS_LIST = "https://www.venturesquare.net/announcement/"
VS_PAGE = "https://www.venturesquare.net/announcement/page/%d/"
VS_VIEW = "https://www.venturesquare.net/announcement/%s"

NAMES = {"kstartup": "K-Startup", "bizinfo": "기업마당", "egbiz": "경기기업비서", "venturesquare": "벤처스퀘어"}
SOURCES = list(NAMES)
PAGE_LIMIT = 10
# 기업마당은 올해 공고 전체(1,400건 넘음)를 최신순으로 준다. 하루 새 공고는 수십 건이라 앞쪽 몇 쪽만 본다.
BIZINFO_PAGES = 3
VS_PAGES = 2
VS_DELAY = 1.0
# 벤처스퀘어는 교육·포럼까지 하루 수십 건이 올라온다. 제목이 IR이거나 창업 지원사업일 때만 상세를 연다.
VS_WORDS = re.compile(r"IR|데모데이|피칭|투자유치|투자 ?연계|투자상담|인베스터|액셀러레이팅|배치|사업화|입주기업|"
                      r"창업지원|지원사업|참여기업 모집|참가기업 모집|스타트업 모집|공모전|경진대회", re.I)


class SourceError(Exception):
    pass


def parse_date(text: Any) -> str:
    """여러 출처의 날짜 표기를 YYYY-MM-DD로. 못 읽으면 빈 문자열."""
    m = re.search(r"(20\d\d)[-.]?\s?(\d{1,2})[-.]?\s?(\d{1,2})", str(text or ""))
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return "%04d-%02d-%02d" % (y, mo, d)


def date_range(text: Any) -> Tuple[str, str]:
    """'20261001 ~ 20261031', '2026-10-28 ~ 2026-10-30 23:59' 같은 기간을 (시작, 끝)으로."""
    parts = re.split(r"~|∼|〜", str(text or ""), maxsplit=1)
    if len(parts) == 2:
        return parse_date(parts[0]), parse_date(parts[1])
    one = parse_date(parts[0])
    return "", one


def strip_html(text: Any) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", str(text or ""), flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</tr>", "\n", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in t.splitlines()]
    return "\n".join(l for l in lines if l)


def notice(source: str, source_id: Any, **fields: Any) -> Notice:
    n = {"source": source, "source_id": str(source_id), "key": "%s:%s" % (source, source_id), "title": "",
         "org": "", "url": "", "start": "", "end": "", "field": "", "region": "", "target": "", "years": "",
         "ages": "", "summary": ""}
    n.update({k: (v if v is not None else "") for k, v in fields.items()})
    n["title"] = re.sub(r"\s+", " ", html.unescape(str(n["title"]))).strip()
    n["summary"] = str(n["summary"])[:1500]
    return n


class Http:
    def __init__(self, opener: Callable[..., Any] = urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep):
        self.opener = opener
        self.sleep = sleep

    def _open(self, req: urllib.request.Request, label: str) -> bytes:
        try:
            with self.opener(req, timeout=30) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            reason = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>|\"returnAuthMsg\"\s*:\s*\"(.*?)\"", body)
            raise SourceError("%s: HTTP %d%s" % (label, e.code, " " + next(g for g in reason.groups() if g)
                                                 if reason else "")) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise SourceError("%s: %s" % (label, e)) from None

    def get(self, url: str, params: Optional[Dict[str, Any]] = None, label: str = "") -> bytes:
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="[]:")
        return self._open(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), label or url)

    def post(self, url: str, data: Dict[str, Any], label: str = "") -> bytes:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": UA, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        return self._open(req, label or url)

    def json(self, raw: bytes, label: str) -> Any:
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise SourceError("%s: JSON이 아님 (%s)" % (label, raw[:120].decode("utf-8", "replace"))) from None


# --- K-Startup (data.go.kr 15125364) ---

def parse_kstartup(data: Dict[str, Any]) -> List[Notice]:
    out = []
    for item in data.get("data") or []:
        sn = item.get("pbanc_sn")
        if not sn:
            continue
        out.append(notice("kstartup", sn, title=item.get("biz_pbanc_nm") or item.get("intg_pbanc_biz_nm"),
                          org=item.get("pbanc_ntrp_nm") or item.get("sprv_inst"),
                          url=item.get("detl_pg_url") or item.get("biz_gdnc_url") or item.get("biz_aply_url"),
                          start=parse_date(item.get("pbanc_rcpt_bgng_dt")), end=parse_date(item.get("pbanc_rcpt_end_dt")),
                          field=item.get("supt_biz_clsfc"), region=item.get("supt_regin"),
                          target="%s %s" % (item.get("aply_trgt") or "", item.get("aply_trgt_ctnt") or ""),
                          years=item.get("biz_enyy"), ages=item.get("biz_trgt_age"),
                          summary="\n".join(str(x) for x in (item.get("pbanc_ctnt"), item.get("aply_excl_trgt_ctnt"),
                                                             item.get("prfn_matr")) if x)))
    return out


def kstartup(http: Http, key: str) -> List[Notice]:
    out: List[Notice] = []
    for page in range(1, PAGE_LIMIT + 1):
        data = http.json(http.get(KSTARTUP_URL, {"serviceKey": key, "page": page, "perPage": 100, "returnType": "json",
                                                 "cond[rcrt_prgs_yn::EQ]": "Y"}, "K-Startup"), "K-Startup")
        batch = parse_kstartup(data)
        out += batch
        if not batch or len(out) >= int(data.get("matchCount") or data.get("totalCount") or 0):
            break
    return out


# --- 중기부 지원사업 공고 (기업마당 데이터, data.go.kr 15157820) ---

def _bizinfo_body(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    root = data.get("response") if isinstance(data.get("response"), dict) else data
    header = root.get("header") or {}
    # 키 오류도 HTTP 200으로 온다. 상태 코드가 아니라 본문을 본다.
    if data.get("reqErr") or (header.get("resultCode") not in (None, "", "00", "0", 0)):
        raise SourceError("기업마당: %s" % (data.get("reqErr") or header.get("resultMsg") or header.get("resultCode")))
    body = root.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


def parse_bizinfo(data: Dict[str, Any]) -> List[Notice]:
    items, _ = _bizinfo_body(data)
    out = []
    for item in items:
        pid = item.get("pblancId")
        if not pid:
            continue
        start, end = date_range(item.get("reqstBeginEndDe"))
        url = item.get("pblancUrl") or ""
        if url.startswith("/"):
            url = "https://www.bizinfo.go.kr" + url
        out.append(notice("bizinfo", pid, title=item.get("pblancNm"),
                          org=item.get("excInsttNm") or item.get("jrsdInsttNm"), url=url, start=start, end=end,
                          field=item.get("pldirSportRealmLclasCodeNm"), region=item.get("hashtags"),
                          target=item.get("trgetNm"), summary=strip_html(item.get("bsnsSumryCn"))))
    return out


def bizinfo(http: Http, key: str) -> List[Notice]:
    out: List[Notice] = []
    for page in range(1, BIZINFO_PAGES + 1):
        data = http.json(http.get(BIZINFO_URL, {"serviceKey": key, "pageNo": page, "numOfRows": 100,
                                                "dataType": "json"}, "기업마당"), "기업마당")
        batch = parse_bizinfo(data)
        out += batch
        if not batch or len(out) >= _bizinfo_body(data)[1]:
            break
    return out


# --- 경기기업비서 (설정한 시군의 접수 중 공고) ---

def parse_egbiz(data: Dict[str, Any]) -> List[Notice]:
    if data.get("result") is False:
        raise SourceError("경기기업비서: %s" % (data.get("message") or "result=false"))
    out = []
    for item in data.get("value") or []:
        bid = item.get("bizCyclId")
        if not bid:
            continue
        out.append(notice("egbiz", bid, title=item.get("bizNm"), org=item.get("outsdInstNm"), url=EGBIZ_VIEW % bid,
                          start=parse_date(item.get("aplyBgngDt")), end=parse_date(item.get("aplyEndDt")),
                          field=item.get("categoryNm"), region="경기 %s" % (item.get("sareaSeCd") or "")))
    return out


def egbiz(http: Http, key: str = "") -> List[Notice]:
    out: List[Notice] = []
    if not EGBIZ_AREA:
        return out
    for page in range(PAGE_LIMIT):
        data = http.json(http.post(EGBIZ_URL, {"areaCode": EGBIZ_AREA, "prjStatus": "apply", "pageIndex": page,
                                               "gginsttYn": "Y", "part": "area"}, "경기기업비서"), "경기기업비서")
        batch = parse_egbiz(data)
        out += batch
        if len(batch) < 10:
            break
    return out


# --- 벤처스퀘어 공고 게시판 ---

CARD = re.compile(r'color:var\(--acc\)[^>]*>([^<]*)</span>\s*<a href="https://www\.venturesquare\.net/announcement/(\d+)"'
                  r'[^>]*>(.*?)</a>\s*</div>\s*<span[^>]*>([\d.]+)</span>', re.S)


def parse_vs_list(page: str) -> List[Tuple[str, str, str, str]]:
    """(id, 기관, 제목, 게시일) 목록."""
    return [(i, html.unescape(org).strip(), strip_html(title), parse_date(day)) for org, i, title, day in CARD.findall(page)]


def _after(lines: List[str], label: str) -> str:
    for i, line in enumerate(lines[:-1]):
        if line == label:
            return lines[i + 1]
    return ""


def parse_vs_detail(vid: str, org: str, title: str, page: str) -> Notice:
    # 상세 화면은 '지원분야'와 값이 붙은 span 두 개라, 태그마다 줄을 나눠야 이름과 값이 갈린다.
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    lines = [l for l in (re.sub(r"\s+", " ", html.unescape(x)).strip() for x in re.split(r"<[^>]+>", body)) if l]
    text = "\n".join(lines)
    m = re.search(r"(20\d\d-\d\d-\d\d)\s*~\s*(20\d\d-\d\d-\d\d)", text)
    start, end = (m.group(1), m.group(2)) if m else ("", "")
    first = lines.index("지원분야") if "지원분야" in lines else 0
    summary = "\n".join(lines[first:]).split("Popular News")[0]
    return notice("venturesquare", vid, title=title, org=org, url=VS_VIEW % vid, start=start, end=end,
                  field=_after(lines, "지원분야"), region=_after(lines, "지역"), target=_after(lines, "신청대상"),
                  summary=summary)


def venturesquare(http: Http, key: str = "", seen: Optional[Callable[[str], bool]] = None) -> List[Notice]:
    seen = seen or (lambda k: False)
    cards: List[Tuple[str, str, str, str]] = []
    for page in range(1, VS_PAGES + 1):
        url = VS_LIST if page == 1 else VS_PAGE % page
        cards += parse_vs_list(http.get(url, label="벤처스퀘어").decode("utf-8", "replace"))
    if not cards:
        raise SourceError("벤처스퀘어: 목록에서 공고를 못 찾음 (화면 형식이 바뀐 듯)")
    out = []
    for vid, org, title, _ in dict((c[0], c) for c in cards).values():
        if seen("venturesquare:%s" % vid) or not VS_WORDS.search(title):
            continue
        http.sleep(VS_DELAY)
        try:
            page = http.get(VS_VIEW % vid, label="벤처스퀘어 %s" % vid).decode("utf-8", "replace")
        except SourceError:
            continue
        out.append(parse_vs_detail(vid, org, title, page))
    return out


FETCHERS = {"kstartup": kstartup, "bizinfo": bizinfo, "egbiz": egbiz, "venturesquare": venturesquare}
NEEDS_KEY = {"kstartup", "bizinfo"}


def collect(http: Http, key: str, seen: Callable[[str], bool]) -> Tuple[List[Notice], Dict[str, int], Dict[str, str]]:
    """모든 출처에서 받는다. 한 곳이 실패해도 나머지는 계속한다. (공고, 출처별 건수, 출처별 오류)."""
    notices: List[Notice] = []
    counts: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    for source in SOURCES:
        if source in NEEDS_KEY and not key:
            errors[source] = "data.go.kr 인증키 없음"
            continue
        try:
            fetch = FETCHERS[source]
            got = fetch(http, key, seen) if source == "venturesquare" else fetch(http, key)
        except SourceError as e:
            errors[source] = str(e)
            continue
        counts[source] = len(got)
        notices += got
    return notices, counts, errors
