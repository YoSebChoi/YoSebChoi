"""3단계 준비: 조건 충족 케이스(5일배 + 경과 14일 역전)의 같은 블로그 이후 글 후보를 모은다.
결과는 data/followup_queue.csv (case_id, url, title, date, source). 결과 판정은 글을 읽고 cases.csv에 기록.
사용: python followup.py [--all-groups] [--unknown]
  --all-groups: 비교군 동일진하기/미역전도 추적
  --unknown: 결과가 미확인인 케이스 전부 추적(배아 일수·그룹 무관)
"""
import argparse
import json
import os
import re

from cases import PATH as CASES, dedupe, is_target
from common import DATA, blog_search, canonical_url, http_get, parse_post_url, read_csv, strip_tags, write_csv

OUTCOME_WORDS = re.compile(r"아기집|난황|심장|심박|계류|화유|화학적|자궁외|졸업|주차|\d+주|임신확인|유산|소파|피검|베타")
QUERIES = ["아기집", "심장소리", "계류", "화유"]
OUT = os.path.join(DATA, "followup_queue.csv")


def post_list(blog_id, pages=5):
    """블로그 글 목록(모바일 API). 실패하면 빈 목록."""
    items = []
    for page in range(1, pages + 1):
        try:
            body = http_get(f"https://m.blog.naver.com/api/blogs/{blog_id}/post-list"
                            f"?categoryNo=0&itemCount=30&page={page}",
                            {"Referer": f"https://m.blog.naver.com/{blog_id}"})
            res = json.loads(body or "{}").get("result", {})
        except (RuntimeError, ValueError):
            break
        batch = res.get("items", [])
        for it in batch:
            items.append({"url": canonical_url(blog_id, it.get("logNo")),
                          "title": strip_tags(it.get("titleWithInspectMessage") or it.get("title", "")),
                          "logNo": int(it.get("logNo", 0)), "source": "post-list"})
        if len(batch) < 30:
            break
    return items


def search_same_blog(blog_id):
    items = []
    for q in QUERIES:
        for it in blog_search(f"{blog_id} {q}", display=100).get("items", []):
            ids = parse_post_url(it.get("link", ""))
            if ids and ids[0] == blog_id:
                items.append({"url": canonical_url(*ids), "title": strip_tags(it["title"]),
                              "logNo": int(ids[1]), "date": it.get("postdate", ""), "source": f"search:{q}"})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-groups", action="store_true")
    ap.add_argument("--unknown", action="store_true")
    args = ap.parse_args()
    cases = dedupe(read_csv(CASES))
    if args.unknown:
        targets = [c for c in cases if c.get("outcome") in ("미확인", "")]
    else:
        targets = [c for c in cases if c.get("embryo_day") == "5" and
                   (args.all_groups and c.get("test_d14") in ("역전", "동일진하기", "미역전(연함)") or is_target(c))]
    queue = read_csv(OUT)
    done = {q["case_id"] for q in queue}
    for c in targets:
        if c["case_id"] in done:
            continue
        blog_id, log_no = parse_post_url(c["url"])
        cands = post_list(blog_id) + search_same_blog(blog_id)
        seen = set()
        for it in sorted(cands, key=lambda x: x["logNo"]):
            # logNo는 블로그 내에서 시간순 증가 → 판정 글 이후 글만
            if it["logNo"] <= int(log_no) or it["url"] in seen or not OUTCOME_WORDS.search(it["title"]):
                continue
            seen.add(it["url"])
            queue.append({"case_id": c["case_id"], **it})
        write_csv(OUT, queue, ["case_id", "url", "title", "date", "source"])
        print(f"{c['case_id']}: 후속 후보 {len(seen)}건")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
