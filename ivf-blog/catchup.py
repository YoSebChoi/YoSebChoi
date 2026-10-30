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
SAC_SMALL = re.compile(r"아기\s*집\s*(?:크기)?\s*(?:이|가|은|는|도)?\s*(?:좀|너무|여전히|많이|조금|약간|계속)?\s*작(?:다|아|고|은|네|대|더)")
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
    small, sac_small = set(), set()
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
        for m in SAC_SMALL.finditer(t):
            if not SMALL_NEG.search(t[m.end():m.end() + 12]) and "#" not in t[max(0, m.start() - 2):m.start()]:
                sac_small.add(b)
                break
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
            if re.match(r"\s*(?:에서|→|➡|에서부터|였던|이었던)", t[m.end():m.end() + 8]):  # '0.35cm에서 1.07cm로'처럼 이전 값을 적은 문장
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
    return seq, st, small, sac_small


OKS = ("출산", "유지12")
# 우리 주수(이식일 기준)에서 앞 1일 ~ 뒤 4일(6주 5일~7주 3일)까지 '비슷한 시기'로 본다 — 7주 무렵 느렸다가 좋아진 케이스 포함
WIN = (-1, 4)


def manual_cases():
    """cases.csv에 없는 케이스(사용자가 알려 준 후기 등): data/manual_cases.csv — traj는 '이식일기준일수:크기mm(0=없음):심박수:URL|…'."""
    out = []
    for r in read_csv(os.path.join(DATA, "manual_cases.csv")):
        traj = []
        for part in r["traj"].split("|"):
            g, c, b, u = part.split(":", 3)
            traj.append((int(g), float(c) or None, int(b) or None, u))
        out.append({**r, "traj": traj})
    return out


def analyze(ga_mine, crl_mine, bpm_mine, win=None, late=True):
    win = win or WIN
    seq, st, small, sac_small = extract()
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

    similar, excluded = [], []
    for b, m in seq.items():
        if b not in st:
            continue
        for g in sorted(m):
            x = m[g]
            if ga_mine + win[0] <= g <= ga_mine + win[1] and ((x.get("crl") and x["crl"] <= crl_mine * 1.2) or (x.get("bpm") and x["bpm"] <= bpm_mine + 7)) \
                    and (not late or late_enough(x.get("crl"), x.get("bpm"))):
                traj = [(gg, m[gg].get("crl"), m[gg].get("bpm"), m[gg].get("url")) for gg in sorted(m) if 38 <= gg <= 70]
                # 우리 아기집은 날짜와 같은 크기 → 아기집이 작다고 들은 케이스는 비교에서 뺀다
                (excluded if b in sac_small else similar).append({"blog": b, "outcome": st[b], "traj": traj})
                break
    mcs = manual_cases()
    manual_blogs = {m["blog"] for m in mcs}  # 수동 입력이 있는 블로그는 자동 추출 대신 수동 값을 쓴다
    similar = [x for x in similar if x["blog"] not in manual_blogs]
    excluded = [x for x in excluded if x["blog"] not in manual_blogs]
    for mc in mcs:
        for g, c, b_, u in mc["traj"]:
            if ga_mine + win[0] <= g <= ga_mine + win[1] and ((c and c <= crl_mine * 1.2) or (b_ and b_ <= bpm_mine + 7)) and (not late or late_enough(c, b_)):
                item = {"blog": mc["blog"], "outcome": mc["outcome"], "traj": mc["traj"], "note": mc["note"], "pgt": mc["pgt"] == "Y"}
                (excluded if mc["sac_small"] == "Y" else similar).append(item)
                break
    sres = collections.Counter(s["outcome"] for s in similar)
    return {"group_n": len(group), "group": res, "similar": similar, "similar_res": sres, "excluded": excluded}


def late_enough(crl_mm, bpm):
    """측정 기준 6주 3일 이후만 비슷한 케이스로 본다. 크기로 계산한 주수가 6주 1~2일이면 110~120bpm은 정상 소견으로 보고 빼며,
    110 미만일 때만 남긴다. 크기 정보가 없으면(심박수만 있는 글) 날짜 주수 창을 그대로 쓴다."""
    if not crl_mm:
        return True
    g = 8.052 * crl_mm ** 0.5 + 23.73
    return g >= 45 or (g >= 43 and bpm is not None and bpm < 110)


def rate(res):
    ok = sum(res[k] for k in OKS)
    n = ok + res["유산"]
    return ok, n


def measured_similar(bpm_mine, slack=12):
    """검색(심박수·크기 검색어)으로 새로 모은 후기에서 '측정 기준 주수 6주 1일~5일, 심박수 ≤ 우리+slack'인 케이스(시험관 / 자연임신)와 경과.
    late: 그중 측정 기준 6주 3일 이후만(6주 1~2일에는 110 안팎도 정상으로 보는 경우가 있어서).
    borderline: 기준 밖이지만 참고할 유산 케이스(similar == 'B').
    natural.py extract/track 이 만든 data/{ivfhb,natural}_{cases,track}.csv 를 읽는다."""
    def cat(t):
        st, wk = t["status"], (int(t["last_week"]) if t["last_week"].isdigit() else 0)
        if st == "출산":
            return "출산"
        if st == "유지12" or (st == "진행중" and wk >= 12):
            return "12주+ 유지"
        if st == "유산":
            return "유산"
        return "진행 중·미상"

    def ga_days(x):
        import re as _re
        m = _re.match(r"(\d+)w(\d)d", x or "")
        return int(m.group(1)) * 7 + int(m.group(2)) if m else 0

    out = {}
    for pfx, key in (("ivfhb", "시험관"), ("natural", "자연임신")):
        cp, tp = os.path.join(DATA, f"{pfx}_cases.csv"), os.path.join(DATA, f"{pfx}_track.csv")
        if not (os.path.exists(cp) and os.path.exists(tp)):
            continue
        tr = {r["blog"]: r for r in read_csv(tp)}
        seen, border = {}, []
        for r in read_csv(cp):
            if r["similar"] == "B":
                if all(b_["blog"] != r["blog"] for b_ in border):
                    border.append(r)
            elif r["similar"] == "Y" and int(r["bpm"]) <= bpm_mine + slack and r["blog"] in tr:
                seen.setdefault(r["blog"], r)
        allitems = [{"blog": b, "row": r, "track": tr[b], "cat": cat(tr[b])} for b, r in seen.items()]

        def keep(x):
            """측정 기준 6주 3일 이후만. 6주 1~2일은 110~120bpm이면 정상 소견으로 보고 빼고, 110 미만만 남긴다."""
            g, b_ = ga_days(x["row"]["crl_ga"]), int(x["row"]["bpm"])
            return g >= 45 or (g in (43, 44) and b_ < 110)
        items = [x for x in allitems if keep(x)]
        dropped = [x for x in allitems if not keep(x)]
        out[key] = {"main": [x for x in items if not x["row"]["sac_small"]], "small": [x for x in items if x["row"]["sac_small"]],
                    "dropped": dropped, "borderline": border}
    return out


def ivf_unified(bpm_mine, crl_mine_mm, date_ga_mine):
    """시험관 비슷한 케이스를 한 목록으로: 모두 '이식일 기준 주수'로 맞춘다.
    - 검색으로 모은 후기(ivfhb_*): data/ga_overrides.csv에 사람이 확인한 이식일 기준 주수(날짜 주수)와, 초음파 기준으로 주수를 바꾼 경우의 보정이 있다.
    - 처음 모은 케이스(cases.csv)에서 찾은 것(analyze)과 수동 입력(manual_cases.csv): 이미 이식일 기준 일수.
    조건: 날짜 주수 6주 3일~7주 3일(날짜 주수 6주 1~2일의 110~120bpm은 정상 소견으로 본다),
          심박수 ≤ 우리+12 이거나 크기가 날짜 주수(CRL 환산)보다 3일 이상 작음. 쌍둥이·자연임신 글은 뺀다."""
    def d(x):
        m = re.match(r"(\d)w(\d)d", x or "")
        return int(m.group(1)) * 7 + int(m.group(2)) if m else None

    def cat(t):
        st, wk = t["status"], (int(t["last_week"]) if t["last_week"].isdigit() else 0)
        if st == "출산":
            return "출산"
        if st == "유지12" or (st == "진행중" and wk >= 12):
            return "12주+ 유지"
        if st == "유산":
            return "유산"
        return "진행 중·미상"

    tr = {r["blog"]: r for r in read_csv(os.path.join(DATA, "ivfhb_track.csv"))}
    ov = {(r["blog"], r["crl_mm"], r["bpm"]): r for r in read_csv(os.path.join(DATA, "ga_overrides.csv"))}
    items, dropped, seen = [], [], set()
    for r in read_csv(os.path.join(DATA, "ivfhb_cases.csv")):
        if r["similar"] != "Y" or r["blog"] not in tr:
            continue
        key = (r["blog"], r["crl_mm"], r["bpm"])
        if key in seen:
            continue
        seen.add(key)
        o = ov.get(key)
        if not o:
            continue
        crl = float(o["crl_mm_new"] or r["crl_mm"] or 0) or None
        bpm = int(o["bpm_new"] or r["bpm"])
        g = d(o["date_ga"])
        it = {"blog": r["blog"], "url": r["url"], "date_ga": g, "crl": crl, "bpm": bpm, "cat": cat(tr[r["blog"]]), "status": tr[r["blog"]],
              "src": o["src"], "flag": o["flag"], "note": o["note"], "small": bool(r["sac_small"]), "via": "검색"}
        ok = g is not None and 45 <= g <= 52 and not o["flag"] and (bpm <= bpm_mine + 12 or (crl and round(g - (8.052 * crl ** 0.5 + 23.73)) >= 3))
        (items if ok else dropped).append(it)
    # 처음 모은 케이스에서 찾은 것(이식일 기준 일수)
    have = {x["blog"] for x in items + dropped}
    cu = analyze(date_ga_mine, crl_mine_mm, bpm_mine, win=(-3, 4), late=False)
    for grp, small in ((cu["similar"], False), (cu["excluded"], True)):
        for s in grp:
            if s["blog"] in have:
                continue
            pts = [(g, c, b_, u) for g, c, b_, u in s["traj"] if 45 <= g <= 52
                   and ((b_ and b_ <= bpm_mine + 12) or (c and round(g - (8.052 * c ** 0.5 + 23.73)) >= 3))]
            if not pts:
                continue
            g, c, b_, u = pts[0]
            items.append({"blog": s["blog"], "url": u, "date_ga": g, "crl": c, "bpm": b_, "cat": {"출산": "출산", "유지12": "12주+ 유지", "유산": "유산"}.get(s["outcome"], "진행 중·미상"),
                          "status": None, "src": "이식일 기준(케이스 기록)", "flag": "", "note": s.get("note", ""), "small": small, "via": "처음 모은 케이스", "pgt": s.get("pgt", False)})
    return items, dropped
