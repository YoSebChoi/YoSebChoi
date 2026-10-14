"""공통: HTTP 요청(딜레이·재시도), 경로, CSV 유틸."""
import csv
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RESULTS = os.path.join(ROOT, "results")
# 본문 원문은 저장소에 커밋하지 않는 로컬 캐시(.gitignore)
CACHE = os.path.join(ROOT, ".cache")

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

_last_request = 0.0


def _throttle():
    global _last_request
    wait = random.uniform(1.0, 2.0) - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def http_get(url, headers=None, retries=2):
    """요청 간 1~2초 딜레이, 실패 시 재시도 2회. 404는 재시도 없이 None."""
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    last_err = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET 실패 ({retries + 1}회): {url}: {last_err}")


def naver_headers():
    """키가 환경변수에 있으면 헤더로, 없으면 network secret 프록시가 붙인다고 가정."""
    cid, sec = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    return {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec} if cid and sec else {}


def blog_search(query, start=1, display=100, sort="sim"):
    qs = urllib.parse.urlencode({"query": query, "display": display, "start": start, "sort": sort})
    body = http_get(f"https://openapi.naver.com/v1/search/blog?{qs}", naver_headers())
    return json.loads(body) if body else {"items": []}


_PATH_RE = re.compile(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)")
_QS_RE = re.compile(r"blog\.naver\.com/PostView\.n[a-z]+\?.*?blogId=([A-Za-z0-9_-]+).*?logNo=(\d+)")


def parse_post_url(url):
    """네이버 블로그 URL → (blogId, logNo). 블로그 글이 아니면 None."""
    m = _QS_RE.search(url or "") or _PATH_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else None


def canonical_url(blog_id, log_no):
    return f"https://m.blog.naver.com/{blog_id}/{log_no}"


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
