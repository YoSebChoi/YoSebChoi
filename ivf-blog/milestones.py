"""아기집·난황·심장소리를 처음 확인한 임신 주수 — 케이스 글과 이식 후 70일 안의 후속 글 본문에서 자동 추출해
data/milestone_log.csv에 케이스당 한 줄로 남긴다(원문은 저장하지 않고 주수와 글 URL만).

임신 주수(GA)는 마지막 생리일 기준이라 배아 일수와 상관없이 같은 축이다(이식일 = 5일배 2주5일, 4일배 2주4일, 3일배 2주3일).
'처음 확인'은 병원에서 처음 본 날이라 진료 일정에 따라 달라진다 — 생물학적으로 가장 이른 시점이 아니다.

사용: python milestones.py collect   # 글 수집(캐시 사용)·추출
      python milestones.py review    # 순서가 어긋나거나 범위 밖인 줄만 근거 문장과 함께
      python milestones.py set < 줄   # case_id|sac|yolk|hb|메모   (주수는 5w3d 형식, 비우면 그대로, - 는 지움)
"""
import datetime as dt
import json
import os
import re
import sys

from birth import CDIR, case_date, est_date, log_dates
from cases import PATH as CASES
from common import DATA, parse_post_url, read_csv, write_csv
from fetch_posts import fetch

LOG = os.path.join(DATA, "milestone_log.csv")
QUEUE = os.path.join(DATA, "followup_queue.csv")
FIELDS = ["case_id", "embryo_day", "reversal_day", "outcome", "sac", "yolk", "hb", "sac_url", "yolk_url", "hb_url",
          "posts", "manual"]
KEYS = {"sac": re.compile(r"아기집|태낭"), "yolk": re.compile(r"난황"),
        "hb": re.compile(r"심장\s*소리|심장\s*박동|심박|심장이?\s*(뛰|반짝|깜빡)|심장\s*확인|아기\s*심장")}
# 'N주 M일'처럼 일까지 적힌 주수만 쓴다('5주차'만 있으면 어느 날인지 알 수 없고, 일반론 문장이 많이 걸린다)
GA = re.compile(r"(?<!\d)([4-9]|10)\s*(?:주|w|W)\s*(?:차\s*)?([0-6])\s*(?:일|d|D)(?![0-9])")
FLOOR = {"sac": 30, "yolk": 33, "hb": 38}  # 4주2일·4주5일·5주3일보다 이른 값은 오탐으로 본다
NEG = re.compile(r"^.{0,14}(안\s*(보|들|뛰|나)|못\s*(보|들|봤|확인|하)|없|아직|보이지|들리지|안보|안들|않|듣기\s*전|보기\s*전|전이라|전까지)")
FUTURE = re.compile(r"^.{0,22}(들으러|보러|기대|예정|바라|기원|기도|빌|길\s*바|ㄱㄷ|두근|떨려|무서|들을\s*수\s*있을|볼\s*수\s*있을|있을\s*거|"
                    r"들을지|볼지|듣길|보길|들려줄까|보여줄까|다음|단계|만\s*들어도|들어야|봐야|라는데|라고\s*한다|이라고|확인하는\s*시기|"
                    r"들을\s*수\s*있는|볼\s*수\s*있는|선|수치)")
# 키워드 바로 앞이 일반론·바람·과거 차수 이야기면 제외
PRE = re.compile(r"(아직|혹시|보통|대체로|대부분|최소|부디|다음\s*주?|언제|지난\s*차수|다른\s*분|이번엔|이제\s*몇|빨리|얼른|주차에|주에)\s*\S{0,6}$")
TITLE_HINT = re.compile(r"아기집|난황|심장|심박|초음파|\d\s*주|주차|피검|졸업|임신\s*확인")


def ga_days(m):
    return int(m.group(1)) * 7 + int(m.group(2) or 0)


def fmt(d):
    return "" if d is None else f"{d // 7}w{d % 7}d"


def parse(s):
    m = re.match(r"(\d+)w(\d)d", s or "")
    return int(m.group(1)) * 7 + int(m.group(2)) if m else None


def first_seen(text, title):
    """본문에서 키워드별로 '확인했다'는 문맥의 가장 이른 주수(일 단위)."""
    t = re.sub(r"\s+", " ", text)
    tga = [ga_days(m) for m in GA.finditer(title)]
    out = {}
    for k, rx in KEYS.items():
        best = None
        for m in rx.finditer(t):
            after = re.split(r"[.!?,/~\n]|아기집|태낭|난황|심장|심박", t[m.end():m.end() + 30])[0]
            if NEG.search(after) or FUTURE.search(after) or PRE.search(t[max(0, m.start() - 14):m.start()]):
                continue
            before = t[max(0, m.start() - 70):m.start()]
            pre, post = list(GA.finditer(before)), list(GA.finditer(t[m.end():m.end() + 25]))
            if pre or post:
                g = ga_days(pre[-1] if pre else post[0])
            elif tga:
                g = min(tga)
            else:
                continue
            if not (FLOOR[k] <= g <= 76):
                continue
            best = g if best is None else min(best, g)
        if best is not None:
            out[k] = best
    return out


def posts_for(c, pts, queue, cands):
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
        if n <= start or not TITLE_HINT.search(title):
            continue
        if d0 and (est_date(pts, n) - d0).days > 70:
            break
        later.append(n)
    nums = [start] + later[:6]
    if c.get("followup_url"):
        f = int(parse_post_url(c["followup_url"])[1])
        if f not in nums:
            nums.append(f)
    return blog, nums


def collect():
    pts = log_dates()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    queue = {}
    for q in read_csv(QUEUE):
        queue.setdefault(q["case_id"], []).append(q)
    old = {r["case_id"]: r for r in read_csv(LOG)}
    rows = []
    for c in read_csv(CASES):
        if c["embryo_day"] not in ("3", "4", "5") or c["outcome"] not in ("심장소리확인", "아기집만(계류)"):
            continue
        if old.get(c["case_id"], {}).get("manual"):
            rows.append(old[c["case_id"]])
            continue
        blog, nums = posts_for(c, pts, queue, cands)
        best = {}
        for n in nums:
            post = fetch(blog, str(n))
            text = " / ".join(x for k, x in post.get("blocks", []) if k == "text")
            for k, g in first_seen(text, post.get("title", "")).items():
                if k not in best or g < best[k][0]:
                    best[k] = (g, f"https://m.blog.naver.com/{blog}/{n}")
        if c["outcome"] != "심장소리확인":
            best.pop("hb", None)
        rows.append({"case_id": c["case_id"], "embryo_day": c["embryo_day"], "reversal_day": c["reversal_day"],
                     "outcome": c["outcome"], "posts": len(nums), "manual": "",
                     **{k: fmt(best[k][0]) if k in best else "" for k in KEYS},
                     **{f"{k}_url": best[k][1] if k in best else "" for k in KEYS}})
        if len(rows) % 25 == 0:
            print(len(rows), flush=True)
            write_csv(LOG, rows, FIELDS)
    write_csv(LOG, rows, FIELDS)
    print(f"{len(rows)}건 → {LOG}")


def suspicious(r):
    s, y, h = (parse(r[k]) for k in ("sac", "yolk", "hb"))
    seq = [v for v in (s, y, h) if v is not None]
    return seq != sorted(seq) or (h is not None and h > 63) or (s is not None and s > 49)


def review():
    for r in read_csv(LOG):
        if r["manual"] or not suspicious(r):
            continue
        print(f"{r['case_id']} d{r['embryo_day']} | 아기집 {r['sac'] or '-'} 난황 {r['yolk'] or '-'} 심장 {r['hb'] or '-'}")
        for k in KEYS:
            if not r[f"{k}_url"]:
                continue
            post = fetch(*parse_post_url(r[f"{k}_url"]))
            t = re.sub(r"\s+", " ", " / ".join(x for kk, x in post.get("blocks", []) if kk == "text"))
            hits = [t[max(0, m.start() - 45):m.end() + 20] for m in KEYS[k].finditer(t)][:3]
            print(f"   {k}: " + " … ".join(hits)[:300])


def set_manual():
    rows = read_csv(LOG)
    by = {r["case_id"]: r for r in rows}
    for line in sys.stdin:
        if not line.strip():
            continue
        cid, sac, yolk, hb, note = (line.rstrip("\n").split("|", 4) + [""] * 5)[:5]
        r = by[cid]
        for k, v in (("sac", sac), ("yolk", yolk), ("hb", hb)):
            if v == "-":
                r[k] = ""
            elif v:
                r[k] = v
        r["manual"] = note or "수동 확인"
    write_csv(LOG, rows, FIELDS)
    print("기록", sum(bool(r["manual"]) for r in rows))


if __name__ == "__main__":
    {"collect": collect, "review": review, "set": set_manual}[sys.argv[1]]()
