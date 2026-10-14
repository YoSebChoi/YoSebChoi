"""1단계: 키워드 검색 → 중복 URL 제거 → data/candidates.csv

블로거 개인정보는 URL 외 저장하지 않으므로 blogger 컬럼에는 URL에 이미 포함된 blogId만 기록한다.
사용: python collect.py [--limit 300]
"""
import argparse
import os

from common import DATA, blog_search, canonical_url, parse_post_url, read_csv, strip_tags, write_csv

KEYWORDS = [
    "5일배아 14일차 임테기 역전", "5일배 15일차 임테기",
    "5일배 이식 14일차", "5일배 이식 15일차",
    "동결 5일배 임테기 역전", "신선 5일배 임테기 역전",
    "5일배 임테기 진하기", "5일배 피검 전 임테기",
]
FIELDS = ["url", "title", "blogger", "postdate", "keyword"]
OUT = os.path.join(DATA, "candidates.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="총 후보 수 상한(0=제한 없음)")
    ap.add_argument("--per-keyword", type=int, default=1000)
    args = ap.parse_args()

    rows = read_csv(OUT)  # 이어하기
    seen = {r["url"] for r in rows}
    # 라운드로빈: --limit이 작을 때도 키워드가 고르게 섞이도록 페이지 단위로 번갈아 수집
    # 이전 실행에서 --limit에 걸려 중간에 끊긴 키워드도 있으므로 모든 키워드를 처음부터 다시 검색한다.
    # 이미 받은 URL은 seen으로 걸러지므로 중복 없이 빠진 결과만 추가된다.
    starts = {kw: 1 for kw in KEYWORDS}
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
