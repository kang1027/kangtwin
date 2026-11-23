import json
import unittest
import urllib.error

from kangtwin import gonghunt


class FakeResponse:
    def __init__(self, data):
        self.body = json.dumps(data).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(pages, detail=None):
    calls = []

    def opener(req, timeout):
        url = req.full_url
        calls.append(url)
        if "/contests?" in url:
            page = int(url.split("page=")[1].split("&")[0])
            return FakeResponse(pages[page - 1])
        if detail is not None:
            return FakeResponse(detail)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return opener, calls


def item(cid, status="open"):
    return {"id": cid, "title": "t" + cid, "status": status}


class ClientTest(unittest.TestCase):
    def test_open_contests_follows_pages_and_keeps_open_only(self):
        pages = [{"items": [item("a"), item("b", "closed")], "total": 3, "page": 1, "pageSize": 2},
                 {"items": [item("c")], "total": 3, "page": 2, "pageSize": 2}]
        opener, calls = opener_for(pages)
        got = gonghunt.Client(opener=opener).open_contests()
        self.assertEqual([c["id"] for c in got], ["a", "c"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("https://app.gonghunt.com/api/v1/contests?page=1"))

    def test_empty_page_stops(self):
        pages = [{"items": [item("a")], "total": 9, "page": 1}, {"items": [], "total": 9, "page": 2}]
        opener, calls = opener_for(pages)
        self.assertEqual(len(gonghunt.Client(opener=opener).open_contests()), 1)
        self.assertEqual(len(calls), 2)

    def test_detail(self):
        opener, calls = opener_for([], detail={"id": "a", "description": "설명"})
        self.assertEqual(gonghunt.Client(opener=opener).detail("a")["description"], "설명")
        self.assertTrue(calls[0].endswith("/api/v1/contests/a"))

    def test_errors_become_api_error(self):
        opener, _ = opener_for([])
        with self.assertRaises(gonghunt.ApiError):
            gonghunt.Client(opener=opener).detail("x")

        def broken(req, timeout):
            raise urllib.error.URLError("dns")
        with self.assertRaises(gonghunt.ApiError):
            gonghunt.Client(opener=broken).open_contests()

    def test_view_url(self):
        self.assertEqual(gonghunt.view_url("a1"), "https://app.gonghunt.com/contests/a1")


if __name__ == "__main__":
    unittest.main()
