"""2단계 준비: 후보 글 본문을 받아 로컬 캐시(.cache/posts, 커밋 안 함)에 저장.

판정은 사람이(또는 Claude가) read_post.py로 글 전체를 읽고 data/cases.csv에 직접 기록한다.
키워드 매칭으로 자동 판정하지 않는다.
사용: python fetch_posts.py [--csv data/candidates.csv] [--limit N]
"""
import argparse
import json
import os
import re

from bs4 import BeautifulSoup

from common import CACHE, DATA, http_get, parse_post_url, read_csv

POSTS = os.path.join(CACHE, "posts")


def extract(html):
    """m.blog / PostView HTML → {title, published, blocks[]}. blocks: ("text"|"caption"|"img", str)"""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    for sel in [".se-title-text", ".tit_h3", ".pcol1", "h3.se_textarea", "title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(" ", strip=True)
            break
    published = ""
    for sel in [".blog_date", ".se_publishDate", ".date", "p.date"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            published = el.get_text(" ", strip=True)
            break
    if not published:
        m = re.search(r'"(?:addDate|publishDate)"\s*:\s*"?([\d.: -]+)', html)
        published = m.group(1).strip() if m else ""

    body = soup.select_one(".se-main-container") or soup.select_one("#postViewArea") or soup.select_one(".post_ct")
    blocks = []
    if body:
        # SE3는 .se-component 단위, 구 에디터는 .se_component/p 단위. 섞어 고르면 중첩돼 본문이 두 번 나온다.
        parts = body.select(".se-component") or body.select(".se_component") or body.select("p")
        for el in parts or [body]:
            if el.select_one(".se-image, img") is not None:
                for img in el.select("img"):
                    alt = (img.get("alt") or "").strip()
                    if alt:
                        blocks.append(("img", alt))
                cap = el.select_one(".se-caption, .se_caption")
                if cap and cap.get_text(strip=True):
                    blocks.append(("caption", cap.get_text(" ", strip=True)))
                continue
            t = el.get_text("\n", strip=True)
            if t:
                blocks.append(("text", t))
    # 중복 블록(중첩 셀렉터) 제거
    seen, uniq = set(), []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return {"title": title, "published": published, "blocks": uniq}


def fetch(blog_id, log_no):
    path = os.path.join(POSTS, f"{blog_id}_{log_no}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    post = None
    for url in (f"https://m.blog.naver.com/{blog_id}/{log_no}",
                f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"):
        html = http_get(url)
        if html:
            post = extract(html)
            if post["blocks"]:
                break
    if post is None:
        post = {"title": "", "published": "", "blocks": [], "error": "not found"}
    post.update(blog_id=blog_id, log_no=log_no)
    os.makedirs(POSTS, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=1)
    return post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(DATA, "candidates.csv"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rows = read_csv(args.csv)[: args.limit or None]
    empty = 0
    for i, r in enumerate(rows, 1):
        ids = parse_post_url(r["url"])
        if not ids:
            continue
        try:
            p = fetch(*ids)
            empty += not p["blocks"]
        except RuntimeError as e:
            print(e)
        if i % 25 == 0:
            print(f"{i}/{len(rows)}")
    print(f"완료 {len(rows)}건 (본문 비어있음 {empty}건)")


if __name__ == "__main__":
    main()
