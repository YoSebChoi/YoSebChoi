"""네이버 블로그에서 우리 단지 이야기를 찾아 apt/data/blog.json에 모아요 (제목·링크·날짜·블로그 ID만).

ivf-blog(claude/ivf-blog-stage-1-u6xa4r)의 수집 방식을 그대로 따라요:
- 검색: NAVER API HUB(네이버 클라우드) 블로그 검색. NCP_API_KEY_ID / NCP_API_KEY가 있으면 그 키로,
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 있으면 개발자센터로, 둘 다 없으면 네트워크 프록시가 키를 붙인다고 봐요.
- 요청 사이 1~2초 쉬고, 실패하면 두 번 더 해 봐요.
- 개인정보: 블로그 URL(blogId 포함), 제목, 날짜 말고는 저장하지 않아요. 본문은 받지 않아요.

python3 apt/fetch_blog.py
"""
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC / "data/blog.json"
COMPLEXES = SRC / "data/complexes.json"

HUB_URL = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
DEV_URL = "https://openapi.naver.com/v1/search/blog"
KEEP = 300

_last = 0.0


def _throttle():
    global _last
    wait = random.uniform(1.0, 2.0) - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()


def search_endpoint():
    env = os.environ.get
    if env("NCP_API_KEY_ID") and env("NCP_API_KEY"):
        return HUB_URL, {"X-NCP-APIGW-API-KEY-ID": env("NCP_API_KEY_ID"), "X-NCP-APIGW-API-KEY": env("NCP_API_KEY")}
    if env("NAVER_CLIENT_ID") and env("NAVER_CLIENT_SECRET"):
        return DEV_URL, {"X-Naver-Client-Id": env("NAVER_CLIENT_ID"), "X-Naver-Client-Secret": env("NAVER_CLIENT_SECRET")}
    return env("NAVER_SEARCH_URL", HUB_URL), {}


class NoAccess(RuntimeError):
    pass


def blog_search(query, display=100, sort="date", retries=2):
    url, headers = search_endpoint()
    qs = urllib.parse.urlencode({"query": query, "display": display, "start": 1, "sort": sort})
    last = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            req = urllib.request.Request(f"{url}?{qs}", headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise NoAccess(f"블로그 검색 API에 들어가지 못했어요 (HTTP {e.code}): 키 NCP_API_KEY_ID / NCP_API_KEY를 확인하세요")
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"블로그 검색 실패: {query}: {last}")


# 매매와 관련 있어 보이는 글 (앱의 「매매 이야기만」)
DEAL = re.compile(r"매매|매수|매도|급매|매물|실거래|시세|신고가|호가|폭등|급등|하락|호재|임장|경매|낙찰|입찰|투자|갭|전세|월세|단지\s*정보|vs", re.I)
_POST = re.compile(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)")


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def main():
    complexes = json.loads(COMPLEXES.read_text(encoding="utf-8"))
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"posts": []}
    posts = {p["url"]: p for p in old.get("posts", [])}
    answered = 0
    blocked = False
    for c in complexes["complexes"]:
        if blocked:
            break
        title_re = re.compile(c["blogTitle"], re.I)
        for q, sort in [(q, sort) for q in c["blogQueries"] for sort in ("date", "sim")]:
            try:
                items = blog_search(q, sort=sort).get("items", [])
            except NoAccess as e:
                print(e, file=sys.stderr)
                blocked = True
                break
            except RuntimeError as e:
                print(e, file=sys.stderr)
                continue
            answered += 1
            for it in items:
                m = _POST.search(it.get("link", ""))
                title = clean(it.get("title"))
                if not m or not title_re.search(title):
                    continue
                url = f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
                p = posts.setdefault(url, {"url": url, "title": title, "blog": m.group(1),
                                           "date": it.get("postdate", ""), "cx": []})
                if c["key"] not in p["cx"]:
                    p["cx"].append(c["key"])
                p["deal"] = bool(DEAL.search(title))
    if not answered:
        print("블로그 검색이 모두 실패해서 이전 기록을 그대로 둬요 (키: NCP_API_KEY_ID / NCP_API_KEY)", file=sys.stderr)
        return
    rows = sorted(posts.values(), key=lambda p: (p["date"], p["url"]), reverse=True)[:KEEP]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": time.strftime("%Y-%m-%d"), "posts": rows}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"블로그 글 {len(rows)}개 → {OUT}")


if __name__ == "__main__":
    main()
