"""피검(hCG) 수치를 케이스 글·후속 글에서 뽑아 이식 후 경과일(5일배 기준)과 함께 data/hcg_log.csv에 남긴다.

경과일 = 이식일 0일. 3일배는 −2일, 4일배는 −1일로 5일배와 같은 축에 맞춘다(3일배 이식 11일 ≈ 5일배 이식 9일).
날은 수치 앞쪽(없으면 뒤쪽)에서 가장 가까운 표현으로 정한다: '+9', 'D+9', '이식 후 9일', '9일차', '9dp5dt', 날짜(이식일을 알 때).
cases.csv의 hcg 칸(2단계에서 직접 적은 값)이 있으면 그것을 우선한다.

group  출산 / 심장후유산 / 심장(진행·미상) / 무심장(계류·화유·자궁외)

사용: python hcg.py collect
      python hcg.py review    # 시간에 따라 거꾸로 가거나 범위를 벗어나는 줄
      python hcg.py set < 줄   # case_id|9:90;14:1695|메모  (경과일:수치, 5일배 기준) — 비우면 그 케이스 제외
"""
import datetime as dt
import math
import os
import re
import sys

from birth import log_dates
from cases import FAILURES, PATH as CASES
from common import DATA, parse_post_url, read_csv, write_csv
from fetch_posts import fetch
from milestones import posts_for

LOG = os.path.join(DATA, "hcg_log.csv")
FIELDS = ["case_id", "embryo_day", "reversal_day", "outcome", "group", "values", "source", "manual"]
SHIFT = {"5": 0, "4": 1, "3": 2}
KEY = re.compile(r"피검\s*(?:사)?\s*(?:결과)?\s*(?:수치)?|h\s*cg|HCG|hCG|베타\s*(?:수치)?")
NUM = re.compile(r"(?<![\d.,+])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d,])(?!\s*(?:일|차|주|월|시|분|mm|cm|bpm|원|kg|개|%|배|살|세|년|번|회|mg|ml|ng|명|층|호|단계|시간|도|pg|dp|이상|이하|미만|넘|정도|만\s|대\s|쯤|안팎|배양))")
DAYS = [(re.compile(r"(\d{1,2})\s*dp\s*\d?\s*d?\s*t", re.I), "dpt"),
        (re.compile(r"이식\s*(?:후\s*)?(\d{1,2})\s*일"), "dpt"),
        (re.compile(r"(?<![\d.])(?:D\s*)?\+\s*(\d{1,2})(?![\d.])"), "dpt"),
        (re.compile(r"(?<![\d.])(\d{1,2})\s*일\s*(?:차|째)"), "cha"),
        (re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "date"),
        (re.compile(r"(?<![\d.])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])"), "date")]
MANUAL = re.compile(r"([\d,.]+)\+?\s*\(([^)]*)\)")
MANUAL_DAY = re.compile(r"[dD]\s*(\d{1,2})|(\d{1,2})\s*일\s*차|\+\s*(\d{1,2})")


def day_of(m, kind, c):
    if kind == "date":
        if not c.get("transfer_date"):
            return None
        t = dt.date.fromisoformat(c["transfer_date"])
        for y in (t.year, t.year + 1):
            try:
                d = (dt.date(y, int(m.group(1)), int(m.group(2))) - t).days
            except ValueError:
                return None
            if 0 <= d <= 40:
                return d
        return None
    d = int(m.group(1))
    if kind == "cha" and c.get("count_basis") == "one":
        d -= 1
    return d


def nearest_day(text, pos, c):
    best = None
    for rx, kind in DAYS:
        for m in rx.finditer(text, max(0, pos - 60), pos):
            if best is None or m.end() > best[0].end():
                best = (m, kind)
    if best is None:
        for rx, kind in DAYS:
            m = rx.search(text, pos, pos + 25)
            if m and (best is None or m.start() < best[0].start()):
                best = (m, kind)
    return day_of(*best, c) if best else None


def extract(text, c):
    out = {}
    t = re.sub(r"\s+", " ", text)
    for k in KEY.finditer(t):
        m = NUM.search(t, k.end(), k.end() + 30)
        if not m or len(re.findall(r"[가-힣]", t[k.end():m.start()])) > 8:
            continue
        v = float(m.group(1).replace(",", ""))
        d = nearest_day(t, k.start(), c)
        if d is None or not (5 <= d <= 30) or not (5 <= v <= 300000) or re.fullmatch(r"20[12]\d(\.\d+)?", m.group(1)):
            continue
        d5 = d - SHIFT[c["embryo_day"]]
        if d5 < 6:
            continue
        out.setdefault(d5, v)
    return out


def from_manual(c):
    out = {}
    for m in MANUAL.finditer(c.get("hcg", "")):
        dm = MANUAL_DAY.search(m.group(2))
        try:
            v = float(m.group(1).replace(",", "").rstrip("."))
        except ValueError:
            continue
        if dm:
            out.setdefault(int(next(g for g in dm.groups() if g)) - SHIFT[c["embryo_day"]], v)
    return out


def group_of(c, birth):
    if c["outcome"] in FAILURES:
        return "무심장"
    if c["outcome"] != "심장소리확인":
        return ""
    st = birth.get(c["case_id"], {}).get("status", "")
    return {"출산": "출산", "유산": "심장후유산"}.get(st, "심장(진행·미상)")


def fmt(vals):
    return ";".join(f"{d}:{v:g}" for d, v in sorted(vals.items()))


def parse(s):
    out = {}
    for part in filter(None, (s or "").split(";")):
        d, v = part.split(":")
        out[int(d)] = float(v)
    return out


def collect():
    pts = log_dates()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    queue = {}
    for q in read_csv(os.path.join(DATA, "followup_queue.csv")):
        queue.setdefault(q["case_id"], []).append(q)
    birth = {r["case_id"]: r for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    old = {r["case_id"]: r for r in read_csv(LOG)}
    rows = []
    for c in read_csv(CASES):
        g = group_of(c, birth) if c["embryo_day"] in SHIFT else ""
        if not g:
            continue
        prev = old.get(c["case_id"])
        if prev and prev.get("manual"):
            prev["group"] = g
            rows.append(prev)
            continue
        vals, src = from_manual(c), "cases.hcg"
        if not vals:
            blog, nums = posts_for(c, pts, queue, cands)
            vals, src = {}, "auto"
            for n in nums:
                post = fetch(blog, str(n))
                for d, v in extract(" / ".join(x for k, x in post.get("blocks", []) if k == "text"), c).items():
                    vals.setdefault(d, v)
        rows.append({"case_id": c["case_id"], "embryo_day": c["embryo_day"], "reversal_day": c["reversal_day"],
                     "outcome": c["outcome"], "group": g, "values": fmt(vals), "source": src, "manual": ""})
    write_csv(LOG, rows, FIELDS)
    print(f"{len(rows)}건, 수치 있음 {sum(bool(r['values']) for r in rows)} → {LOG}")


def suspicious(r):
    v = sorted(parse(r["values"]).items())
    if not v:
        return False
    bad_range = any(x > 30 * 2 ** ((d - 9) / 1.4) * 40 or x < 30 * 2 ** ((d - 9) / 1.4) / 60 for d, x in v)
    falling = r["group"] != "무심장" and any(b[1] < a[1] for a, b in zip(v, v[1:]))
    return bad_range or falling


def review():
    for r in read_csv(LOG):
        if not r["manual"] and suspicious(r):
            print(f"{r['case_id']} d{r['embryo_day']} {r['group']} | {r['values']}")


def set_manual():
    rows = read_csv(LOG)
    by = {r["case_id"]: r for r in rows}
    for line in sys.stdin:
        if not line.strip():
            continue
        cid, vals, note = (line.rstrip("\n").split("|", 2) + ["", ""])[:3]
        by[cid]["values"] = vals
        by[cid]["manual"] = note or "수동 확인"
    write_csv(LOG, rows, FIELDS)
    print("기록", sum(bool(r["manual"]) for r in rows))


def doubling(vals):
    """첫 값과 마지막 값으로 더블링 시간(일)."""
    v = sorted(vals.items())
    if len(v) < 2 or v[-1][1] <= v[0][1] or v[-1][0] == v[0][0]:
        return None
    return (v[-1][0] - v[0][0]) * math.log(2) / math.log(v[-1][1] / v[0][1])


if __name__ == "__main__":
    {"collect": collect, "review": review, "set": set_manual}[sys.argv[1]]()
