"""공모전헌터 공개 API. 로그인 없이 열린 공모전 목록과 상세를 읽는다."""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List

BASE = "https://app.gonghunt.com/api/v1"
SITE = "https://app.gonghunt.com"
PAGE_SIZE = 50
MAX_PAGES = 20


class ApiError(Exception):
    pass


def view_url(contest_id: str) -> str:
    return "%s/contests/%s" % (SITE, contest_id)


class Client:
    def __init__(self, opener: Callable[..., Any] = urllib.request.urlopen, base: str = BASE):
        self.opener = opener
        self.base = base

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(self.base + path, headers={"Accept": "application/json",
                                                                "User-Agent": "kang-twin/1.0"})
        try:
            with self.opener(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ApiError("공모전헌터 %s: HTTP %d" % (path.split("?")[0], e.code)) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError("공모전헌터 %s: %s" % (path.split("?")[0], e)) from None

    def open_contests(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._get("/contests?" + urllib.parse.urlencode({"page": page, "limit": PAGE_SIZE}))
            batch = data.get("items") or []
            items += batch
            if not batch or len(items) >= int(data.get("total") or 0):
                break
        return [c for c in items if c.get("status") == "open"]

    def detail(self, contest_id: str) -> Dict[str, Any]:
        return self._get("/contests/%s" % urllib.parse.quote(contest_id))
