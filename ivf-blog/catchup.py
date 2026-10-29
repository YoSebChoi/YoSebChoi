"""초음파 아기 크기·심박수를 후기 본문에서 이식일 기준 주수로 뽑아, '주수보다 작거나 느렸던' 케이스와
우리와 비슷한 케이스가 이후 따라잡고 출산했는지 센다(summary_report.py가 씀).

주수: 문장 근처 날짜(이식일로 계산) → 없으면 글에 적힌 'N주 M일'(글 작성일과 맞는 것만). '6주 3일 크기'처럼
크기로 매긴 주수와 '지난 진료에서는 …'처럼 이전 값을 다시 적은 문장은 뺀다.
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import statistics

from birth import after_hb, case_date, est_date, log_dates
from common import CACHE, DATA, read_csv

GA = re.compile(r"([5-9])\s*주\s*차?\s*([0-6])\s*일")
SIZELBL = re.compile(r"^\s*(?:정도\s*)?(?:의\s*)?(?:크기|사이즈|크기로|사이즈로|로\s*측정|에\s*해당)")
DATE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*(?:월\s*|[/.]\s*)([12]\d|3[01]|0?[1-9])\s*일?(?![\d])")
NUM = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})?)\s*(cm|mm|센치|센티|미리|㎝|㎜)")
WHO = re.compile(r"CRL|crl|Crl|아기(?!\s*집)|태아|아가(?!\s*집)|애기(?!\s*집)|콩|젤리곰|곰돌|키|머리\s*엉덩이|배아")
BAD = re.compile(r"아기\s*집|애기\s*집|아가\s*집|난황|피\s*고임|혈종|자궁|경부|난포|내막|근종|낭종|물혹|GS|gs|MSD|태낭|목투명|NT|nt")
BPM = re.compile(r"(\d{2,3})\s*(?:bpm|BPM|회|비피엠)")
RECAP = re.compile(r"지난\s*(?:번|진료|주|초음파)|저번|이전\s*(?:진료|초음파)|전에는")
# '주수보다 작다', '심장이 느리다', '아기가 작다', '주수가 밀렸다' 같은 말(부정·해시태그 제외)
SMALL = re.compile(r"주수보다\s*(?:조금|약간|좀|살짝|며칠|하루|이틀|\d\s*일)?\s*(?:작|느리|늦|어리)|"
                   r"심장\s*(?:소리|박동|박동수|박수)?\s*(?:가|이|는)?\s*(?:너무|좀|조금|약간|아직|많이)?\s*(?:느리|느려|느린|약하)|"
                   r"(?:아기|태아|애기)\s*(?:크기|키)?\s*(?:가|도|는)?\s*(?:너무|좀|조금|약간)?\s*작(?:다|아|고|은|네)|주수\s*(?:가|보다)?\s*밀")
SMALL_NEG = re.compile(r"^.{0,10}(?:않|아니|안\s*(?:느리|작))")


def extract():
    pts = log_dates()
    cand = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    T = {}
    for c in read_csv(os.path.join(DATA, "cases.csv")):
        if c["embryo_day"] in ("3", "4", "5"):
            d0 = case_date(c, cand)
            if d0:
                T.setdefault(c["url"].split("/")[3], (d0, int(c["embryo_day"])))
    seq = collections.defaultdict(dict)
    small = set()
    for f in glob.glob(os.path.join(CACHE, "posts", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        b = d.get("blog_id")
        if b not in T:
            continue
        tr, emb = T[b]
        ga0 = 14 + emb
        post_ga = ga0 + (est_date(pts, int(d["log_no"])) - tr).days
        t = re.sub(r"\s+", " ", " ".join(x for k, x in d.get("blocks", []) if k == "text"))
        url = f"https://m.blog.naver.com/{b}/{d['log_no']}"
        for m in SMALL.finditer(t):
            if not SMALL_NEG.search(t[m.end():m.end() + 12]) and "#" not in t[max(0, m.start() - 2):m.start()]:
                small.add(b)
                break

        def resolve(pos):
            if RECAP.search(t[max(0, pos - 40):pos]):
                return None
            for m in reversed(list(DATE.finditer(t[max(0, pos - 60):pos]))):
                for y in (tr.year, tr.year + 1):
                    try:
                        dd = dt.date(y, int(m[1]), int(m[2]))
                    except ValueError:
                        continue
                    g = ga0 + (dd - tr).days
                    if 35 <= g <= 77 and g <= post_ga + 3:
                        return g
            gs = list(GA.finditer(t[max(0, pos - 90):pos]))
            if not gs:
                return None
            m = gs[-1]
            base = max(0, pos - 90)
            if SIZELBL.search(t[base + m.end():base + m.end() + 12]) or re.search(r"(아기|태아)\s*크기\s*$", t[base:base + m.start()][-12:]):
                return None
            g = int(m[1]) * 7 + int(m[2])
            return g if post_ga - 21 <= g <= post_ga + 3 else None

        for m in NUM.finditer(t):
            v = float(m[1]) * (1 if m[2] in ("mm", "미리", "㎜") else 10)
            pre = t[max(0, m.start() - 25):m.start()]
            w = list(WHO.finditer(pre))
            if not (1 <= v <= 40) or not w or BAD.search(pre[w[-1].start():]) or BAD.search(t[m.end():m.end() + 6]):
                continue
            g = resolve(m.start())
            if g:
                seq[b].setdefault(g, {}).setdefault("crl", v)
                seq[b][g].setdefault("url", url)
        for m in BPM.finditer(t):
            v = int(m[1])
            if not 70 <= v <= 200 or not re.search(r"심박|심장|bpm", t[max(0, m.start() - 40):m.end() + 5]):
                continue
            g = resolve(m.start())
            if g:
                seq[b].setdefault(g, {}).setdefault("bpm", v)
                seq[b][g].setdefault("url", url)
    adj = after_hb()
    st = {}
    for c in read_csv(os.path.join(DATA, "cases.csv")):
        b = c["url"].split("/")[3]
        if c["outcome"] == "심장소리확인":
            st[b] = adj.get(c["case_id"]) or "미상"
    return seq, st, small


OKS = ("출산", "유지12")


def analyze(ga_mine, crl_mine, bpm_mine):
    seq, st, small = extract()
    # 반주 단위(0~3일 / 4~6일) 기준값: 그 구간 아래쪽 25%
    bins = collections.defaultdict(lambda: {"crl": [], "bpm": []})
    for b, m in seq.items():
        for g, x in m.items():
            for k in ("crl", "bpm"):
                if k in x:
                    bins[(g // 7, g % 7 >= 4)][k].append(x[k])
    q1 = {key: {k: statistics.quantiles(v[k], n=4)[0] for k in v if len(v[k]) >= 8} for key, v in bins.items()}
    behind = []
    for b, m in seq.items():
        if b not in st:
            continue
        for g in sorted(m):
            if not 42 <= g <= 56:
                continue
            lim = q1.get((g // 7, g % 7 >= 4), {})
            if any(k in m[g] and k in lim and m[g][k] < lim[k] for k in ("crl", "bpm")):
                behind.append(b)
                break
    group = set(behind) | (small & set(st))
    res = collections.Counter(st[b] for b in group)

    similar = []
    for b, m in seq.items():
        if b not in st:
            continue
        for g in sorted(m):
            x = m[g]
            if ga_mine - 1 <= g <= ga_mine + 2 and ((x.get("crl") and x["crl"] <= crl_mine * 1.2) or (x.get("bpm") and x["bpm"] <= bpm_mine + 7)):
                traj = [(gg, m[gg].get("crl"), m[gg].get("bpm"), m[gg].get("url")) for gg in sorted(m) if 38 <= gg <= 70]
                similar.append({"blog": b, "outcome": st[b], "traj": traj})
                break
    sres = collections.Counter(s["outcome"] for s in similar)
    return {"group_n": len(group), "group": res, "similar": similar, "similar_res": sres}


def rate(res):
    ok = sum(res[k] for k in OKS)
    n = ok + res["유산"]
    return ok, n
