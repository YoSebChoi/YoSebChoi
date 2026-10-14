"""캐시된 글을 사람이 읽기 좋은 형태로 출력 (판정용). 날짜·일차 표기는 앞에 ▶ 표시만 붙이고 판정은 하지 않는다.
사용: python read_post.py <url> [...]
"""
import json
import os
import re
import sys

from common import parse_post_url
from fetch_posts import POSTS

MARK = re.compile(r"(\d{1,2}\s*[./월]\s*\d{1,2}\s*일?|\d+\s*일\s*차|D\s*\+\s*\d+|\d+\s*dp\s*\d*|피검|hcg|HCG|이식)")


def show(url):
    ids = parse_post_url(url)
    path = os.path.join(POSTS, f"{ids[0]}_{ids[1]}.json")
    if not os.path.exists(path):
        print(f"[캐시 없음] {url}")
        return
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    print(f"=== {url}\n제목: {p['title']}\n발행: {p['published']}\n")
    for kind, text in p["blocks"]:
        prefix = {"text": "", "caption": "[사진설명] ", "img": "[사진alt] "}[kind]
        for line in text.splitlines():
            print(("▶ " if MARK.search(line) else "  ") + prefix + line)
    print()


if __name__ == "__main__":
    for u in sys.argv[1:]:
        show(u)
