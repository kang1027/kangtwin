import io
import json
import unittest
import urllib.error
from unittest import mock

from kangtwin import fundsources as fs

# 2026-10-30에 받은 실제 응답에서 줄인 것.
EGBIZ = {"ipAddr": "x", "paramMap": {}, "result": True, "message": None, "value": [
    {"bizCyclId": "PD000000057494", "bizNm": "(11.6,13,광주하남) 아마존(북미) 시장 진출 및 입점 교육", "aplyBgngDt": "2026-10-20",
     "aplyEndDt": "2026-11-05", "outsdInstNm": "경기FTA센터", "categoryNm": "수출", "sareaSeCd": "권역구분없음",
     "prjStatus": "apply", "cnt": 57},
    {"bizCyclId": "PD000000057468", "bizNm": "2026년 WIXG 경기도 G-펀드 투자상담회", "aplyBgngDt": "2026-10-27",
     "aplyEndDt": "2026-11-09", "outsdInstNm": "경기도경제과학진흥원", "categoryNm": "금융", "sareaSeCd": "권역구분없음",
     "prjStatus": "apply", "cnt": 57}]}

VS_LIST = """
<div style="height:155px;border-top:1px solid rgb(221,221,221)">
    <div style="width:620px;display:flex;flex-direction:column;gap:16px;flex-shrink:0">
    <div style="display:flex;flex-direction:column;gap:8px;align-self:stretch">
      <span style="font-weight:500;font-size:16px;line-height:1.4;color:var(--acc);white-space:nowrap">한국능률협회</span>
      <a href="https://www.venturesquare.net/announcement/1124061" style="font-weight:700;font-size:20px">2026년 충청남도 로컬 창업 특화 교육생 모집</a>
    </div>
    <span style="font-weight:400;font-size:12px;line-height:1.4;color:rgb(118,122,126)">2026.10.29</span>
  </div>
</div>
<div style="height:155px;border-top:1px solid rgb(221,221,221)">
    <div style="width:620px;display:flex;flex-direction:column;gap:16px;flex-shrink:0">
    <div style="display:flex;flex-direction:column;gap:8px;align-self:stretch">
      <span style="font-weight:500;font-size:16px;line-height:1.4;color:var(--acc);white-space:nowrap">해양수산과학기술진흥원</span>
      <a href="https://www.venturesquare.net/announcement/1122843" style="font-weight:700;font-size:20px">제6차 해양수산 투자기관협의회(정기IR) 참여기업 모집공고</a>
    </div>
    <span style="font-weight:400;font-size:12px;line-height:1.4;color:rgb(118,122,126)">2026.10.26</span>
  </div>
</div>
"""

VS_DETAIL = """<html><head><script>var x = "지원분야";</script></head><body>
<div><span style="font-weight:700">마감7일전</span></div><span style="font-weight:400">2026-10-26 ~ 2026-11-06 18:00</span></div>
<div><span style="font-weight:600">지원분야</span><span style="font-weight:400">행사ㆍ네트워크</span></div>
<div><span style="font-weight:600">지역</span><span style="font-weight:400">전국</span></div>
<p>해양수산 분야 투자기관 앞 IR 기회를 드립니다.</p>
<div class="information_list"><p class="title">신청방법 및 대상</p><ul><li><div class="table_inner"><p class="tit">신청대상</p>
<p class="txt">해양수산 분야 창업 7년 이내 기업</p></div></li></ul></div>
<h3>Popular News</h3><p>다른 기사</p></body></html>"""

KSTARTUP = {"currentCount": 1, "matchCount": 1, "page": 1, "perPage": 100, "totalCount": 1, "data": [
    {"pbanc_sn": 175001, "biz_pbanc_nm": "2027년 초기창업패키지 창업기업 모집 공고", "pbanc_ntrp_nm": "창업진흥원",
     "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=175001",
     "pbanc_rcpt_bgng_dt": "20270120", "pbanc_rcpt_end_dt": "20270210", "supt_biz_clsfc": "사업화", "supt_regin": "전국",
     "aply_trgt": "일반인", "aply_trgt_ctnt": "업력 3년 이내 창업기업", "biz_enyy": "2년미만,3년미만", "biz_trgt_age": "",
     "pbanc_ctnt": "사업화 자금 최대 1억 원", "rcrt_prgs_yn": "Y"}]}

BIZINFO = {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"totalCount": 1, "items": {
    "item": {"pblancId": "PBLN_000000000120001", "pblancNm": "2026년 경기 스타트업 IR 데이 참가기업 모집",
             "pblancUrl": "/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120001", "jrsdInsttNm": "경기도",
             "excInsttNm": "경기창조경제혁신센터", "bsnsSumryCn": "<p>투자자 앞 IR 기회</p>",
             "pldirSportRealmLclasCodeNm": "창업", "reqstBeginEndDe": "20261101 ~ 20261120", "trgetNm": "중소기업",
             "hashtags": "창업,경기"}}}}}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=30):
        url = req.full_url
        self.calls.append((url, req.data))
        for prefix, body in self.routes:
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return FakeResponse(body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode())
        raise urllib.error.URLError("no route: %s" % url)


def http(routes):
    opener = FakeOpener(routes)
    return fs.Http(opener=opener, sleep=lambda s: None), opener


class DateTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(fs.parse_date("20261103235900"), "2026-11-03")
        self.assertEqual(fs.parse_date("2026.10.28(수) 10:00"), "2026-10-28")
        self.assertEqual(fs.parse_date("상시"), "")
        self.assertEqual(fs.date_range("20261001 ~ 20261031"), ("2026-10-01", "2026-10-31"))
        self.assertEqual(fs.date_range("2026-11-20"), ("", "2026-11-20"))


class ParseTest(unittest.TestCase):
    def test_egbiz(self):
        items = fs.parse_egbiz(EGBIZ)
        self.assertEqual(items[1]["key"], "egbiz:PD000000057468")
        self.assertEqual((items[1]["end"], items[1]["field"], items[1]["org"]), ("2026-11-09", "금융", "경기도경제과학진흥원"))
        self.assertIn("bizCyclId=PD000000057468", items[1]["url"])

    def test_egbiz_failure_flag(self):
        with self.assertRaises(fs.SourceError):
            fs.parse_egbiz({"result": False, "message": "점검 중"})

    def test_kstartup(self):
        n = fs.parse_kstartup(KSTARTUP)[0]
        self.assertEqual((n["key"], n["start"], n["end"], n["years"], n["region"]),
                         ("kstartup:175001", "2027-01-20", "2027-02-10", "2년미만,3년미만", "전국"))

    def test_bizinfo_single_item_and_relative_url(self):
        n = fs.parse_bizinfo(BIZINFO)[0]
        self.assertEqual((n["start"], n["end"], n["summary"]), ("2026-11-01", "2026-11-20", "투자자 앞 IR 기회"))
        self.assertTrue(n["url"].startswith("https://www.bizinfo.go.kr/sii/"))

    def test_bizinfo_error_in_200_body(self):
        with self.assertRaises(fs.SourceError):
            fs.parse_bizinfo({"reqErr": "인증키를 입력해주세요."})
        with self.assertRaises(fs.SourceError):
            fs.parse_bizinfo({"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED"}}})

    def test_venturesquare_list_and_detail(self):
        cards = fs.parse_vs_list(VS_LIST)
        self.assertEqual([c[0] for c in cards], ["1124061", "1122843"])
        self.assertEqual(cards[1][1:], ("해양수산과학기술진흥원", "제6차 해양수산 투자기관협의회(정기IR) 참여기업 모집공고",
                                        "2026-10-26"))
        n = fs.parse_vs_detail("1122843", cards[1][1], cards[1][2], VS_DETAIL)
        self.assertEqual((n["start"], n["end"], n["field"], n["region"], n["target"]),
                         ("2026-10-26", "2026-11-06", "행사ㆍ네트워크", "전국", "해양수산 분야 창업 7년 이내 기업"))
        self.assertIn("IR 기회", n["summary"])
        self.assertNotIn("다른 기사", n["summary"])


class FetchTest(unittest.TestCase):
    def setUp(self):
        # 경기기업비서는 시군 코드를 설정해야 돈다.
        patcher = mock.patch.object(fs, "EGBIZ_AREA", "000")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_venturesquare_opens_only_matching_unseen_details(self):
        h, opener = http([(fs.VS_VIEW % "1122843", VS_DETAIL.encode()), (fs.VS_LIST, VS_LIST.encode())])
        got = fs.venturesquare(h, seen=lambda k: False)
        self.assertEqual([n["source_id"] for n in got], ["1122843"])
        got = fs.venturesquare(h, seen=lambda k: k == "venturesquare:1122843")
        self.assertEqual(got, [])
        self.assertEqual(sum(1 for url, _ in opener.calls if url == fs.VS_VIEW % "1122843"), 1)

    def test_venturesquare_empty_listing_is_an_error(self):
        h, _ = http([(fs.VS_LIST, b"<html>maintenance</html>")])
        with self.assertRaises(fs.SourceError):
            fs.venturesquare(h)

    def test_egbiz_pages_until_short_page(self):
        full = dict(EGBIZ, value=EGBIZ["value"] * 5)
        pages = iter([full, EGBIZ])

        class Opener(FakeOpener):
            def __call__(self, req, timeout=30):
                self.calls.append((req.full_url, req.data))
                return FakeResponse(json.dumps(next(pages), ensure_ascii=False).encode())

        opener = Opener([])
        got = fs.egbiz(fs.Http(opener=opener))
        self.assertEqual(len(got), 12)
        self.assertIn(b"areaCode=000", opener.calls[0][1])
        self.assertIn(b"pageIndex=1", opener.calls[1][1])

    def test_unregistered_key_reason_is_kept(self):
        body = b'{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE_KEY_IS_NOT_REGISTERED_ERROR",' \
               b'"returnAuthMsg":"\xeb\x93\xb1\xeb\xa1\x9d\xeb\x90\x98\xec\xa7\x80 \xec\x95\x8a\xec\x9d\x80 \xec\x84\x9c\xeb\xb9\x84\xec\x8a\xa4\xed\x82\xa4"}}}'
        err = urllib.error.HTTPError(fs.KSTARTUP_URL, 403, "Forbidden", {}, io.BytesIO(body))
        h, _ = http([(fs.KSTARTUP_URL, err)])
        with self.assertRaises(fs.SourceError) as cm:
            fs.kstartup(h, "k")
        self.assertIn("HTTP 403 등록되지 않은 서비스키", str(cm.exception))

    def test_collect_keeps_going_and_skips_keyed_sources_without_key(self):
        h, _ = http([(fs.EGBIZ_URL, EGBIZ), (fs.VS_LIST, urllib.error.URLError("timeout"))])
        notices, counts, errors = fs.collect(h, "", seen=lambda k: False)
        self.assertEqual(counts, {"egbiz": 2})
        self.assertEqual(set(errors), {"kstartup", "bizinfo", "venturesquare"})
        self.assertIn("인증키 없음", errors["kstartup"])
        self.assertEqual(len(notices), 2)


if __name__ == "__main__":
    unittest.main()
