"""후기 본문에서 주수별 심박수·아기집 크기·'주수보다 작다' 언급을 숫자로만 뽑아 data/scan_measures.csv에 남긴다.

종합 보고서(summary_report.py)의 '초음파 결과를 후기와 비교'가 이 파일을 쓴다. 본문 캐시(.cache/posts)는 커밋하지 않아
새 컨테이너에서는 사라지므로, 숫자만 남겨 두면 캐시 없이도 보고서를 만들 수 있다. 원문은 저장하지 않는다.

data/scan_measures.csv : blog(블로그 아이디의 해시, 원래 아이디는 남기지 않음), kind(bpm / sac / small), ga(임신 일수, small은 빈칸), value

사용: python scan_measures.py fetch   # 케이스 블로그의 첫 글과 이후 글 본문을 다시 캐시(milestones.py와 같은 글 선택)
      python scan_measures.py build   # 캐시 본문 → data/scan_measures.csv
"""
import glob
import hashlib
import json
import os
import re
import sys

from common import CACHE, DATA, read_csv, write_csv

OUT = os.path.join(DATA, "scan_measures.csv")
FIELDS = ["blog", "kind", "ga", "value"]
GA = re.compile(r"([4-9])\s*주\s*차?\s*([0-6])\s*일")
BPM = re.compile(r"(\d{2,3})\s*(?:bpm|BPM|회|비피엠)")
SAC = re.compile(r"아기집\s*(?:크기)?\s*(?:는|은|가|이|:)?\s*(?:약\s*)?(\d(?:\.\d{1,2})?)\s*(cm|mm|센치|미리)")
SMALL = re.compile(r"주수보다\s*(?:조금|약간|좀|살짝|며칠|하루|이틀|\d\s*일)?\s*(?:작|느리|늦|어리)|"
                   r"(?:하루|이틀|사흘|[1-6]\s*일|며칠)\s*(?:정도\s*)?(?:작|느리|늦|어리)(?:다|게|아|어|고|네|대|더)")


def key(blog):
    """블로그 아이디 → 짧은 해시. 파일에는 이것만 남기고, 보고서는 케이스 아이디를 같은 방식으로 바꿔 맞춘다."""
    return hashlib.sha1(blog.encode()).hexdigest()[:12]


def extract():
    """캐시 본문 → {(blog, ga): bpm}, {(blog, ga): 아기집 cm}, {작다 언급 blog}. 같은 블로그·주수는 먼저 나온 값."""
    bpms, sacs, small = {}, {}, set()
    for f in sorted(glob.glob(os.path.join(CACHE, "posts", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        b = d.get("blog_id")
        t = re.sub(r"\s+", " ", " ".join(x for k, x in d.get("blocks", []) if k == "text"))
        for m in BPM.finditer(t):
            v = int(m.group(1))
            if 70 <= v <= 200 and re.search(r"심박|심장|bpm", t[max(0, m.start() - 40):m.end() + 5]):
                g = list(GA.finditer(t[max(0, m.start() - 80):m.start()]))
                if g:
                    bpms.setdefault((b, int(g[-1][1]) * 7 + int(g[-1][2])), v)
        for m in SAC.finditer(t):
            v = float(m.group(1)) / (10 if m.group(2) in ("mm", "미리") else 1)
            g = list(GA.finditer(t[max(0, m.start() - 80):m.start()]))
            if g and 0.2 <= v <= 4:
                sacs.setdefault((b, int(g[-1][1]) * 7 + int(g[-1][2])), v)
        for m in SMALL.finditer(t):
            if not re.search(r"^.{0,8}않", t[m.end():m.end() + 10]) and re.search(r"아기|태아|크기|CRL|crl|cm|주수", t[max(0, m.start() - 60):m.end() + 20]):
                small.add(b)
    return bpms, sacs, small


def build():
    bpms, sacs, small = extract()
    rows = ([{"blog": key(b), "kind": "bpm", "ga": g, "value": v} for (b, g), v in sorted(bpms.items())]
            + [{"blog": key(b), "kind": "sac", "ga": g, "value": v} for (b, g), v in sorted(sacs.items())]
            + [{"blog": key(b), "kind": "small", "ga": "", "value": 1} for b in sorted(small)])
    write_csv(OUT, rows, FIELDS)
    print(f"심박수 {len(bpms)} · 아기집 {len(sacs)} · 작다 언급 {len(small)} → {OUT}")


def load():
    """data/scan_measures.csv → extract()와 같은 모양(블로그는 key() 해시). 파일이 없고 캐시가 있으면 캐시에서 뽑는다."""
    rows = read_csv(OUT)
    if not rows:
        if not glob.glob(os.path.join(CACHE, "posts", "*.json")):
            return None
        bpms, sacs, small = extract()
        return ({(key(b), g): v for (b, g), v in bpms.items()}, {(key(b), g): v for (b, g), v in sacs.items()}, {key(b) for b in small})
    bpms = {(r["blog"], int(r["ga"])): int(r["value"]) for r in rows if r["kind"] == "bpm"}
    sacs = {(r["blog"], int(r["ga"])): float(r["value"]) for r in rows if r["kind"] == "sac"}
    small = {r["blog"] for r in rows if r["kind"] == "small"}
    return bpms, sacs, small


def fetch_all():
    """케이스마다 milestones.py와 같은 글(첫 글 + 70일 안의 이후 글 최대 6개 + 후속 글)을 받아 캐시한다."""
    from birth import log_dates, titles_after
    from cases import PATH as CASES
    from common import parse_post_url
    from fetch_posts import fetch
    from milestones import QUEUE, posts_for
    pts = log_dates()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    queue = {}
    for q in read_csv(QUEUE):
        queue.setdefault(q["case_id"], []).append(q)
    cases = read_csv(CASES)

    def one(c):
        try:
            blog, log_no = parse_post_url(c["url"])
            titles_after(blog, log_no)  # .cache/birth/<blog>.json (이후 글 목록)
            blog, nums = posts_for(c, pts, queue, cands)
            for n in nums:
                fetch(blog, str(n))
        except Exception as e:  # noqa: BLE001
            print("실패", c.get("case_id"), type(e).__name__, flush=True)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:  # 블로그마다 글 목록·본문을 받느라 오래 걸려 나눠 받는다
        for i, _ in enumerate(ex.map(one, cases), 1):
            if i % 50 == 0:
                print(f"{i}/{len(cases)}", flush=True)


if __name__ == "__main__":
    {"fetch": fetch_all, "build": build}[sys.argv[1]]()
