"""자연임신 후기에서 '우리와 비슷한 초음파 소견(측정 기준 주수 6주 1일~5일, 심박수 100~125)' 케이스를 찾아 경과를 추적한다.

시험관과 달리 자연임신 주수는 마지막 생리일 기준이라 배란이 늦으면 실제보다 크게 나온다. 그래서 날짜 주수 대신
아기 크기(CRL)로 정한 측정 기준 주수와 심박수를 비교한다. CRL → 주수는 Robinson 공식(일 = 8.052·√CRL(mm) + 23.73).

data/natural_candidates.csv : url, blog, postdate, title   (검색 결과, 시험관·이식 글 제외)
data/natural_cases.csv      : 한 줄 = 한 측정(크기·심박수가 같은 진료에 함께 적힌 것). 원문은 저장하지 않는다.
data/natural_track.csv      : 블로그별 경과 판정(출산 / 유산 / 진행중 / 추적불가) + 마지막으로 본 주수·글 번호

사용: python natural.py collect     # 검색 → 후보
      python natural.py extract     # 본문에서 크기·심박수 측정 추출 → 비슷한 케이스 선별
      python natural.py track       # 비슷한 케이스 블로그의 새 글을 보고 경과 갱신(주 1회 돌리는 용도)
      python natural.py show        # 현재 비슷한 케이스와 경과를 한눈에
"""
import datetime as dt
import math
import os
import re
import sys

from birth import BIRTH, LOSS, PLAN
from common import DATA, blog_search, canonical_url, parse_post_url, read_csv, strip_tags, write_csv
from fetch_posts import fetch
from followup import post_list

IVFMODE = "--ivf" in sys.argv  # 시험관 후기를 '심박수·크기' 검색어로 따로 모은다(역전 검색에 안 잡힌 케이스 보완)
PFX = "ivfhb" if IVFMODE else "natural"
CAND = os.path.join(DATA, f"{PFX}_candidates.csv")
CASES = os.path.join(DATA, f"{PFX}_cases.csv")
TRACK = os.path.join(DATA, f"{PFX}_track.csv")
CF = ["url", "blog", "postdate", "title"]
SF = ["blog", "url", "lmp_ga", "crl_mm", "crl_ga", "bpm", "sac_small", "similar", "manual"]
TF = ["blog", "start_logno", "similar_url", "status", "last_week", "last_logno", "checked", "note"]

QUERIES = [
    "임신 6주 심박수", "임신 6주 심장소리", "임신 7주 심장소리", "6주 심장박동 느림", "7주 심박수 느림", "6주 아기 크기 작음",
    "주수보다 작다 심장소리", "임신 6주 초음파 아기 크기 심박수", "임신 6주 CRL", "임신 7주 CRL 심박수",
    "자연임신 6주 초음파", "자연임신 7주 심장소리", "6주 심장 반짝임 심박수", "임신 초기 심박수 낮음", "임신 6주 심박수 110",
    "임신 6주 심박수 115", "임신 6주 심박수 120", "6주 3일 심박수", "6주 4일 심박수", "6주 5일 심박수",
]
QUERIES_IVF = [
    "시험관 6주 심박수", "시험관 7주 심박수", "시험관 7주 심박수 느림", "시험관 6주 심장소리", "시험관 7주 심장소리",
    "시험관 심박수 느림", "시험관 심박수 100", "시험관 심박수 110", "시험관 심박수 120", "시험관 6주 아기 크기",
    "시험관 주수보다 작다", "시험관 6주 CRL", "시험관 7주 CRL", "동결이식 6주 심박수", "동결이식 7주 심박수 느림",
    "신선이식 6주 심박수", "5일배아 6주 심박수", "5일배아 7주 심박수", "3일배아 7주 심박수", "시험관 느린 심장소리",
    "시험관 7주 초음파 심박수 정상 진입", "시험관 심박수 따라잡음", "시험관 6주 심장 반짝임 심박수", "시험관 6주 5일 심박수",
]
IVF = re.compile(r"시험관|이식|난임|배아|피검|동결|신선|인공수정|\bIUI\b|\bIVF\b|과배란|채취|착상")
GA = re.compile(r"([4-9])\s*주\s*차?\s*(?:([0-6])\s*일)?")
NUM = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})?)\s*(cm|mm|센치|센티|미리|㎝|㎜)")
WHO = re.compile(r"CRL|crl|Crl|아기(?!\s*집)|태아|아가(?!\s*집)|애기(?!\s*집)|콩|젤리곰|곰돌|키|머리\s*엉덩이|배아")
BAD = re.compile(r"아기\s*집|애기\s*집|아가\s*집|난황|피\s*고임|혈종|자궁|경부|난포|내막|근종|낭종|물혹|GS|gs|MSD|태낭|목투명|NT|nt")
BPM = re.compile(r"(\d{2,3})\s*(?:bpm|BPM|회|비피엠)")
SAC_SMALL = re.compile(r"아기\s*집\s*(?:크기)?\s*(?:이|가|은|는|도)?\s*(?:좀|너무|여전히|많이|조금|약간|계속)?\s*작(?:다|아|고|은|네|대|더)")
SINCE = "20210101"
# 우리: CRL 6.2mm(측정 기준 6주 2~3일), 113bpm → 측정 기준 6주 1일~5일, 심박수 100~125
SIM_GA = (43, 47)
SIM_BPM = (100, 125)


def crl_ga_days(mm):
    return 8.052 * math.sqrt(mm) + 23.73


def collect():
    old = {r["url"]: r for r in read_csv(CAND)}
    for q in (QUERIES_IVF if IVFMODE else QUERIES):
        for start in (1, 101, 201):
            try:
                items = blog_search(q, start=start, display=100).get("items", [])
            except Exception as e:  # noqa: BLE001
                print("검색 실패", q, start, e)
                break
            for it in items:
                m = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)", it.get("link", ""))
                date = it.get("postdate", "")
                title, desc = strip_tags(it.get("title", "")), strip_tags(it.get("description", ""))
                if not m or date < SINCE or bool(IVF.search(title + " " + desc)) != IVFMODE:
                    continue
                if not re.search(r"[5-8]\s*주", title + desc) or not re.search(r"심박|심장|bpm|크기|CRL|초음파", title + desc):
                    continue
                url = canonical_url(m.group(1), m.group(2))
                old.setdefault(url, {"url": url, "blog": m.group(1), "postdate": date, "title": title})
            if len(items) < 100:
                break
    write_csv(CAND, sorted(old.values(), key=lambda r: r["postdate"], reverse=True), CF)
    print(f"후보 {len(old)}건 → {CAND}")


def measurements(text):
    """본문에서 (LMP 주수일, CRL mm, bpm, 아기집작다) — 크기와 심박수가 같은 문단(120자 안)에 함께 있는 것만."""
    t = re.sub(r"\s+", " ", text)
    out = []
    for m in BPM.finditer(t):
        v = int(m.group(1))
        if not 70 <= v <= 200 or not re.search(r"심박|심장|bpm|BPM", t[max(0, m.start() - 40):m.end() + 5]):
            continue
        win = t[max(0, m.start() - 130):m.end() + 130]
        crl = None
        for n in NUM.finditer(win):
            mm = float(n.group(1)) * (1 if n.group(2) in ("mm", "미리", "㎜") else 10)
            pre = win[max(0, n.start() - 25):n.start()]
            w = list(WHO.finditer(pre))
            if 1 <= mm <= 40 and w and not BAD.search(pre[w[-1].start():]) and not BAD.search(win[n.end():n.end() + 6]):
                crl = mm
                break
        if crl is None:
            continue
        g = list(GA.finditer(t[max(0, m.start() - 160):m.start()]))
        lmp = (int(g[-1].group(1)) * 7 + int(g[-1].group(2) or 0)) if g else None
        out.append((lmp, crl, v))
    return out, bool(SAC_SMALL.search(t))


def extract():
    cands = read_csv(CAND)
    old = {(r["url"], r["crl_mm"], r["bpm"]): r for r in read_csv(CASES)}
    n = 0
    for c in cands:
        b, no = parse_post_url(c["url"])
        post = fetch(b, no)
        text = " / ".join(x for k, x in post.get("blocks", []) if k == "text")
        if not text or bool(IVF.search(text[:3000] + post.get("title", ""))) != IVFMODE:
            continue
        ms, small = measurements(text)
        for lmp, crl, bpm in ms:
            cga = crl_ga_days(crl)
            sim = SIM_GA[0] <= cga <= SIM_GA[1] and SIM_BPM[0] <= bpm <= SIM_BPM[1]
            key = (c["url"], f"{crl:g}", str(bpm))
            old.setdefault(key, {"blog": b, "url": c["url"], "lmp_ga": "" if lmp is None else f"{lmp // 7}w{lmp % 7}d",
                                 "crl_mm": f"{crl:g}", "crl_ga": f"{int(cga) // 7}w{int(cga) % 7}d", "bpm": str(bpm),
                                 "sac_small": "Y" if small else "", "similar": "Y" if sim else "", "manual": ""})
        n += 1
    rows = list(old.values())
    write_csv(CASES, rows, SF)
    sims = {r["blog"] for r in rows if r["similar"] == "Y"}
    print(f"글 {n}개 읽음, 측정 {len(rows)}건, 비슷한 케이스 {len(sims)}개 블로그 → {CASES}")


def _pts():
    from birth import log_dates
    pts = log_dates()
    for r in read_csv(CAND):
        d = r["postdate"]
        if len(d) == 8:
            pts.append((int(parse_post_url(r["url"])[1]), dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).toordinal()))
    return sorted(set(pts))


def judge_titles(items):
    """이후 글 제목으로: 출산 / 유산 / 진행중(마지막 주수) / 추적불가. 출산 준비·계획 글은 출산 근거로 쓰지 않는다."""
    birth = next((it for it in items if any(rx.search(it["title"]) for rx, _ in BIRTH) and not PLAN.search(it["title"])), None)
    if birth:
        return "출산", "", ""
    loss = next((it for it in items if LOSS.search(it["title"])), None)
    if loss:
        return "유산?", "", ""
    wk = [int(m.group(1)) for it in items for m in re.finditer(r"(\d{1,2})\s*주", it["title"]) if 4 <= int(m.group(1)) <= 42]
    if wk:
        return "진행중", str(max(wk)), ""
    return "추적불가", "", ""


def track(today=None):
    today = today or dt.date.today().isoformat()
    sims = {}
    for r in read_csv(CASES):
        if r["similar"] == "Y" and r["blog"] not in sims:
            sims[r["blog"]] = r["url"]
    old = {r["blog"]: r for r in read_csv(TRACK)}
    rows = []
    for blog, url in sims.items():
        prev = old.get(blog)
        start = int(parse_post_url(url)[1])
        items = [it for it in post_list(blog, pages=40, stop_at=start) if it["logNo"] > start]
        items.sort(key=lambda it: it["logNo"])
        status, wk, _ = judge_titles(items)
        last = max([it["logNo"] for it in items], default=start)
        note = prev["note"] if prev else ""
        if prev and prev["status"] != status:
            note = (note + "; " if note else "") + f"{today} {prev['status']}→{status}"
        rows.append({"blog": blog, "start_logno": start, "similar_url": url, "status": status, "last_week": wk,
                     "last_logno": last, "checked": today, "note": note})
    write_csv(TRACK, rows, TF)
    print(f"{len(rows)}개 블로그 경과 갱신 → {TRACK}")


def show():
    cases = [r for r in read_csv(CASES) if r["similar"] == "Y"]
    tr = {r["blog"]: r for r in read_csv(TRACK)}
    for r in cases:
        t = tr.get(r["blog"], {})
        print(f"{r['blog']} | 측정 {r['crl_mm']}mm({r['crl_ga']}) {r['bpm']}bpm | 날짜주수 {r['lmp_ga']} | "
              f"{'아기집작음 ' if r['sac_small'] else ''}| {t.get('status', '미추적')} {t.get('last_week', '')} {t.get('note', '')} | {r['url']}")


if __name__ == "__main__":
    {"collect": collect, "extract": extract, "track": track, "show": show}[sys.argv[1]]()
