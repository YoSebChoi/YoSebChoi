"""data/hcg_log.csv → 피검 수치 보고서(그룹별 일자별 수치, 내 수치의 위치, 비슷한 케이스의 결과 확률)

사용: python hcg_report.py --mine 9:90,14:1695 [--transfer 2026-09-30 --embryo 5 --scan 2026-10-21 --seen '아기집 확인 1.02cm' --next 2026-11-05] [--out ...]
--mine 은 5일배 기준 경과일(이식일 = 0일):수치. 개인 수치가 들어간 결과 파일은 커밋하지 않는다(.gitignore).
"""
import argparse
import datetime
import html
import math
import os
import random
import statistics

from cases import PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from hcg import parse
from milestones import parse as ga_of
from report import CSS
from summarize import wilson

GROUPS = [("출산", "심장소리 → 출산", "var(--accent)"), ("심장후유산", "심장소리 → 유산", "var(--mid)"),
          ("심장(진행·미상)", "심장소리 → 진행 중·미상", "var(--hb)"), ("무심장", "심장소리 못 들음", "var(--low)")]
DAYS = range(7, 18)


def case_slope(v):
    pts = sorted((d, math.log(x)) for d, x in v.items() if 6 <= d <= 20)
    if len(pts) < 2 or pts[-1][0] == pts[0][0]:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


def at(v, t, fallback):
    """그 날의 수치: 앞뒤 측정값 사이면 로그 보간, 아니면 2일 안의 값을 자기(없으면 전체) 상승 속도로 옮김."""
    pts = sorted((d, math.log(x)) for d, x in v.items() if 6 <= d <= 20)
    if not pts:
        return None
    for (d0, a), (d1, b) in zip(pts, pts[1:]):
        if d0 <= t <= d1 and d1 - d0 <= 8:
            return math.exp(a + (b - a) * (t - d0) / (d1 - d0)) if d1 > d0 else math.exp(a)
    d, a = min(pts, key=lambda p: abs(p[0] - t))
    if abs(d - t) > 2:
        return None
    s = case_slope(v)
    return math.exp(a + ((s if s and s > 0 else fallback) * (t - d)))


def pctile(vals, x):
    return sum(v < x for v in vals) / len(vals) * 100 if vals else float("nan")


def fit_logit(xs, ys, iters=50):
    a = b = 0.0
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            w = p * (1 - p)
            ga += y - p
            gb += (y - p) * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if abs(det) < 1e-12:
            break
        a += (hbb * ga - hab * gb) / det
        b += (haa * gb - hab * ga) / det
    return a, b


def logit_p(xs, ys, x0, boot=400):
    a, b = fit_logit(xs, ys)
    p = 1 / (1 + math.exp(-(a + b * x0)))
    rnd = random.Random(7)
    sims = []
    idx = list(range(len(xs)))
    for _ in range(boot):
        s = [rnd.choice(idx) for _ in idx]
        if len({ys[i] for i in s}) < 2:
            continue
        aa, bb = fit_logit([xs[i] for i in s], [ys[i] for i in s], 25)
        sims.append(1 / (1 + math.exp(-(aa + bb * x0))))
    sims.sort()
    return p, sims[int(len(sims) * .025)], sims[int(len(sims) * .975)]


def fmtn(x):
    return "—" if x is None else (f"{x:,.0f}" if x >= 10 else f"{x:.1f}")


def pct(x, d=0):
    return "—" if x != x else f"{x * 100:.{d}f}%"


def band_chart(series, mine):
    """로그 축. series: [(이름, 색, {day: [values]})]. 띠 = 가운데 50%, 선 = 중앙값."""
    w, h, left, right, top, bottom = 680, 340, 56, 20, 16, 34
    y0, y1 = math.log10(10), math.log10(20000)
    x = lambda d: left + (w - left - right) * (d - DAYS[0]) / (DAYS[-1] - DAYS[0])
    y = lambda v: top + (h - top - bottom) * (1 - (math.log10(max(v, 10)) - y0) / (y1 - y0))
    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="일자별 피검 수치" class="chart">']
    for v in (10, 30, 100, 300, 1000, 3000, 10000):
        p.append(f'<line x1="{left}" y1="{y(v):.1f}" x2="{w - right}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{left - 8}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{v:,}</text>')
    for d in DAYS:
        p.append(f'<text x="{x(d):.1f}" y="{h - 12}" class="tick" text-anchor="middle">{d}일</text>')
    for name, color, by in series:
        qs = [(d, statistics.quantiles(by[d], n=4, method="inclusive")) for d in DAYS if len(by.get(d, [])) >= 4]
        if len(qs) < 2:
            continue
        up = " ".join(f"{x(d):.1f},{y(q[2]):.1f}" for d, q in qs)
        dn = " ".join(f"{x(d):.1f},{y(q[0]):.1f}" for d, q in reversed(qs))
        md = " ".join(f"{x(d):.1f},{y(q[1]):.1f}" for d, q in qs)
        p.append(f'<polygon points="{up} {dn}" style="fill:{color};opacity:.16"/>'
                 f'<polyline points="{md}" style="fill:none;stroke:{color};stroke-width:2.5"/>')
        for d, q in qs:
            p.append(f'<circle cx="{x(d):.1f}" cy="{y(q[1]):.1f}" r="7" class="hit"><title>{html.escape(name)} {d}일: '
                     f'중앙값 {fmtn(q[1])}, 가운데 50% {fmtn(q[0])}~{fmtn(q[2])} (n={len(by[d])})</title></circle>')
    pts = sorted(mine.items())
    if len(pts) > 1:
        p.append('<polyline points="' + " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in pts)
                 + '" style="fill:none;stroke:var(--fg);stroke-width:1.5;stroke-dasharray:4 3"/>')
    for d, v in pts:
        p.append(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="6" style="fill:var(--fg);stroke:var(--panel);stroke-width:2">'
                 f'<title>우리 {d}일: {fmtn(v)}</title></circle>'
                 f'<text x="{x(d) + 9:.1f}" y="{y(v) - 8:.1f}" class="val">{fmtn(v)}</text>')
    p.append("</svg>")
    return "".join(p)


MS = [("sac", "아기집", "var(--mid)"), ("yolk", "난황", "var(--accent)"), ("hb", "심장", "var(--hb)")]


def gw(g):
    return f"{g // 7}주 {g % 7}일"


def schedule(sim_ids, birth_ids, miles, transfer, embryo, scan, nxt=None, seen=""):
    """첫 확인 주수를 우리 날짜로 옮긴 예상 일정. 기준: 심장소리 → 출산 케이스(비슷한 수치 / 전체), 심장소리 확인 전체."""
    ga0 = 14 + embryo
    day = lambda g: transfer + datetime.timedelta(days=g - ga0)
    md = lambda g: f"{day(g).month}/{day(g).day}"
    hb = [r for r in miles if r["outcome"] == "심장소리확인"]
    born = [r for r in hb if r["case_id"] in birth_ids]
    sets = [("출산 · 비슷한 수치", [r for r in born if r["case_id"] in sim_ids]), ("출산 케이스 전체", born),
            ("심장소리 확인 전체", hb)]
    sg = ga0 + (scan - transfer).days if scan else None
    ng = ga0 + (nxt - transfer).days if nxt else None
    vals = lambda rs, k: sorted(ga_of(r[k]) for r in rs if ga_of(r[k]))

    def first_any(r):
        v = [ga_of(r[k]) for k, _, _ in MS if ga_of(r[k])]
        return min(v) if v else None

    head = "".join(f"<th>{n}</th>" for n, _ in sets)
    t1, t2 = [], []
    for k, name, _ in MS:
        c1, c2 = [], []
        for _, rs in sets:
            v = vals(rs, k)
            if len(v) >= 4:
                q = statistics.quantiles(v, n=4, method="inclusive")
                c1.append(f'<td><b>{gw(round(q[1]))} · {md(round(q[1]))}</b><br>'
                          f'<span class="muted">{md(round(q[0]))}~{md(round(q[2]))} · {len(v)}</span></td>')
            else:
                c1.append(f'<td class="muted">{", ".join(md(g) for g in v) or "—"}</td>')
            if sg:
                sc = [r for r in rs if first_any(r) and first_any(r) <= sg]
                ok = sum(1 for r in sc if ga_of(r[k]) and ga_of(r[k]) <= sg)
                c2.append(f'<td class="num"><b>{pct(ok / len(sc)) if sc else "—"}</b> <span class="muted">{ok}/{len(sc)}</span></td>')
        t1.append(f"<tr><td>{name}</td>{''.join(c1)}</tr>")
        t2.append(f"<tr><td>{name}</td>{''.join(c2)}</tr>")
    table = (f'<div class="tbl"><table><thead><tr><th>첫 확인 (중앙값 · 가운데 50% · 건수)</th>{head}</tr></thead>'
             f'<tbody>{"".join(t1)}</tbody></table></div>')
    if sg:
        table += (f'<h3>{scan.month}/{scan.day} 초음파({gw(sg)}) — 다른 케이스는 이 주수까지 무엇을 봤나'
                  + (f' · <span style="color:var(--hb)">우리 결과: {html.escape(seen)}</span>' if seen else "") + '</h3>'
                  f'<div class="tbl"><table><thead><tr><th>그 주수까지 초음파를 본 케이스 중 확인 비율</th>{head}</tr></thead>'
                  f'<tbody>{"".join(t2)}</tbody></table></div>')

    if ng:
        cells = []
        for _, rs in sets:
            v = vals(rs, "hb")
            ok = sum(x <= ng for x in v)
            cells.append(f'<td class="num"><b>{pct(ok / len(v)) if v else "—"}</b> <span class="muted">{ok}/{len(v)}</span></td>')
        table += (f'<h3>{nxt.month}/{nxt.day} 심장소리 예정({gw(ng)}) — 이 주수까지 심장을 처음 확인한 비율</h3>'
                  f'<div class="tbl"><table><thead><tr><th>심장소리 확인 케이스 중</th>{head}</tr></thead>'
                  f'<tbody><tr><td>심장</td>{"".join(cells)}</tr></tbody></table></div>')

    # 누적 곡선: 실선 = 출산 케이스 전체, 점선 = 심장소리 확인 전체
    g0, g1 = ga0 + 14, max(ga0 + 35, (ng or 0) + 3)
    w, h, left, right, top, bottom = 680, 250, 44, 20, 14, 46
    x = lambda g: left + (w - left - right) * (g - g0) / (g1 - g0)
    y = lambda p: top + (h - top - bottom) * (1 - p)
    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="주수별 누적 확인 비율" class="chart">']
    for v in (0, .25, .5, .75, 1):
        p.append(f'<line x1="{left}" y1="{y(v):.1f}" x2="{w - right}" y2="{y(v):.1f}" class="grid"/>'
                 f'<text x="{left - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{int(v * 100)}%</text>')
    for g in range(g0, g1 + 1):
        if g % 7 == 0:
            p.append(f'<text x="{x(g):.1f}" y="{h - 26}" class="tick" text-anchor="middle">{g // 7}주</text>'
                     f'<text x="{x(g):.1f}" y="{h - 10}" class="tick" text-anchor="middle">{md(g)}</text>')
    for rs, dash, wd in ((hb, "5 4", 1.5), (born, "", 2.5)):
        for k, name, color in MS:
            va = vals(rs, k)
            pts = " ".join(f"{x(g):.1f},{y(sum(v <= g for v in va) / len(va)):.1f}" for g in range(g0, g1 + 1))
            p.append(f'<polyline points="{pts}" style="fill:none;stroke:{color};stroke-width:{wd};stroke-dasharray:{dash or "none"}"/>')
    if sg and g0 <= sg <= g1:
        p.append(f'<line x1="{x(sg):.1f}" y1="{top}" x2="{x(sg):.1f}" y2="{h - bottom}" style="stroke:var(--fg);stroke-width:1.5;stroke-dasharray:4 3"/>'
                 f'<text x="{x(sg) + 6:.1f}" y="{top + 12}" class="val">초음파 {md(sg)}</text>')
    if ng and g0 <= ng <= g1:
        p.append(f'<line x1="{x(ng):.1f}" y1="{top}" x2="{x(ng):.1f}" y2="{h - bottom}" style="stroke:var(--hb);stroke-width:1.5;stroke-dasharray:4 3"/>'
                 f'<text x="{x(ng) - 6:.1f}" y="{top + 12}" class="val" text-anchor="end">심장 예정 {md(ng)}</text>')
    p.append("</svg>")
    legend = '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{n}</span>' for _, n, c in MS) + \
             '<span>실선: 출산 케이스 · 점선: 심장소리 확인 전체 · 그 날까지 처음 확인한 비율</span></div>'
    return table, legend + "".join(p), sg


def build(rows, cases, miles, mine, transfer=None, embryo=5, scan=None, nxt=None, seen=""):
    allv = [r for r in rows if r["values"]]
    slopes = [s for r in allv if r["group"] != "무심장" for s in [case_slope(parse(r["values"]))] if s and s > 0]
    S = statistics.median(slopes)
    est = {r["case_id"]: {d: at(parse(r["values"]), d, S) for d in DAYS} for r in allv}
    by = {g: {d: [est[r["case_id"]][d] for r in allv if r["group"] == g and est[r["case_id"]][d]] for d in DAYS}
          for g, _, _ in GROUPS}
    hb_all = {d: sum((by[g][d] for g in ("출산", "심장후유산", "심장(진행·미상)")), []) for d in DAYS}
    md = sorted(mine)
    d1, d2 = md[0], md[-1]
    dt_mine = (d2 - d1) * math.log(2) / math.log(mine[d2] / mine[d1]) if len(md) > 1 and mine[d2] > mine[d1] else None
    dts = {g: [math.log(2) / s for r in allv if r["group"] == g for s in [case_slope(parse(r["values"]))] if s and s > 0]
           for g, _, _ in GROUPS}
    outcome = {c["case_id"]: c["outcome"] for c in cases}
    yolk = {r["case_id"] for r in miles if r["yolk"]}

    # 비슷한 케이스: 두 번째 수치 날의 추정값이 우리 값의 0.5~2배
    lo2, hi2 = mine[d2] / 2, mine[d2] * 2
    sim = [r for r in allv if est[r["case_id"]][d2] and lo2 <= est[r["case_id"]][d2] <= hi2]
    base = allv

    def probs(rs):
        n = len(rs)
        hb = sum(r["group"] != "무심장" for r in rs)
        miss = sum(outcome.get(r["case_id"]) == "아기집만(계류)" for r in rs)
        miss_y = sum(outcome.get(r["case_id"]) == "아기집만(계류)" and r["case_id"] in yolk for r in rs)
        born = sum(r["group"] == "출산" for r in rs)
        lost = sum(r["group"] == "심장후유산" for r in rs)
        return {"n": n, "sac": (hb + miss, n), "yolk": (hb + miss_y, n), "hb": (hb, n), "born": (born, born + lost),
                "chem": sum(outcome.get(r["case_id"]) == "화학적유산" for r in rs),
                "ect": sum(outcome.get(r["case_id"]) == "자궁외" for r in rs), "miss": miss}

    P_all, P_sim = probs(base), probs(sim)
    twins = {c["case_id"] for c in cases if c.get("twins") == "쌍둥이"}
    sens = [("단태·불명만 (쌍둥이 제외)", probs([r for r in sim if r["case_id"] not in twins])),
            ("5일배아만", probs([r for r in sim if r["embryo_day"] == "5"])),
            ("{d2}일 값이 우리보다 낮은 쪽만 (×0.5~×1)", probs([r for r in sim if est[r["case_id"]][d2] <= mine[d2]]))]
    # 로지스틱(두 번째 수치 날 추정값)
    xs, ys = [], []
    for r in allv:
        v = est[r["case_id"]][d2]
        if v:
            xs.append(math.log10(v))
            ys.append(1 if r["group"] != "무심장" else 0)
    lg = logit_p(xs, ys, math.log10(mine[d2]))
    xs1, ys1 = [], []
    for r in allv:
        v = est[r["case_id"]][d1]
        if v:
            xs1.append(math.log10(v))
            ys1.append(1 if r["group"] != "무심장" else 0)
    lg1 = logit_p(xs1, ys1, math.log10(mine[d1]))
    born_all = P_all["born"]
    born_sim = P_sim["born"]
    p_birth_given_hb = born_sim[0] / born_sim[1] if born_sim[1] >= 10 else born_all[0] / born_all[1]
    birth_src = "비슷한 케이스" if born_sim[1] >= 10 else "전체 케이스"

    def rate(k, n):
        lo, hi = wilson(k, n)
        return (k / n if n else float("nan")), lo, hi

    def prob_row(name, kn_sim, kn_all, extra=""):
        s, a = rate(*kn_sim), rate(*kn_all)
        return (f"<tr><td>{name}</td><td class=\"num\"><b>{pct(s[0])}</b> <span class=\"muted\">{kn_sim[0]}/{kn_sim[1]} · "
                f"{pct(s[1])}–{pct(s[2])}</span></td><td class=\"num\">{pct(a[0])} <span class=\"muted\">{kn_all[0]}/{kn_all[1]}</span></td>"
                f"<td class=\"muted\">{extra}</td></tr>")

    hb_sim = rate(*P_sim["hb"])
    p_birth = hb_sim[0] * p_birth_given_hb
    # 초음파에서 자궁 안 아기집을 확인했다면: 심장소리 ÷ (심장소리 + 아기집만 계류)
    sac_seen = "아기집" in seen
    hb_sac_sim = (P_sim["hb"][0], P_sim["hb"][0] + P_sim["miss"])
    hb_sac_all = (P_all["hb"][0], P_all["hb"][0] + P_all["miss"])
    hs = rate(*hb_sac_sim)
    p_birth_sac = hs[0] * p_birth_given_hb
    today = datetime.date.today().isoformat()
    legend = ('<div class="legend">' + f'<span><i style="background:var(--accent)"></i>심장소리 들음 (출산·유산·진행 모두)</span>'
              f'<span><i style="background:var(--low)"></i>심장소리 못 들음</span><span><i style="background:var(--fg)"></i>우리 수치</span>'
              '<span>띠: 가운데 50% · 선: 중앙값 · 세로축 로그</span></div>')

    def day_table():
        head = "".join(f"<th>{n}</th>" for _, n, _ in GROUPS)
        body = []
        for d in DAYS:
            cells = []
            for g, _, _ in GROUPS:
                v = by[g][d]
                if len(v) >= 3:
                    q = statistics.quantiles(v, n=4, method="inclusive")
                    cells.append(f'<td><b>{fmtn(q[1])}</b> <span class="muted">{fmtn(q[0])}~{fmtn(q[2])} · {len(v)}</span></td>')
                else:
                    cells.append(f'<td class="muted">{"·".join(fmtn(x) for x in sorted(v)) or "—"}</td>')
            mark = f' <b>← 우리 {fmtn(mine[d])}</b>' if d in mine else ""
            body.append(f'<tr class="{"total" if d in mine else ""}"><td>{d}일{mark}</td>{"".join(cells)}</tr>')
        return (f'<div class="tbl"><table><thead><tr><th>이식 후 (5일배 기준)</th>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>')

    def pos_table():
        rows_ = []
        for d in md:
            cells = "".join(f'<td>{pct(pctile(by[g][d], mine[d]) / 100)} <span class="muted">({len(by[g][d])})</span></td>'
                            for g, _, _ in GROUPS)
            rows_.append(f"<tr><td>{d}일 · {fmtn(mine[d])}</td>"
                         f'<td><b>{pct(pctile(hb_all[d], mine[d]) / 100)}</b> <span class="muted">({len(hb_all[d])})</span></td>{cells}</tr>')
        if dt_mine:
            cells = "".join(f'<td>{pct(sum(v > dt_mine for v in dts[g]) / len(dts[g]))} <span class="muted">({len(dts[g])})</span></td>'
                            if dts[g] else '<td class="muted">—</td>' for g, _, _ in GROUPS)
            hbd = sum((dts[g] for g in ("출산", "심장후유산", "심장(진행·미상)")), [])
            rows_.append(f"<tr><td>더블링 {dt_mine:.2f}일</td><td><b>{pct(sum(v > dt_mine for v in hbd) / len(hbd))}</b> "
                         f'<span class="muted">({len(hbd)})</span></td>{cells}</tr>')
        head = "".join(f"<th>{n}</th>" for _, n, _ in GROUPS)
        return (f'<div class="tbl"><table><thead><tr><th>우리 값</th><th>심장소리 들음 전체</th>{head}</tr></thead>'
                f'<tbody>{"".join(rows_)}</tbody></table></div>')

    def sens_table():
        body = []
        for name, P in sens:
            name = name.replace("{d2}", str(d2))
            h = rate(*P["hb"])
            b = P["born"]
            body.append(f'<tr><td>{html.escape(name)}</td><td>{P["n"]}</td><td>{pct(rate(*P["sac"])[0])}</td>'
                        f'<td><b>{pct(h[0])}</b> <span class="muted">{P["hb"][0]}/{P["hb"][1]}</span></td>'
                        f'<td class="muted">{b[0]}/{b[1]}</td></tr>')
        return ('<div class="tbl"><table><thead><tr><th>조건</th><th>케이스</th><th>아기집</th><th>심장소리</th>'
                f'<th>출산/(출산+유산)</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')

    sched_html = ""
    birth_status = {r["case_id"]: r["status"] for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    if transfer:
        table, chart, sg = schedule({r["case_id"] for r in sim}, {c for c, st in birth_status.items() if st == "출산"},
                                    miles, transfer, embryo, scan, nxt, seen)
        scan_txt = (f"<p class=\"note\">{scan.month}/{scan.day} 초음파는 <b>임신 {gw(sg)}</b>입니다. 위 표의 확인 비율은 그 주수까지 초음파를 한 번이라도 본 케이스 중 해당 항목을 확인한 비율입니다(블로그에 안 적었을 뿐 본 경우가 있어 실제보다 낮게 나올 수 있음).</p>"
                    if scan else "")
        sched_html = f"""<section>
  <h2>3. 예상 일정: 아기집·난황·심장</h2>
  <p class="note">{embryo}일배 이식일 {transfer.month}/{transfer.day} = 임신 {gw(14 + embryo)}. 다른 케이스의 첫 확인 주수를 우리 날짜로 옮겼습니다. 기준은 <b>심장소리를 듣고 출산까지 간 케이스</b>이며, 비교로 심장소리 확인 전체를 함께 둡니다.</p>
  <div class="panel">{table}{scan_txt}
  <h3>주수별 누적 확인 비율</h3>{chart}
  <p class="note">'출산 · 비슷한 수치'는 시기 기록이 있는 케이스가 4~8건뿐이라, 확률은 '출산 케이스 전체' 열을 기준으로 보는 편이 안정적입니다. 출산 케이스와 심장소리 확인 전체의 일정은 거의 같습니다.</p>
  <p class="note">'첫 확인'은 병원에 간 날이라 실제로 보이기 시작한 시점보다 늦을 수 있습니다. 심장은 초음파 깜빡임 확인도 포함합니다.</p></div>
</section>
"""

    dt_hb = statistics.median(sum((dts[g] for g in ("출산", "심장후유산", "심장(진행·미상)")), []))
    css = CSS.replace("--mid:#8fb3dc;", "--mid:#8fb3dc;--hb:#1f8a5b;").replace("--mid:#35557d;", "--mid:#6f9bd1;--hb:#4cb782;")
    return f"""<title>우리 피검 수치 위치</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · {today}</span>
  <h1>피검 수치로 본 우리 위치</h1>
  <p class="lede">블로그 후기 {len(allv)}건의 일자별 피검(hCG) 수치를 결과별로 나눠, 5일배 이식 {d1}일 {fmtn(mine[d1])} · {d2}일 {fmtn(mine[d2])}이 어디쯤인지와 비슷한 수치였던 케이스가 어떻게 됐는지 봤습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{pct(pctile(hb_all[d2], mine[d2]) / 100)}</b><span>{d2}일 수치 위치 (심장소리 들은 케이스 중 백분위)</span></div>
  <div class="kpi"><b>{f'{dt_mine:.1f}일' if dt_mine else '—'}</b><span>우리 더블링 시간 (심장소리 케이스 중앙값 {dt_hb:.1f}일)</span></div>
  <div class="kpi"><b>{pct(hs[0] if sac_seen else hb_sim[0])}</b><span>심장소리 확률 ({"아기집 확인 후, " if sac_seen else ""}비슷한 {d2}일 수치)</span></div>
  <div class="kpi"><b>{pct(p_birth_sac if sac_seen else p_birth)}</b><span>출산 확률 (추정{", 아기집 확인 후" if sac_seen else ""})</span></div>
</div>

<div class="key"><b>핵심 결과</b>
<ul>
  <li><b>{d1}일 {fmtn(mine[d1])}</b>은 심장소리를 들은 케이스 중 하위 {pct(pctile(hb_all[d1], mine[d1]) / 100)} 위치로 낮은 편이지만, 이 날 수치는 결과와 겹치는 구간이 넓어 구분력이 약합니다.</li>
  <li><b>{d2}일 {fmtn(mine[d2])}</b>은 심장소리를 들은 케이스 중 상위 {pct(1 - pctile(hb_all[d2], mine[d2]) / 100)}, 심장소리를 못 들은 케이스 중에서는 {pct(pctile(by['무심장'][d2], mine[d2]) / 100)} 위치입니다. 더블링 {f'{dt_mine:.2f}일' if dt_mine else '—'}은 심장소리 케이스 중앙값({dt_hb:.2f}일)보다 빠릅니다.</li>
  <li>{d2}일 수치가 비슷했던(×0.5~×2) {P_sim['n']}건 중 <b>{P_sim['hb'][0]}건({pct(hb_sim[0])})이 심장소리</b>를 들었습니다. 수치 하나로 본 모델 추정은 {pct(lg[0])} (95% {pct(lg[1])}–{pct(lg[2])})입니다.</li>
  <li>심장소리를 들은 뒤 출산 비율 {pct(p_birth_given_hb)}({birth_src})를 곱하면 <b>출산까지 약 {pct(p_birth)}</b>입니다.</li>
  {f"<li><b>{scan.month}/{scan.day} 초음파: {html.escape(seen)}</b>. 자궁 안 아기집을 확인해 자궁외 임신·화학적 유산 가능성이 빠졌습니다. 비슷한 수치에서 아기집을 본 {hb_sac_sim[1]}건 중 {hb_sac_sim[0]}건이 심장소리를 들어 <b>심장소리 {pct(hs[0])}, 출산까지 약 {pct(p_birth_sac)}</b>로 올라갑니다.</li>" if sac_seen and scan else ""}
  {f"<li>{nxt.month}/{nxt.day} 심장소리 예정일은 임신 {gw(14 + embryo + (nxt - transfer).days)}로, 심장소리를 들은 케이스 대부분이 이미 첫 확인을 마친 시점입니다.</li>" if nxt and transfer else ""}
</ul></div>

<section>
  <h2>1. 결과별 일자별 피검 수치와 우리 위치</h2>
  <p class="note">3일배는 −2일, 4일배는 −1일로 5일배 기준에 맞췄습니다. 측정일이 다른 케이스는 앞뒤 값 사이를 로그로 이어 그 날 값을 추정했습니다.</p>
  <div class="panel">{legend}{band_chart([("심장소리 들음", "var(--accent)", hb_all), ("심장소리 못 들음", "var(--low)", by["무심장"])], mine)}
  <h3>우리 값의 백분위 (그 그룹에서 우리보다 낮은 케이스 비율)</h3>{pos_table()}
  <p class="note">더블링 줄은 '우리보다 느린 케이스 비율'입니다. 높을수록 우리가 빠릅니다. 괄호는 케이스 수.</p></div>
</section>

<section>
  <h2>2. 비슷한 수치였던 케이스의 결과 → 확률</h2>
  <p class="note">{d2}일 추정 수치가 {fmtn(lo2)}~{fmtn(hi2)}였던 케이스 {P_sim['n']}건과, 피검 수치가 있는 전체 {P_all['n']}건을 비교했습니다.</p>
  <div class="panel"><div class="tbl"><table><thead><tr><th>단계</th><th>비슷한 케이스 (95% 구간)</th><th>전체</th><th>계산</th></tr></thead><tbody>
  {prob_row("아기집 확인", P_sim["sac"], P_all["sac"], "심장소리 + 아기집만(계류)")}
  {prob_row("난황 확인", P_sim["yolk"], P_all["yolk"], "심장소리 + 계류 중 난황 기록")}
  {prob_row("심장소리 확인", P_sim["hb"], P_all["hb"], f"모델 {pct(lg[0])} ({pct(lg[1])}–{pct(lg[2])}), {d1}일 값만으로는 {pct(lg1[0])}")}
  {prob_row("심장소리 후 출산", born_sim, born_all, "예정일 지난 케이스 중 출산 ÷ (출산+유산)")}
  {(prob_row(f"{scan.month}/{scan.day} 아기집 확인 후 → 심장소리", hb_sac_sim, hb_sac_all, "심장소리 ÷ (심장소리 + 아기집만 계류)") if sac_seen and scan else "")}
  {(f'<tr class="total"><td><b>아기집 확인 후 출산까지</b></td><td class="num"><b>{pct(p_birth_sac)}</b></td><td class="num">{pct(rate(*hb_sac_all)[0] * born_all[0] / born_all[1])}</td><td class="muted">아기집 확인 후 심장소리 × 심장소리 후 출산</td></tr>') if sac_seen and scan else ""}
  <tr class="total"><td><b>출산까지 (피검만 기준)</b></td><td class="num"><b>{pct(p_birth)}</b></td><td class="num">{pct(rate(*P_all['hb'])[0] * born_all[0] / born_all[1])}</td><td class="muted">심장소리 확률 × 심장소리 후 출산 비율({birth_src})</td></tr>
  </tbody></table></div>
  <h3>조건을 바꿔 본 경우 (비슷한 케이스 중)</h3>{sens_table()}
  <p class="note">비슷한 케이스에서 심장소리를 못 들은 경우: 계류 {P_sim['miss']}건, 화학적 유산 {P_sim['chem']}건, 자궁외 {P_sim['ect']}건.</p></div>
</section>

{sched_html}
<section>
  <h2>4. 일자별 피검 수치 (그룹별)</h2>
  <p class="note">셀: 중앙값, 회색은 가운데 50% 범위와 케이스 수. 3건 미만이면 값만 나열.</p>
  <div class="panel">{day_table()}</div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>지금까지 모은 3·4·5일배 케이스의 이식 후기와 후속 글에서 '1차 피검 90', 'hCG 1,695' 같은 수치와 그 날(이식 후 N일, N일차, 날짜)을 뽑았습니다. 2단계에서 직접 적어 둔 수치가 있으면 그것을 썼습니다.</li>
  <li>범위를 벗어나거나 순서가 맞지 않는 값과 표본으로 뽑은 케이스는 원문을 다시 보고 고쳤습니다(수동 18건).</li>
  <li>결과 그룹은 앞선 분석(심장소리 확인 여부, 출산 추적)을 그대로 씁니다. '진행 중·미상'은 아직 예정일 전이거나 출산 글을 못 찾은 케이스입니다.</li>
  <li>모델은 두 번째 수치 날의 log(hCG)로 심장소리 여부를 예측한 로지스틱 회귀, 구간은 부트스트랩 95%입니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>후기를 남긴 사람들 기준입니다. 임테기 역전을 기록한 사람이 많아 처음부터 결과가 좋은 쪽으로 기울어 있습니다.</li>
  <li>병원마다 검사 기기와 채혈 시각이 달라 수치를 그대로 비교하기 어렵습니다. 쌍둥이는 수치가 높게 나옵니다.</li>
  <li>심장소리를 못 들은 케이스와 유산 케이스는 수가 적어 확률 구간이 넓습니다.</li>
  <li>의학적 판단 근거가 아닙니다. 다음 초음파와 담당 의사의 설명이 기준입니다.</li>
</ul></section>
</div>
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mine", required=True, help="5일배 기준 경과일:수치, 예) 9:90,14:1695")
    ap.add_argument("--out", default=os.path.join(RESULTS, "my_hcg_report.html"))
    ap.add_argument("--transfer", help="이식일 YYYY-MM-DD (예상 일정 섹션)")
    ap.add_argument("--embryo", type=int, default=5)
    ap.add_argument("--scan", help="초음파 날짜 YYYY-MM-DD")
    ap.add_argument("--seen", default="", help="그 초음파 결과, 예) '아기집 확인 1.02cm (5주 5일 크기)'")
    ap.add_argument("--next", help="다음 초음파(심장소리) 날짜 YYYY-MM-DD")
    a = ap.parse_args()
    mine = {int(d): float(v) for d, v in (p.split(":") for p in a.mine.split(","))}
    rows = read_csv(os.path.join(DATA, "hcg_log.csv"))
    cases = dedupe(read_csv(CASES))
    ids = {c["case_id"] for c in cases}
    rows = [r for r in rows if r["case_id"] in ids]
    miles = read_csv(os.path.join(DATA, "milestone_log.csv"))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(rows, cases, miles, mine,
                      datetime.date.fromisoformat(a.transfer) if a.transfer else None, a.embryo,
                      datetime.date.fromisoformat(a.scan) if a.scan else None,
                      datetime.date.fromisoformat(a.next) if a.next else None, a.seen))
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
