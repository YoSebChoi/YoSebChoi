"""1단계: 키워드 검색 → 중복 URL 제거 → data/candidates.csv

블로거 개인정보는 URL 외 저장하지 않으므로 blogger 컬럼에는 URL에 이미 포함된 blogId만 기록한다.
사용: python collect.py [--limit 300] [--day3]
"""
import argparse
import os
import re

from common import DATA, blog_search, canonical_url, parse_post_url, read_csv, strip_tags, write_csv

KEYWORDS = [
    "5일배아 14일차 임테기 역전", "5일배 15일차 임테기",
    "5일배 이식 14일차", "5일배 이식 15일차",
    "동결 5일배 임테기 역전", "신선 5일배 임테기 역전",
    "5일배 임테기 진하기", "5일배 피검 전 임테기",
]
# 3일배아: 이식 후 경과일이 5일배아보다 2일 길다(3일배 경과 16일 ≈ 5일배 경과 14일)
KEYWORDS_DAY3 = [
    "3일배아 임테기 역전", "3일배 임테기 역전", "3일배양 이식 임테기 역전",
    "3일배 이식 16일차 임테기", "3일배 이식 17일차 임테기", "3일배 이식 15일차 임테기",
    "동결 3일배 임테기", "신선 3일배 임테기", "3일배아 임테기 진하기", "3일배 피검 전 임테기",
]
DAY3_TITLE = re.compile(r"3일\s*(배아|배양|배|짜리|된)|3일배|분할\s*배아|8세포|초기\s*배아|3일\s*동결")
FIELDS = ["url", "title", "blogger", "postdate", "keyword"]
OUT = os.path.join(DATA, "candidates.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="총 후보 수 상한(0=제한 없음)")
    ap.add_argument("--per-keyword", type=int, default=1000)
    ap.add_argument("--day3", action="store_true", help="3일배아 키워드로 수집")
    args = ap.parse_args()

    rows = read_csv(OUT)  # 이어하기
    seen = {r["url"] for r in rows}
    # 라운드로빈: --limit이 작을 때도 키워드가 고르게 섞이도록 페이지 단위로 번갈아 수집
    # 이전 실행에서 --limit에 걸려 중간에 끊긴 키워드도 있으므로 모든 키워드를 처음부터 다시 검색한다.
    # 이미 받은 URL은 seen으로 걸러지므로 중복 없이 빠진 결과만 추가된다.
    starts = {kw: 1 for kw in (KEYWORDS_DAY3 if args.day3 else KEYWORDS)}
    while starts:
        for kw in list(starts):
            start = starts[kw]
            if start > min(args.per_keyword, 1000) or (args.limit and len(rows) >= args.limit):
                starts.pop(kw)
                continue
            items = blog_search(kw, start=start).get("items", [])
            for it in items:
                ids = parse_post_url(it.get("link", ""))
                if not ids:
                    continue  # 네이버 블로그 외(티스토리 등) 제외
                url = canonical_url(*ids)
                if url in seen:
                    continue
                if args.day3 and not DAY3_TITLE.search(strip_tags(it.get("title"))):
                    continue  # 3일배 검색은 잡음이 많아 제목에 3일배아 표현이 있는 글만
                seen.add(url)
                rows.append({"url": url, "title": strip_tags(it.get("title")), "blogger": ids[0],
                             "postdate": it.get("postdate", ""), "keyword": kw})
                if args.limit and len(rows) >= args.limit:
                    break
            starts[kw] = start + 100
            if len(items) < 100:
                starts.pop(kw)
            write_csv(OUT, rows, FIELDS)
        if args.limit and len(rows) >= args.limit:
            break
    write_csv(OUT, rows, FIELDS)
    print(f"후보 {len(rows)}건 → {OUT}")


if __name__ == "__main__":
    main()
