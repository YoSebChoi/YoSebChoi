"""임신 초기 피비침(갈색혈·선홍혈·하혈)과 피고임 언급을 케이스 글·후속 글에서 찾아 시기별로 data/bleeding_log.csv에 남긴다.
원문은 저장하지 않고 분류 결과와 주수, 글 URL만 남긴다.

시기(임신 주수, 이식일 = 5일배 2주5일 / 4일배 2주4일 / 3일배 2주3일)
  early  이식 ~ 4주 0일 (착상 시기·피검 전)
  pre    4주 1일 ~ 심장 첫 확인 전 (심장 확인 주수를 모르면 7주 6일까지)
  post   심장 확인 ~ 12주 6일
분류: brown(갈색, 양이 적음) / red(선홍·빨간 피·하혈·생리처럼·많은 양) / spot(색 미상 피비침) / 없음
주수는 언급 앞 80자 안의 'N주 M일'(없으면 'N주'), 그것도 없으면 글 작성일(추정)로 정한다.

사용: python bleeding.py collect
      python bleeding.py show CASE_ID ...   # 근거 문장 확인
      python bleeding.py set < 줄           # case_id|pre|post|hematoma|메모   (pre/post: brown·red·spot·없음, 비우면 그대로)
"""
import json
import os
import re
import sys

from birth import CDIR, case_date, est_date, log_dates
from cases import FAILURES, PATH as CASES
from common import DATA, parse_post_url, read_csv, write_csv
from fetch_posts import fetch
from milestones import parse as ga_of

LOG = os.path.join(DATA, "bleeding_log.csv")
FIELDS = ["case_id", "embryo_day", "outcome", "birth", "hb_ga", "early", "pre", "post", "hematoma", "first_ga",
          "posts", "evidence_url", "manual"]
TERM = re.compile(r"피\s*비침|피비춤|갈색\s*(?:혈|피|냉|분비물|출혈|피비침|찌꺼기)|갈색혈|선홍\S*\s*(?:피|혈|출혈)?|빨간\s*피|붉은\s*(?:피|혈)|"
                  r"하혈|출혈|피가\s*(?:묻|비치|나|보)")
BROWN = re.compile(r"갈색|브라운|검붉|흑갈|짙은\s*갈")
RED = re.compile(r"선홍|빨간|빨갛|붉은|붉게|새빨|생리처럼|생리\s*양|하혈|덩어리|콸콸|왈칵|패드|많이\s*(?:나|비|흘)|양이\s*많")
NEG = re.compile(r"^[^./!?]{0,12}(?:없|않|안\s*(?:나|비|보|했)|아니|X\b|x\b|무\b)")
GENERIC = re.compile(r"(?:혹시|만약|보통|대부분|흔히|경우|라면|하면|으면|이면|시에는|주의|증상\s*:|체크)\s*\S{0,8}$")
HEMA = re.compile(r"피\s*고임|융모막\s*하\s*혈종|혈종")
GA = re.compile(r"(?<!\d)([3-9]|1[0-3])\s*(?:주|w|W)\s*(?:차\s*)?(?:([0-6])\s*(?:일|d|D))?(?![0-9개월])")
HINT = re.compile(r"피\s*비침|갈색|출혈|하혈|선홍|피고임|\d\s*주|주차|아기집|난황|심장|초음파|피검|졸업|임신")


def mentions(text, title_ga, post_ga):
    """(주수, 분류) 목록. 부정·일반론·해시태그 문장은 뺀다."""
    t = re.sub(r"\s+", " ", text)
    out = []
    for m in TERM.finditer(t):
        if t[max(0, m.start() - 1):m.start()] == "#" or "#" in t[max(0, m.start() - 2):m.start()]:
            continue
        after = re.split(r"[.!?\n]", t[m.end():m.end() + 30])[0]
        before = t[max(0, m.start() - 25):m.start()]
        if NEG.search(after) or GENERIC.search(before) or re.search(r"(?:없이|없었|없는|안\s*비친)\s*$", before):
            continue
        ctx = t[max(0, m.start() - 20):m.end() + 25]
        kind = "red" if RED.search(ctx) else "brown" if BROWN.search(ctx) else "spot"
        gas = list(GA.finditer(t, max(0, m.start() - 80), m.start()))
        g = (int(gas[-1].group(1)) * 7 + int(gas[-1].group(2) or 0)) if gas else (title_ga or post_ga)
        out.append((g, kind))
    hema = any(not NEG.search(t[m.end():m.end() + 20]) and "#" not in t[max(0, m.start() - 2):m.start()]
               for m in HEMA.finditer(t))
    return out, hema


def posts(c, pts, queue, cands):
    blog, log_no = parse_post_url(c["url"])
    start = int(log_no)
    d0 = case_date(c, cands)
    items = {}
    p = os.path.join(CDIR, f"{blog}.json")
    if os.path.exists(p):
        for it in json.load(open(p, encoding="utf-8")):
            items[it["logNo"]] = it["title"]
    for q in queue.get(c["case_id"], []):
        items[int(parse_post_url(q["url"])[1])] = q["title"]
    later = []
    for n, title in sorted(items.items()):
        if n <= start or not HINT.search(title):
            continue
        if d0 and (est_date(pts, n) - d0).days > 75:
            break
        later.append(n)
    nums = [start] + later[:8]
    if c.get("followup_url"):
        f = int(parse_post_url(c["followup_url"])[1])
        if f not in nums:
            nums.append(f)
    return blog, nums, d0


RANK = {"red": 3, "brown": 2, "spot": 1}


def collect():
    pts = log_dates()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    queue = {}
    for q in read_csv(os.path.join(DATA, "followup_queue.csv")):
        queue.setdefault(q["case_id"], []).append(q)
    birth = {r["case_id"]: r["status"] for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    miles = {r["case_id"]: r for r in read_csv(os.path.join(DATA, "milestone_log.csv"))}
    old = {r["case_id"]: r for r in read_csv(LOG)}
    rows = []
    for c in read_csv(CASES):
        if c["embryo_day"] not in ("3", "4", "5") or c["outcome"] not in FAILURES | {"심장소리확인"}:
            continue
        if old.get(c["case_id"], {}).get("manual"):
            rows.append(old[c["case_id"]])
            continue
        ga0 = 14 + int(c["embryo_day"])
        hb_ga = ga_of(miles.get(c["case_id"], {}).get("hb", "")) if c["outcome"] == "심장소리확인" else None
        cut = hb_ga or 55
        blog, nums, d0 = posts(c, pts, queue, cands)
        best = {"early": "", "pre": "", "post": ""}
        first, url, hema = None, "", False
        for n in nums:
            post = fetch(blog, str(n))
            title = post.get("title", "")
            tg = [int(m.group(1)) * 7 + int(m.group(2) or 0) for m in GA.finditer(title)]
            pg = ga0 + (est_date(pts, n) - d0).days if d0 else None
            found, h = mentions(" / ".join(x for k, x in post.get("blocks", []) if k == "text"), min(tg) if tg else None, pg)
            hema |= h
            for g, kind in found:
                if g is None:
                    continue
                period = "early" if g <= 28 else "pre" if g < cut else "post" if g <= 90 else None
                if not period:
                    continue
                if RANK[kind] > RANK.get(best[period], 0):
                    best[period] = kind
                if period == "pre" and (first is None or g < first):
                    first, url = g, f"https://m.blog.naver.com/{blog}/{n}"
        rows.append({"case_id": c["case_id"], "embryo_day": c["embryo_day"], "outcome": c["outcome"],
                     "birth": birth.get(c["case_id"], ""), "hb_ga": "" if hb_ga is None else hb_ga,
                     **{k: v or "없음" for k, v in best.items()}, "hematoma": "Y" if hema else "",
                     "first_ga": "" if first is None else f"{first // 7}w{first % 7}d", "posts": len(nums),
                     "evidence_url": url, "manual": ""})
    write_csv(LOG, rows, FIELDS)
    print(f"{len(rows)}건 → {LOG}")


def show():
    pts = log_dates()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    queue = {}
    for q in read_csv(os.path.join(DATA, "followup_queue.csv")):
        queue.setdefault(q["case_id"], []).append(q)
    C = {c["case_id"]: c for c in read_csv(CASES)}
    for cid in sys.argv[2:]:
        blog, nums, _ = posts(C[cid], pts, queue, cands)
        print("#####", cid, C[cid]["outcome"])
        for n in nums:
            t = re.sub(r"\s+", " ", " / ".join(x for k, x in fetch(blog, str(n)).get("blocks", []) if k == "text"))
            hits = [t[max(0, m.start() - 50):m.end() + 30] for m in TERM.finditer(t)][:5]
            if hits:
                print("  ", n % 100000, " ‖ ".join(hits)[:600])


def set_manual():
    rows = read_csv(LOG)
    by = {r["case_id"]: r for r in rows}
    for line in sys.stdin:
        if not line.strip():
            continue
        cid, pre, post, hema, note = (line.rstrip("\n").split("|", 4) + [""] * 5)[:5]
        r = by[cid]
        if pre:
            r["pre"] = pre
        if post:
            r["post"] = post
        if hema:
            r["hematoma"] = "" if hema == "-" else hema
        r["manual"] = note or "수동 확인"
    write_csv(LOG, rows, FIELDS)
    print("기록", sum(bool(r["manual"]) for r in rows))


if __name__ == "__main__":
    {"collect": collect, "show": show, "set": set_manual}[sys.argv[1]]()
