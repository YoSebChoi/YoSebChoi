"""지금까지의 분석(역전·심장소리·출산·초음파 시기·피검·피비침)을 한 장으로 묶고 우리 상황을 대입한 종합 보고서.
개인 수치가 들어가므로 결과 파일은 커밋하지 않는다(.gitignore).

사용: python summary_report.py --mine 9:90,14:1695 --transfer 2026-09-30 --embryo 5 \
        --scan 2026-10-21 --seen '아기집 확인 1.02cm (5주 5일 크기)' --spotting brown --next 2026-11-05
"""
import argparse
import datetime
import html
import math
import os
import statistics

from cases import FAILURES, PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from birth import after_hb
from hcg import parse
from hcg_report import at, case_slope, gw, pctile
from milestones import parse as ga_of
from report import CSS, bar_chart, birth_count, birth_rows, groups, pct
from summarize import REV_COARSE, rev_day, stats, wilson

LINKS = [("임테기 역전 시점과 심장소리", "https://claude.ai/artifact/5JAzjTUNhL9h4aigvkjR9H"),
         ("심장소리 확인 후 출산까지", "https://claude.ai/artifact/Qimr2Y9tnix8JXd8QjNaG9"),
         ("아기집·난황·심장소리 확인 주수", "https://claude.ai/artifact/STPFZoyNBo8zZg6AA7SVPx"),
         ("피검 수치로 본 우리 위치", "https://claude.ai/artifact/UebN7tCCHWGb5h75hSaj7W"),
         ("임신 초기 피비침과 결과", "https://claude.ai/artifact/RhSurcJidsZ22eWxX9hzmG")]


def st(k, n):
    lo, hi = wilson(k, n)
    return {"hb": k, "n": n, "rate": k / n if n else float("nan"), "lo": lo, "hi": hi, "unk": 0}


def md(d):
    return f"{d.month}/{d.day}"


def scan_stats(ga_hb, bpm, ids_status):
    """캐시된 후기 본문에서: 비슷한 주수의 심박수 분포·결과, '주수보다 작다' 언급 케이스의 결과, 5주 4~6일 아기집 크기."""
    import glob
    import json
    import re
    from common import CACHE
    files = glob.glob(os.path.join(CACHE, "posts", "*.json"))
    if not files:
        return None
    GA = re.compile(r"([4-7])\s*주\s*차?\s*([0-6])\s*일")
    BPM = re.compile(r"(\d{2,3})\s*(?:bpm|BPM|회|비피엠)")
    SAC = re.compile(r"아기집\s*(?:크기)?\s*(?:는|은|가|이|:)?\s*(?:약\s*)?(\d(?:\.\d{1,2})?)\s*(cm|mm|센치|미리)")
    SMALL = re.compile(r"주수보다\s*(?:조금|약간|좀|살짝|며칠|하루|이틀|\d\s*일)?\s*(?:작|느리|늦|어리)|"
                       r"(?:하루|이틀|사흘|[1-6]\s*일|며칠)\s*(?:정도\s*)?(?:작|느리|늦|어리)(?:다|게|아|어|고|네|대|더)")
    bpms, sacs, small = {}, {}, set()
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        b = d.get("blog_id")
        if b not in ids_status:
            continue
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
    near = [(b, v) for (b, g), v in bpms.items() if ga_hb - 3 <= g <= ga_hb]
    vals = sorted(v for _, v in near)
    low = [b for b, v in near if v < 120]
    sac = sorted(v for (b, g), v in sacs.items() if 39 <= g <= 41)
    sm = [b for b in small if ids_status[b] in ("출산", "유지12", "유산", "미상")]
    return {"bpm_n": len(vals), "bpm_q": statistics.quantiles(vals, n=4) if len(vals) >= 4 else None,
            "bpm_pct": sum(v < bpm for v in vals) / len(vals) if vals and bpm else None,
            "low": [ids_status[b] for b in low], "sac_n": len(sac), "sac_q": statistics.quantiles(sac, n=4) if len(sac) >= 4 else None,
            "small": [ids_status[b] for b in sm]}


def build(a):
    cases = dedupe(read_csv(CASES))
    ids = {c["case_id"] for c in cases}
    allc = [c for c in cases if c.get("embryo_day") in ("3", "4", "5")]
    five = [c for c in allc if c["embryo_day"] == "5"]
    outcome = {c["case_id"]: c["outcome"] for c in cases}
    mine = {int(d): float(v) for d, v in (p.split(":") for p in a.mine.split(","))}
    d1, d2 = min(mine), max(mine)
    transfer = datetime.date.fromisoformat(a.transfer)
    scan = datetime.date.fromisoformat(a.scan) if a.scan else None
    nxt = datetime.date.fromisoformat(a.next) if a.next else None
    ga0 = 14 + a.embryo
    ga = lambda d: ga0 + (d - transfer).days
    day = lambda g: transfer + datetime.timedelta(days=g - ga0)
    today = datetime.date.today()

    # 1. 역전 → 심장소리
    g_all, g_five = dict(groups(allc, REV_COARSE)), dict(groups(five, REV_COARSE))
    early = stats([r for r in allc if rev_day(r) is not None and rev_day(r) <= 17])
    late = g_all["경과 18일 이후"]
    none = g_all["미관찰"]

    # 2. 심장소리 → 출산
    b_all = birth_rows(allc)
    bn, brate, bd = birth_count(b_all)

    # 3. 초음파 시기 (심장소리 확인 → 출산 케이스)
    birth = {r["case_id"]: r["status"] for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    miles = [r for r in read_csv(os.path.join(DATA, "milestone_log.csv")) if r["case_id"] in ids]
    born_m = [r for r in miles if birth.get(r["case_id"]) == "출산"]
    hb_m = [r for r in miles if r["outcome"] == "심장소리확인"]

    def med(rs, k):
        v = sorted(ga_of(r[k]) for r in rs if ga_of(r[k]))
        return statistics.median(v), statistics.quantiles(v, n=4, method="inclusive"), len(v)

    sched = {k: med(born_m, k) for k in ("sac", "yolk", "hb")}
    hb_by_next = None
    if nxt:
        v = [ga_of(r["hb"]) for r in born_m if ga_of(r["hb"])]
        hb_by_next = (sum(x <= ga(nxt) for x in v), len(v))

    # 4. 피검
    hrows = [r for r in read_csv(os.path.join(DATA, "hcg_log.csv")) if r["values"] and r["case_id"] in ids]
    S = statistics.median([s for r in hrows if r["group"] != "무심장" for s in [case_slope(parse(r["values"]))] if s and s > 0])
    est = {r["case_id"]: {d: at(parse(r["values"]), d, S) for d in (d1, d2)} for r in hrows}
    hbv = {d: [est[r["case_id"]][d] for r in hrows if r["group"] != "무심장" and est[r["case_id"]][d]] for d in (d1, d2)}
    nov = {d: [est[r["case_id"]][d] for r in hrows if r["group"] == "무심장" and est[r["case_id"]][d]] for d in (d1, d2)}
    dt_mine = (d2 - d1) * math.log(2) / math.log(mine[d2] / mine[d1])
    dt_hb = statistics.median([math.log(2) / s for r in hrows if r["group"] != "무심장"
                               for s in [case_slope(parse(r["values"]))] if s and s > 0])
    sim = [r for r in hrows if est[r["case_id"]][d2] and mine[d2] / 2 <= est[r["case_id"]][d2] <= mine[d2] * 2]
    sac_seen = "아기집" in (a.seen or "")
    keep = lambda r: not sac_seen or r["group"] != "무심장" or outcome.get(r["case_id"]) == "아기집만(계류)"
    sim_s = [r for r in sim if keep(r)]
    hb_sim = st(sum(r["group"] != "무심장" for r in sim_s), len(sim_s))
    adj = after_hb()
    OK = ("출산", "유지12")
    res_sim = [r for r in sim if adj.get(r["case_id"]) in OK + ("유산",)]
    born_hb_sim = st(sum(adj.get(r["case_id"]) in OK for r in res_sim), len(res_sim))
    hb_ids = [c["case_id"] for c in allc if c["outcome"] == "심장소리확인"]
    ok_all = sum(adj.get(i) in OK for i in hb_ids)
    born_hb_all = st(ok_all, ok_all + sum(adj.get(i) == "유산" for i in hb_ids))
    direct_sim = st(sum(adj.get(r["case_id"]) in OK for r in sim_s),
                    sum(adj.get(r["case_id"]) in OK + ("유산",) or r["group"] == "무심장" for r in sim_s))

    # 5. 피비침
    bl = [r for r in read_csv(os.path.join(DATA, "bleeding_log.csv")) if r["case_id"] in ids and not r["manual"].startswith("제외")]
    born_bl = [r for r in bl if r["birth"] == "출산"]
    any_pre = sum(r["pre"] != "없음" for r in born_bl) / len(born_bl)
    sp = a.spotting or "brown"
    sac_bl = [r for r in bl if r["outcome"] in ("심장소리확인", "아기집만(계류)")]

    def spot(c):
        s = [r for r in (sac_bl if sac_seen else bl) if r["pre"] == c]
        hb = sum(r["outcome"] == "심장소리확인" for r in s)
        b = sum(adj.get(r["case_id"]) in OK for r in s)
        lost = sum(adj.get(r["case_id"]) == "유산" for r in s)
        return st(hb, len(s)), st(b, b + lost), st(b, b + lost + (len(s) - hb))

    sp_hb, sp_born, sp_direct = spot(sp)
    no_hb, no_born, no_direct = spot("없음")

    # 종합 확률
    hb_lo = min(hb_sim["rate"], sp_hb["rate"])
    hb_hi = max(hb_sim["rate"], sp_hb["rate"])
    prod = [hb_sim["rate"] * born_hb_sim["rate"], hb_sim["rate"] * born_hb_all["rate"], sp_hb["rate"] * sp_born["rate"]]
    birth_lo = min([direct_sim["rate"], sp_direct["rate"]] + prod)
    birth_hi = max(prod)
    birth_mid = hb_sim["rate"] * born_hb_all["rate"]
    # 심장소리를 들은 뒤 출산할 확률(조건부): 출산 ÷ (출산 + 심장소리 후 유산)
    cond = [born_hb_sim, born_hb_all, sp_born]
    cond_lo, cond_hi = min(c["rate"] for c in cond), max(c["rate"] for c in cond)

    hb_date = datetime.date.fromisoformat(a.hb_date) if a.hb_date else None
    hb_ok = hb_date is not None
    ss = None
    if hb_ok:
        st_map = {}
        for c in allc:
            b = c["url"].split("/")[3]
            if c["outcome"] == "심장소리확인":
                v = adj.get(c["case_id"])
                st_map[b] = v or "미상"
            elif c["outcome"] in FAILURES:
                st_map.setdefault(b, c["outcome"])
        ss = scan_stats(ga(hb_date), a.bpm, st_map)

    timeline = [(transfer, f"{a.embryo}일배 이식 (임신 {gw(ga0)})", "done"),
                (transfer + datetime.timedelta(days=d1), f"1차 피검 {mine[d1]:,.0f}", "done"),
                (transfer + datetime.timedelta(days=d2), f"2차 피검 {mine[d2]:,.0f} (더블링 {dt_mine:.1f}일)", "done")]
    if scan:
        timeline.append((scan, f"초음파 {gw(ga(scan))}: {a.seen}", "done"))
    if a.spotting:
        timeline.append((today, {"brown": "갈색 소량 피비침"}.get(a.spotting, a.spotting), "note"))
    if hb_ok:
        timeline.append((hb_date, f"초음파 {gw(ga(hb_date))}{f' ({a.hb_place})' if a.hb_place else ''}: 심장소리 확인" + (f" {a.bpm}bpm" if a.bpm else "")
                         + (f", 아기 크기 {a.crl}cm" if a.crl else "") + (f" (측정 기준 {a.crl_ga})" if a.crl_ga else ""), "done"))
    if nxt and not (hb_ok and nxt <= hb_date):
        timeline.append((nxt, f"{'다음 초음파 · 심장소리 재확인' if hb_ok else '심장소리 예정'} (임신 {gw(ga(nxt))})", "next"))
    tl = "".join(f'<li class="{k}"><b>{"최근" if k == "note" else md(d)}</b> {html.escape(t)}</li>' for d, t, k in sorted(timeline, key=lambda x: x[0]))

    def bar(name, lo, hi, txt):
        return (f'<div class="sb"><span>{name}</span><div class="track"><i style="width:{lo * 100:.1f}%"></i>'
                f'<i class="rng" style="left:{lo * 100:.1f}%;width:{(hi - lo) * 100:.1f}%"></i></div><b>{txt}</b></div>')
    if hb_ok:
        stage = (bar("아기집", 1, 1, "확인됨") + bar("심장소리", 1, 1, "확인됨")
                 + bar("출산까지", cond_lo, cond_hi, f"{pct(cond_lo, 0)}~{pct(cond_hi, 0)}"))
    else:
        stage = (bar("아기집", 1 if sac_seen else 0, 1 if sac_seen else 0, "확인됨" if sac_seen else "—")
                 + bar("심장소리", hb_lo, hb_hi, f"{pct(hb_lo, 0)}~{pct(hb_hi, 0)}")
                 + bar("출산까지", birth_lo, birth_hi, f"{pct(birth_lo, 0)}~{pct(birth_hi, 0)}")
                 + '<p class="note" style="margin:8px 0 0">심장소리를 들은 뒤라면</p>'
                 + bar("→ 출산", cond_lo, cond_hi, f"{pct(cond_lo, 0)}~{pct(cond_hi, 0)}"))

    def counts(lst):
        c = {k: lst.count(k) for k in ("출산", "유지12", "유산", "미상")}
        return f"출산 {c['출산']} · 12주+ 유지 {c['유지12']} · 유산 {c['유산']} · 미상 {c['미상']}"

    scan_sec = ""
    if hb_ok and ss:
        ok_small = sum(x in ("출산", "유지12") for x in ss["small"])
        res_small = ok_small + ss["small"].count("유산")
        catch_html = ""
        try:
            from catchup import analyze, rate
            cu = analyze(ga(hb_date), float(a.crl) * 10 if a.crl else 99, a.bpm or 999)
        except Exception:
            cu = None
        if cu:
            gok, gn = rate(cu["group"])
            sok, sn = rate(cu["similar_res"])
            def traj(s_):
                return " → ".join(f"{gw(g)} " + " · ".join(x for x in ((f"{c:.1f}mm" if c and not (g >= 49 and c < 4) else ""), (f"{b_}bpm" if b_ else "")) if x)
                                  for g, c, b_, _ in s_["traj"])
            lab = {"출산": "출산", "유지12": "12주+ 유지", "유산": "유산", "미상": "진행 중·미상"}
            rows_ = "".join(f'<li><b>{lab[s_["outcome"]]}</b> · {traj(s_)} · <a href="{s_["traj"][0][3]}">글</a></li>' for s_ in cu["similar"])
            catch_html = f"""<div class="cmp"><h3>주수보다 작거나 느렸던 케이스는 따라잡았나</h3>
  <p>6~8주에 아기 크기나 심박수가 같은 주수 후기의 아래쪽 25%였거나 '주수보다 작다'는 말을 들은 심장소리 케이스 <b>{cu['group_n']}건</b> 중, 결과가 나온 {gn}건에서 <b>{gok}건({pct(gok / gn, 0) if gn else '—'})</b>이 출산하거나 12주 넘게 유지했습니다 (출산 {cu['group']['출산']} · 12주+ 유지 {cu['group']['유지12']} · 유산 {cu['group']['유산']} · 진행 중·미상 {cu['group']['미상']}). 심장소리 확인 전체(약 93%)와 비슷합니다.</p></div>
  <div class="cmp"><h3>우리와 비슷한 케이스 (이식일 기준 {gw(ga(hb_date) - 1)}~{gw(ga(hb_date) + 2)}, 크기 {float(a.crl) * 12:.1f}mm 이하 또는 심박수 {a.bpm + 7} 이하)</h3>
  <p>{len(cu['similar'])}건 중 결과가 나온 {sn}건에서 <b>{sok}건 출산</b>({pct(sok / sn, 0) if sn else '—'}), 나머지는 진행 중·미상. 표본이 매우 작아 비율보다 흐름을 보세요: 잘 된 케이스는 1주 뒤 크기 +8~10mm, 심박수 +40~50bpm이었고, 유산 케이스는 7주에 심박수가 떨어졌거나, 아기 크기·심박수는 정상이었지만 아기집이 주수보다 계속 작았습니다(우리 아기집은 날짜와 같은 크기).</p>
  <ul class="note" style="margin:4px 0 0;padding-left:18px;display:grid;gap:4px">{rows_}</ul></div>"""
        scan_sec = f"""<section>
  <h2>{md(hb_date)} 초음파 결과를 후기와 비교</h2>
  <div class="panel">
  <div class="cmp"><h3>심박수</h3><p>우리: <b>{a.bpm}bpm</b> ({gw(ga(hb_date))})</p><p class="note">{gw(ga(hb_date) - 3)}~{gw(ga(hb_date))} 심박수 {ss['bpm_n']}건: 중앙값 {ss['bpm_q'][1]:.0f}, 가운데 50% {ss['bpm_q'][0]:.0f}~{ss['bpm_q'][2]:.0f}bpm. 우리보다 낮은 케이스 {pct(ss['bpm_pct'], 0)}.<br>120 미만 {len(ss['low'])}건의 결과: {counts(ss['low'])}</p></div>
  <div class="cmp"><h3>아기 크기</h3><p>우리: <b>{a.crl}cm</b> (측정 기준 {a.crl_ga}, 날짜보다 {ga(hb_date) - ga_of(a.crl_ga.replace('주', 'w').replace('일', 'd').replace(' ', '')) if a.crl_ga else ''}일 작음)</p><p class="note">'주수보다 작다' 언급이 있던 심장소리 케이스 {len(ss['small'])}건: {counts(ss['small'])} → 결과가 나온 {res_small}건 중 {ok_small}건({pct(ok_small / res_small, 0) if res_small else '—'}) 출산·유지. 이 시기 크기 측정은 앞뒤 3~5일 오차가 흔함.</p></div>
  {f'<div class="cmp"><h3>아기집 ({md(scan)})</h3><p>우리: <b>1.02cm</b> ({gw(ga(scan))}, 날짜와 같은 크기)</p><p class="note">5주 4~6일 아기집 크기 {ss['sac_n']}건: 중앙값 {ss['sac_q'][1]:.2f}cm, 가운데 50% {ss['sac_q'][0]:.2f}~{ss['sac_q'][2]:.2f}cm → 중간 정도</p></div>' if scan and ss['sac_q'] else ""}

  {catch_html}
  <p class="note">심박수는 6주 무렵 100~120에서 시작해 9주쯤 150~170까지 빠르게 오릅니다. 일부 연구는 6주 3일~7주에 120 미만을 '조금 느린 편'으로 보지만 대부분 정상 진행됩니다. 다음 초음파에서 심박수가 오르고 크기가 1주에 약 0.5~0.7cm씩 자라는지가 가장 확실한 확인입니다. 후기 표본은 수십 건 이하라 참고용입니다.</p></div>
</section>
"""
    css = CSS + (".tl{list-style:none;margin:0;padding:0;display:grid;gap:6px}.tl li{padding:6px 10px;border-left:3px solid var(--line);"
                 "background:var(--panel);border-radius:0 8px 8px 0}.tl li.done{border-color:var(--accent)}.tl li.note{border-color:var(--low)}"
                 ".tl li.next{border-color:var(--fg);border-left-style:dashed}.links a{color:var(--accent)}"
                 ".sb{display:grid;grid-template-columns:72px 1fr 92px;gap:10px;align-items:center}.sb b{font:600 14px var(--mono);text-align:right}"
                 ".track{position:relative;height:14px;border-radius:7px;background:var(--grid);overflow:hidden}"
                 ".cmp{border-top:1px solid var(--line);padding-top:8px}.cmp h3{margin:0 0 4px}.cmp p{margin:0 0 4px}"
                 ".track i{position:absolute;top:0;bottom:0;left:0;background:var(--accent)}.track i.rng{background:var(--accent);opacity:.4}")
    q = lambda k: sched[k]
    return f"""<title>시험관 후기 종합</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · 종합 · {today.isoformat()}</span>
  <h1>지금까지의 분석과 우리 위치</h1>
  <p class="lede">네이버 블로그 시험관 후기 {len(allc)}건(3·4·5일배)을 모아 임테기 역전, 피검, 초음파 시기, 피비침, 출산까지 따라간 결과를 한 장으로 묶고, 우리 상황을 대입했습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{"확인" if sac_seen else "—"}</b><span>자궁 안 아기집 ({md(scan) if scan else ""})</span></div>
  {f'<div class="kpi"><b>확인</b><span>심장소리 ({md(hb_date)}, {a.bpm}bpm)</span></div>' if hb_ok else f'<div class="kpi"><b>{pct(hb_lo, 0)}~{pct(hb_hi, 0)}</b><span>심장소리 들을 확률</span></div>'}
  {f'<div class="kpi"><b>{pct(cond_lo, 0)}~{pct(cond_hi, 0)}</b><span>출산까지 확률 (심장소리 확인 후, 중심 약 {pct(born_hb_all["rate"], 0)})</span></div>' if hb_ok else f'<div class="kpi"><b>{pct(birth_lo, 0)}~{pct(birth_hi, 0)}</b><span>출산까지 확률 (중심 약 {pct(birth_mid, 0)})</span></div>'}
  {f'<div class="kpi"><b>{a.crl}cm</b><span>아기 크기 (측정 기준 {a.crl_ga})</span></div>' if hb_ok and a.crl else f'<div class="kpi"><b>{pct(cond_lo, 0)}~{pct(cond_hi, 0)}</b><span>심장소리를 들은 뒤 출산할 확률{f" ({md(nxt)} 확인 시)" if nxt else ""}</span></div>'}
</div>

<div class="key"><b>한 줄 요약</b>
<ul>
  <li>피검 2차 수치와 더블링은 심장소리를 들은 케이스 기준으로도 좋은 편이고, 자궁 안 아기집을 이미 확인했습니다. <b>갈색 소량 피비침은 흔했고 결과와 뚜렷한 관계가 없었습니다.</b></li>
{"" if hb_ok else f"""<li>비슷한 케이스들은 <b>심장소리 {pct(hb_lo, 0)}~{pct(hb_hi, 0)}</b>, <b>출산 {pct(birth_lo, 0)}~{pct(birth_hi, 0)}</b>(가운데 약 {pct(birth_mid, 0)})였습니다. <b>심장소리를 들은 뒤에는 출산 {pct(cond_lo, 0)}~{pct(cond_hi, 0)}</b>(전체 기준 {pct(born_hb_all['rate'], 0)})로 올라갑니다.</li>"""}
  {f"<li><b>{md(hb_date)}({gw(ga(hb_date))}) 심장소리 확인.</b> 이제 출산 확률은 심장소리를 들은 케이스 기준 <b>{pct(cond_lo, 0)}~{pct(cond_hi, 0)}</b>(전체 {pct(born_hb_all['rate'], 0)})입니다. 심장소리 후 유산은 주로 7~10주라 10주를 넘기면 더 올라갑니다.</li><li>심박수 {a.bpm}bpm은 같은 시기 후기 중앙값보다 조금 낮고, 아기 크기는 날짜보다 며칠 작게 측정됐지만 둘 다 흔한 범위입니다(아래 비교). {f"{md(nxt)}({gw(ga(nxt))}) 초음파에서" if nxt and nxt > hb_date else "다음 초음파에서"} 심박수 상승과 크기 증가를 확인하면 됩니다.</li>" if hb_ok else ""}
  {"" if hb_ok else f"<li>{md(nxt)}({gw(ga(nxt))})은 출산 케이스의 {pct(hb_by_next[0] / hb_by_next[1], 0)}가 이미 심장을 처음 확인한 시점이라, 심장소리를 확인하기 충분한 날짜입니다.</li>" if hb_by_next and not hb_ok else ""}
</ul></div>

<div class="two">
<section><h2>우리 경과</h2><ul class="tl">{tl}</ul></section>
<section><h2>우리 확률 단계별</h2><div class="panel">{stage}
<p class="note">진한 막대 = 범위의 아래쪽, 옅은 부분 = 범위. 출산은 출산 글이 있거나 12주 이상 유지가 확인된 케이스를 함께 센 값입니다. 범위는 바로 센 값(출산·유지 ÷ 결과가 나온 케이스)과 단계별 곱셈 값입니다.</p></div></section>
</div>

{scan_sec}
<section>
  <h2>1. 임테기 첫 역전 시기와 심장소리</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>첫 역전 (5일배 기준)</th><th>3·4·5일배 전체</th><th>5일배만</th></tr></thead><tbody>
  {"".join(f'<tr class="{"low" if k in ("경과 18일 이후", "미관찰") else ""}"><td>{k.replace("경과 ", "")}</td><td><b>{pct(g_all[k]["rate"], 0)}</b> <span class="muted">{g_all[k]["hb"]}/{g_all[k]["n"]}</span></td><td><b>{pct(g_five[k]["rate"], 0)}</b> <span class="muted">{g_five[k]["hb"]}/{g_five[k]["n"]}</span></td></tr>' for k in [l for l, _ in REV_COARSE] + ["미관찰"])}
  </tbody></table></div>
  <p class="note">17일 이내 역전은 {pct(early['rate'], 1)}({early['hb']}/{early['n']}), 18일 이후 {pct(late['rate'], 0)}, 역전 미관찰 {pct(none['rate'], 0)}. 비율 = 심장소리 ÷ (심장소리 + 계류·화유·자궁외).</p></div>
</section>

<section>
  <h2>2. 심장소리 후 출산</h2>
  <div class="panel"><p>예정일이 지나 결과가 확인된 {bd}건 중 <b>{pct(brate, 1)} ({bn['출산']}건) 출산</b>, 심장소리 후 유산 {bn['유산']}건(대부분 7~10주 계류). 5일배는 대부분 아직 예정일 전이라 이 비율은 주로 3·4일배 기준입니다.</p>
  <p>유산은 일찍 확정되고 출산은 예정일 뒤에 확정되므로, 예정일 전이라도 <b>12주 이상 유지가 확인된 케이스를 함께 세면 {pct(born_hb_all['rate'], 0)}</b>({born_hb_all['hb']}/{born_hb_all['n']})입니다. 아래 확률은 이 기준을 씁니다.</p></div>
</section>

<section>
  <h2>3. 아기집·난황·심장 첫 확인 시기 (출산 케이스 기준, 우리 날짜로)</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>항목</th><th>중앙값</th><th>가운데 50%</th><th>건수</th></tr></thead><tbody>
  {"".join(f'<tr><td>{n}</td><td><b>{gw(round(q(k)[0]))} · {md(day(round(q(k)[0])))}</b></td><td>{md(day(round(q(k)[1][0])))}~{md(day(round(q(k)[1][2])))}</td><td>{q(k)[2]}</td></tr>' for k, n in (("sac", "아기집"), ("yolk", "난황"), ("hb", "심장")))}
  </tbody></table></div>
  <p class="note">첫 역전 시기(17일 이내)에 따른 차이는 거의 없었습니다. '첫 확인'은 병원에 간 날이라 실제 보이기 시작한 시점보다 늦을 수 있습니다.</p></div>
</section>

<section>
  <h2>4. 피검 수치</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>우리 값</th><th>심장소리 들은 케이스 중 위치</th><th>못 들은 케이스 중 위치</th></tr></thead><tbody>
  <tr><td>{d1}일 {mine[d1]:,.0f}</td><td>{pct(pctile(hbv[d1], mine[d1]) / 100, 0)}</td><td>{pct(pctile(nov[d1], mine[d1]) / 100, 0)}</td></tr>
  <tr><td>{d2}일 {mine[d2]:,.0f}</td><td><b>{pct(pctile(hbv[d2], mine[d2]) / 100, 0)}</b></td><td><b>{pct(pctile(nov[d2], mine[d2]) / 100, 0)}</b></td></tr>
  <tr><td>더블링 {dt_mine:.2f}일</td><td colspan="2">심장소리 케이스 중앙값 {dt_hb:.2f}일보다 빠름</td></tr>
  </tbody></table></div>
  <p class="note">{d2}일 수치가 비슷했던(×0.5~×2) {len(sim)}건 기준: {"아기집 확인 후 " if sac_seen else ""}심장소리 {pct(hb_sim['rate'], 0)} ({hb_sim['hb']}/{hb_sim['n']}), 심장소리 후 출산 {pct(born_hb_sim['rate'], 0)} ({born_hb_sim['hb']}/{born_hb_sim['n']}, 전체 기준 {pct(born_hb_all['rate'], 0)}). {d1}일 값은 결과와 겹치는 구간이 넓어 구분력이 약합니다.</p></div>
</section>

<section>
  <h2>5. 임신 초기 피비침</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>{"아기집 확인 케이스, " if sac_seen else ""}심장 확인 전 피비침</th><th>심장소리</th><th>심장소리 후 출산</th><th>출산까지 (직접)</th></tr></thead><tbody>
  <tr><td><b>갈색 소량</b></td><td><b>{pct(sp_hb['rate'], 0)}</b> <span class="muted">{sp_hb['hb']}/{sp_hb['n']}</span></td><td>{pct(sp_born['rate'], 0)} <span class="muted">{sp_born['hb']}/{sp_born['n']}</span></td><td>{pct(sp_direct['rate'], 0)} <span class="muted">{sp_direct['hb']}/{sp_direct['n']}</span></td></tr>
  <tr><td>언급 없음</td><td>{pct(no_hb['rate'], 0)} <span class="muted">{no_hb['hb']}/{no_hb['n']}</span></td><td>{pct(no_born['rate'], 0)} <span class="muted">{no_born['hb']}/{no_born['n']}</span></td><td>{pct(no_direct['rate'], 0)} <span class="muted">{no_direct['hb']}/{no_direct['n']}</span></td></tr>
  </tbody></table></div>
  <p class="note">출산한 케이스의 {pct(any_pre, 0)}가 심장 확인 전 피비침을 적었습니다. 빨간 피·많은 양, 덩어리, 심한 복통이 있으면 병원에 바로 연락하는 것이 기준입니다.</p></div>
</section>

<section>
  <h2>6. 우리 확률 종합</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>근거</th><th>심장소리</th><th>출산까지 (지금부터)</th><th>심장소리 들은 뒤 출산</th></tr></thead><tbody>
  <tr><td>피검 비슷 + 아기집 확인</td><td><b>{pct(hb_sim['rate'], 0)}</b></td><td>{pct(hb_sim['rate'] * born_hb_sim['rate'], 0)}~{pct(hb_sim['rate'] * born_hb_all['rate'], 0)} (곱셈) · {pct(direct_sim['rate'], 0)} (직접)</td><td><b>{pct(born_hb_sim['rate'], 0)}</b> <span class="muted">{born_hb_sim['hb']}/{born_hb_sim['n']}</span></td></tr>
  <tr><td>심장소리 확인 전체 (수치 무관, 12주 이상 유지 포함)</td><td>—</td><td>—</td><td><b>{pct(born_hb_all['rate'], 0)}</b> <span class="muted">{born_hb_all['hb']}/{born_hb_all['n']}</span></td></tr>
  <tr><td>갈색 소량 피비침 + 아기집 확인</td><td><b>{pct(sp_hb['rate'], 0)}</b></td><td>{pct(sp_hb['rate'] * sp_born['rate'], 0)} (곱셈) · {pct(sp_direct['rate'], 0)} (직접)</td><td><b>{pct(sp_born['rate'], 0)}</b> <span class="muted">{sp_born['hb']}/{sp_born['n']}</span></td></tr>
  <tr class="total"><td><b>종합</b></td><td><b>{pct(hb_lo, 0)}~{pct(hb_hi, 0)}</b></td><td><b>{pct(birth_lo, 0)}~{pct(birth_hi, 0)}</b> (중심 약 {pct(birth_mid, 0)})</td><td><b>{pct(cond_lo, 0)}~{pct(cond_hi, 0)}</b> (중심 약 {pct(born_hb_all['rate'], 0)})</td></tr>
  </tbody></table></div>
  <p class="note">두 근거(피검·피비침)를 동시에 만족하는 케이스는 몇 건뿐이라 따로 계산해 범위로 묶었습니다. 출산 범위가 넓은 이유는 출산 결과까지 확인된 케이스가 적기 때문입니다. '심장소리 들은 뒤 출산' = (출산 + 12주 이상 유지) ÷ (그 + 심장소리 후 유산). 심장소리 후 유산은 대부분 7~10주라 12주를 넘긴 케이스를 함께 셌습니다(12주 이후 유산도 드물게 있어 약간 높게 잡힐 수 있음).</p></div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>출산 확률은 출산 글이 확인된 케이스와 출산 글은 없지만 12주 이상까지 유지가 확인된 케이스를 '출산(유지)'로 함께 셉니다. 예정일이 지난 케이스만 세면 결과가 일찍 확정되는 유산만 들어가 낮게 치우치기 때문입니다.</li>
  <li>네이버 블로그에서 시험관 이식 후기({len(allc)}건)를 모아 배아 일수, 이식일, 첫 역전 날, 결과(심장소리·계류·화유·자궁외)를 기록했습니다. 3일배는 −2일, 4일배는 −1일로 5일배 기준에 맞췄습니다.</li>
  <li>같은 블로그의 이후 글(제목·본문)로 출산 여부, 아기집·난황·심장 첫 확인 주수, 피검 수치, 피비침을 뽑고, 어긋난 값은 원문을 다시 보고 고쳤습니다.</li>
  <li>비율의 95% 구간은 Wilson 방식입니다. 원문은 저장하지 않고 블로그 주소와 판정 결과만 남겼습니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>후기를 남긴 사람 기준이라 좋은 결과 쪽으로 기울어 있을 수 있습니다. 블로그에 적지 않은 내용은 '없음'으로 잡힙니다.</li>
  <li>병원마다 피검 기기와 초음파 일정이 달라 수치·시기를 그대로 비교하기 어렵습니다.</li>
  <li>의학적 판단 근거가 아닙니다. 담당 의사의 설명이 기준입니다.</li>
</ul></section>
</div>

<section><h2>자세한 보고서</h2><ul class="links note">{"".join(f'<li><a href="{u}">{html.escape(n)}</a></li>' for n, u in LINKS)}</ul></section>
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mine", required=True)
    ap.add_argument("--transfer", required=True)
    ap.add_argument("--embryo", type=int, default=5)
    ap.add_argument("--scan")
    ap.add_argument("--seen", default="")
    ap.add_argument("--spotting", default="")
    ap.add_argument("--next")
    ap.add_argument("--hb-date", help="심장소리 확인 날짜 YYYY-MM-DD")
    ap.add_argument("--bpm", type=int)
    ap.add_argument("--hb-place", default="", help="심장소리 확인한 곳, 예) 서브병원")
    ap.add_argument("--crl", help="아기 크기 cm, 예) 0.62")
    ap.add_argument("--crl-ga", help="측정 기준 주수, 예) '6주 3일'")
    ap.add_argument("--out", default=os.path.join(RESULTS, "my_summary_report.html"))
    a = ap.parse_args()
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a))
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
