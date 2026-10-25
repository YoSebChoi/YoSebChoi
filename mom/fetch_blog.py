"""네이버 블로그에서 임산부 혜택 후기(2024년~)를 모아 mom/data/blog.json에 저장해요.

apt/fetch_blog.py와 같은 방식이에요:
- 검색: NAVER API HUB(네이버 클라우드) 블로그 검색. NCP_API_KEY_ID / NCP_API_KEY가 있으면 그 키로,
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 있으면 개발자센터로 찾아요.
- 요청 사이 1~2초 쉬고, 실패하면 두 번 더 해 봐요.
- blog.json(저장소에 올라가요)에는 글 주소·제목·날짜·블로그 ID·검색 요약만 남겨요.
- --excerpts: 글 본문에서 임산부 혜택을 말하는 문장만 골라 mom/data/excerpts.json에 써요.
  이 파일은 저장소에 올리지 않고(.gitignore) Actions 실행 결과물로만 남겨서, 혜택 매장 목록을 다듬을 때 읽어요.

python3 mom/fetch_blog.py [--excerpts]
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
EXCERPTS = SRC / "data/excerpts.json"

HUB_URL = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
DEV_URL = "https://openapi.naver.com/v1/search/blog"
SINCE = "20240101"
KEEP = 1500

TOPICS = [
    "임산부 할인", "임산부 혜택 카페", "임산부 혜택 맛집", "임산부 할인 식당", "임산부 할인 빵집", "임산부 할인 베이커리",
    "임산부 프리패스", "임산부 우선입장", "임산부 웨이팅 없이", "임산부 뷔페 할인", "임산부 호텔뷔페 50%", "임산부 할인 호텔",
    "임산부 리조트 할인", "임산부 숙소 혜택", "태교여행 임산부 혜택", "베이비문 패키지", "태교 패키지 호텔", "임산부 무료 음료",
    "임산부 디카페인 무료", "임산부 서비스 카페", "산모수첩 할인", "산모수첩 보여주면", "임산부 배지 할인", "임산부 뱃지 혜택",
    "임신부 할인", "임신부 혜택 매장", "예비맘 할인", "예비맘 혜택 카페", "임산부 배려 할인업소", "임신부 배려 할인업소",
    "임산부 무료 입장", "임산부 할인 스파", "임산부 할인 브런치", "임신확인서 할인", "임산부 할인 이벤트 매장",
]
REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "수원", "성남 판교", "용인", "고양 일산",
           "화성 동탄", "강원", "강릉", "속초", "청주", "천안", "전주", "여수", "경주", "포항", "창원", "김해", "제주", "서귀포"]
QUERIES = TOPICS + [f"{r} 임산부 할인" for r in REGIONS] + [f"{r} 임산부 혜택" for r in REGIONS]

WHO = re.compile(r"임산부|임신부|예비맘|산모|임밍아웃|태교|만삭|임신\s*\d+\s*주")
PERK = re.compile(r"할인|혜택|무료|프리패스|서비스|우대|우선\s*입장|증정|이벤트|패키지|배려|%|반값|웨이팅")
_POST = re.compile(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)")

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


def blog_search(query, sort="sim", start=1, retries=2):
    url, headers = search_endpoint()
    qs = urllib.parse.urlencode({"query": query, "display": 100, "start": start, "sort": sort})
    last = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}?{qs}", headers=headers), timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                raise NoAccess(f"블로그 검색 API에 들어가지 못했어요 (HTTP {e.code}): NCP_API_KEY_ID / NCP_API_KEY를 확인하세요")
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"블로그 검색 실패: {query}: {last}")


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def post_text(url):
    """The post's text, read from the mobile page (the 스마트에디터 body), or "" when it cannot be read."""
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception:
        return ""
    body = page
    m = re.search(r'<div class="se-main-container">(.*?)<div class="(?:post_footer|wrap_postdata|comment_area)', page, re.S)
    if m:
        body = m.group(1)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>|</p>|</div>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"[ \t​\xa0]+", " ", text)


def perk_lines(text):
    """Lines that talk about a pregnancy benefit, with the line before and after for context (at most 1,200 characters)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    keep = set()
    for i, ln in enumerate(lines):
        if WHO.search(ln) and PERK.search(ln) or re.search(r"산모수첩|임신확인서|임신\s*확인증|임산부\s*(배지|뱃지)", ln):
            keep.update({i - 1, i, i + 1})
    out = " / ".join(lines[i] for i in sorted(keep) if 0 <= i < len(lines))
    return out[:1200]


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"posts": []}
    posts = {p["url"]: p for p in old.get("posts", [])}
    answered = 0
    for q in QUERIES:
        for sort in ("sim", "date"):
            try:
                items = blog_search(q, sort=sort).get("items", [])
            except NoAccess as e:
                print(e, file=sys.stderr)
                sys.exit(0 if not answered else 1)
            except RuntimeError as e:
                print(e, file=sys.stderr)
                continue
            answered += 1
            for it in items:
                m = _POST.search(it.get("link", ""))
                date = it.get("postdate", "")
                title, desc = clean(it.get("title")), clean(it.get("description"))
                if not m or date < SINCE:
                    continue
                both = title + " " + desc
                if not (WHO.search(both) and PERK.search(both)):
                    continue
                url = f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
                p = posts.setdefault(url, {"url": url, "title": title, "blog": m.group(1), "date": date, "desc": desc[:160], "q": []})
                if q not in p["q"]:
                    p["q"].append(q)
    if not answered:
        print("블로그 검색이 모두 실패해서 이전 기록을 그대로 둬요", file=sys.stderr)
        return
    rows = sorted(posts.values(), key=lambda p: (p["date"], p["url"]), reverse=True)[:KEEP]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": time.strftime("%Y-%m-%d"), "posts": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"블로그 글 {len(rows)}개 → {OUT}")

    if "--excerpts" in sys.argv:
        # the posts most likely to name a shop and its benefit first: the ones many searches found
        ranked = sorted(rows, key=lambda p: (-len(p["q"]), p["date"]), reverse=False)[:600]
        ex = []
        for i, p in enumerate(ranked):
            t = post_text(p["url"])
            lines = perk_lines(t) if t else ""
            if lines:
                ex.append({"url": p["url"], "title": p["title"], "date": p["date"], "text": lines})
            if i % 50 == 0:
                print(f"본문 {i}/{len(ranked)} · 혜택 문장 있는 글 {len(ex)}")
        EXCERPTS.write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"혜택 문장 {len(ex)}개 글 → {EXCERPTS}")


if __name__ == "__main__":
    main()
