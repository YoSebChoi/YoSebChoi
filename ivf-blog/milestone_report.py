"""data/milestone_log.csv → results/milestone_report.html (첫 역전 시기별 아기집·난황·심장소리 첫 확인 주수, report.py와 같은 양식)
사용: python milestone_report.py
"""
import datetime
import html
import os
import statistics

from cases import PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from milestones import parse
from report import CSS, LOW, short
from summarize import REV_COARSE, rev_day

ITEMS = [("sac", "아기집", "var(--mid)"), ("yolk", "난황", "var(--accent)"), ("hb", "심장소리", "var(--hb)")]
AX0, AX1 = 28, 63  # 4주 0일 ~ 9주 0일


def wk(d):
    if d is None:
        return "—"
    d = round(d)
    return f"{d // 7}주 {d % 7}일"


def q(vals):
    """중앙값과 사분위(25%·75%)."""
    if not vals:
        return None
    v = sorted(vals)
    if len(v) == 1:
        return v[0], v[0], v[0]
    qs = statistics.quantiles(v, n=4, method="inclusive")
    return qs[0], statistics.median(v), qs[2]


def rows_of(log, cases):
    ids = {c["case_id"] for c in cases}
    return [r for r in log if r["case_id"] in ids]


def grouped(rows):
    out = [(label, [r for r in rows if rev_day(r) is not None and f(rev_day(r))]) for label, f in REV_COARSE]
    return out + [("미관찰", [r for r in rows if r.get("reversal_day") == "미관찰"])]


def vals(rows, k):
    return [parse(r[k]) for r in rows if parse(r[k]) is not None]


def range_chart(groups, title):
    """그룹마다 아기집·난황·심장소리 세 줄: 점 = 중앙값, 막대 = 사분위 범위(가운데 50%)."""
    w, left, right, top, sub = 680, 118, 24, 26, 15
    row = sub * 3 + 16
    h = top + row * len(groups) + 30
    plot = w - left - right
    x = lambda d: left + plot * (min(max(d, AX0), AX1) - AX0) / (AX1 - AX0)
    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}" class="chart">']
    for wks in range(4, 10):
        d = wks * 7
        p.append(f'<line x1="{x(d):.1f}" y1="{top - 8}" x2="{x(d):.1f}" y2="{h - 24}" class="grid"/>'
                 f'<text x="{x(d):.1f}" y="{h - 8}" class="tick" text-anchor="middle">{wks}주</text>')
    for i, (label, rs) in enumerate(groups):
        y0 = top + i * row
        p.append(f'<text x="{left - 12}" y="{y0 + row / 2 - 2}" class="lab" text-anchor="end">{html.escape(short(label))}</text>')
        for j, (k, name, color) in enumerate(ITEMS):
            v = q(vals(rs, k))
            y = y0 + 6 + j * sub
            if not v:
                continue
            lo, md, hi = v
            tip = f"{short(label)} {name}: 중앙값 {wk(md)}, 가운데 50% {wk(lo)}~{wk(hi)} (n={len(vals(rs, k))})"
            p.append(f'<g class="row"><title>{html.escape(tip)}</title>'
                     f'<rect x="{x(lo):.1f}" y="{y}" width="{max(x(hi) - x(lo), 3):.1f}" height="9" rx="4" style="fill:{color};opacity:.45"/>'
                     f'<circle cx="{x(md):.1f}" cy="{y + 4.5}" r="5" style="fill:{color};stroke:var(--panel);stroke-width:1.5"/></g>')
    p.append("</svg>")
    return "".join(p)


def cell(rs, k):
    v = q(vals(rs, k))
    if not v:
        return '<td class="muted">—</td>'
    return f'<td><b>{wk(v[1])}</b> <span class="muted">{wk(v[0])}~{wk(v[2])} · {len(vals(rs, k))}</span></td>'


def table(groups, first="첫 역전"):
    body = []
    for label, rs in groups:
        body.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td><td>{len(rs)}</td>'
                    + "".join(cell(rs, k) for k, _, _ in ITEMS) + "</tr>")
    head = "".join(f"<th>{n}</th>" for _, n, _ in ITEMS)
    return (f'<div class="tbl"><table><thead><tr><th>{first}</th><th>케이스</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def cumulative(groups):
    cuts = [(42, "6주 0일"), (45, "6주 3일"), (49, "7주 0일"), (52, "7주 3일"), (56, "8주 0일")]
    body = []
    for label, rs in groups:
        v = vals(rs, "hb")
        if not v:
            continue
        body.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td><td>{len(v)}</td>'
                    + "".join(f'<td>{sum(x <= c for x in v) / len(v) * 100:.0f}%</td>' for c, _ in cuts) + "</tr>")
    return ('<div class="tbl"><table><thead><tr><th>첫 역전</th><th>심장소리 시기 확인</th>'
            + "".join(f"<th>{n}까지</th>" for _, n in cuts) + f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def short_wk(d):
    return "—" if d is None else f"{round(d) // 7}w{round(d) % 7}d"


def matrix(hb):
    """첫 역전 시기 × 배아 일수: 칸마다 아기집 / 난황 / 심장소리 중앙값."""
    days = [("5", "5일배"), ("4", "4일배 (−1일)"), ("3", "3일배 (−2일)")]
    body = []
    for label, rs in grouped(hb):
        cells = []
        for d, _ in days:
            sub = [r for r in rs if r["embryo_day"] == d]
            meds = [q(vals(sub, k)) for k, _, _ in ITEMS]
            n = len(vals(sub, "hb"))
            cells.append('<td class="mono">' + " · ".join(short_wk(m[1] if m else None) for m in meds)
                         + f' <span class="muted">({n})</span></td>' if sub else '<td class="muted">—</td>')
        body.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td>{"".join(cells)}</tr>')
    return ('<div class="tbl"><table><thead><tr><th>첫 역전 (5일배 기준)</th>'
            + "".join(f"<th>{n}</th>" for _, n in days) + f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def build(cases, log):
    allc = [c for c in cases if c.get("embryo_day") in ("3", "4", "5")]
    hb_cases = [c for c in allc if c["outcome"] == "심장소리확인"]
    hb = rows_of(log, hb_cases)
    five = [r for r in hb if r["embryo_day"] == "5"]
    miss = rows_of(log, [c for c in allc if c["outcome"] == "아기집만(계류)"])
    g_all, g_five = grouped(hb), grouped(five)
    med = {k: q(vals(hb, k)) for k, _, _ in ITEMS}
    by = dict(g_all)
    early = [r for r in hb if rev_day(r) is not None and rev_day(r) <= 17]
    late = [r for r in hb if rev_day(r) is not None and rev_day(r) >= 18]
    none = q(vals(by["미관찰"], "hb"))
    me, ml = q(vals(early, "hb")), q(vals(late, "hb"))
    legend = '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{n}</span>' for _, n, c in ITEMS) + \
             '<span>점: 중앙값 · 막대: 가운데 50%</span></div>'
    today = datetime.date.today().isoformat()
    css = CSS.replace("--mid:#8fb3dc;", "--mid:#8fb3dc;--hb:#1f8a5b;").replace("--mid:#35557d;", "--mid:#6f9bd1;--hb:#4cb782;") \
        + ".mono{font-family:var(--mono);font-size:13px;white-space:nowrap}"
    return f"""<title>아기집·난황·심장소리 시기</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{css}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · {today}</span>
  <h1>역전 시기별 아기집·난황·심장소리 확인 주수</h1>
  <p class="lede">심장소리까지 확인한 케이스에서 초음파로 아기집, 난황, 심장소리를 처음 확인한 임신 주수를 첫 역전 시기별로 비교했습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{len(hb)}</b><span>심장소리 확인 케이스</span></div>
  <div class="kpi"><b>{wk(med['sac'][1])}</b><span>아기집 첫 확인 (중앙값, {len(vals(hb, 'sac'))}건)</span></div>
  <div class="kpi"><b>{wk(med['yolk'][1])}</b><span>난황 첫 확인 (중앙값, {len(vals(hb, 'yolk'))}건)</span></div>
  <div class="kpi"><b>{wk(med['hb'][1])}</b><span>심장소리 첫 확인 (중앙값, {len(vals(hb, 'hb'))}건)</span></div>
</div>

<div class="key"><b>핵심 결과</b>
<ul>
  <li>심장소리까지 간 케이스는 보통 <b>아기집 {wk(med['sac'][1])}</b> → <b>난황 {wk(med['yolk'][1])}</b> → <b>심장소리 {wk(med['hb'][1])}</b> 순서로 확인했습니다 (임신 주수, 마지막 생리일 기준).</li>
  <li>첫 역전이 <b>경과 17일 이내</b>면 시기(13일 이전·14~15일·16~17일)와 상관없이 아기집·난황·심장소리 확인 주수가 거의 같습니다. 심장소리 중앙값 <b>{wk(me[1]) if me else '—'}</b>.</li>
  <li>첫 역전이 <b>18일 이후</b>면 심장소리 중앙값이 <b>{wk(ml[1]) if ml else '—'}</b>({len(vals(late, 'hb'))}건), 역전 미관찰은 <b>{wk(none[1]) if none else '—'}</b>로 며칠 늦습니다. 표본이 적어 참고용입니다.</li>
  <li>임신 주수는 배아 일수와 상관없이 같은 축이라 3·4·5일배를 그대로 비교할 수 있습니다.</li>
</ul></div>

<section>
  <h2>1. 3·4·5일배 전체</h2>
  <p class="note">첫 역전은 5일배 기준 환산(3일배 −2일, 4일배 −1일). 셀: 중앙값, 회색은 가운데 50% 범위와 건수.</p>
  <div class="panel">{legend}{range_chart(g_all, "3·4·5일배 첫 역전 시기별 아기집·난황·심장소리 확인 주수")}
  <h3>시기별 상세</h3>{table(g_all)}
  <h3>주수별 심장소리 확인 누적 비율</h3>{cumulative(g_all)}</div>
</section>

<section>
  <h2>2. 5일배아만</h2>
  <p class="note">환산 없이 실제 경과일로 나눈 첫 역전 시기입니다.</p>
  <div class="panel">{legend}{range_chart(g_five, "5일배 첫 역전 시기별 아기집·난황·심장소리 확인 주수")}
  <h3>시기별 상세</h3>{table(g_five)}
  <h3>주수별 심장소리 확인 누적 비율</h3>{cumulative(g_five)}</div>
</section>

<section>
  <h2>3. 배아 일수별 비교</h2>
  <div class="panel">{table([(f"{d}일배", [r for r in hb if r['embryo_day'] == d]) for d in ("5", "4", "3")], "배아")}
  <h3>배아 일수 × 첫 역전 시기</h3>{matrix(hb)}
  <p class="note">칸: 아기집 · 난황 · 심장소리 첫 확인 중앙값(예: 6w2d = 6주 2일), 괄호는 심장소리 시기가 확인된 건수.</p>
  <p class="note">이식일은 5일배 2주 5일, 4일배 2주 4일, 3일배 2주 3일입니다. 심장소리 주수에서 이 값을 빼면 이식 후 경과일이 됩니다.</p></div>
</section>

<section>
  <h2>4. 아기집만 보고 계류된 케이스와 비교</h2>
  <div class="panel">{table([("심장소리 확인", hb), ("아기집만(계류)", miss)], "결과")}
  <p class="note">계류 케이스는 {len(miss)}건뿐이라 참고용입니다. 아기집·난황을 처음 본 시기 자체는 큰 차이가 없고, 이후 심장소리를 듣지 못한 경우입니다.</p></div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>심장소리 확인·계류 케이스의 이식 후기와, 같은 블로그에서 이식 후 70일 안에 쓴 초음파·주수 관련 글을 읽었습니다.</li>
  <li>'아기집', '난황', '심장소리·심박' 문장과 가장 가까운 임신 주수(예: 6주 2일)를 그 항목의 확인 시기로 보고, 케이스마다 가장 이른 값을 썼습니다. "아직 안 보였다", "들으러 간다", "보통 7주에 듣는다" 같은 문장은 뺐습니다. 심장은 소리를 듣기 전 초음파의 깜빡임 확인도 포함했습니다.</li>
  <li>순서가 어긋나거나 이르거나 늦은 값 약 40건은 해당 문장을 다시 보고 고쳤습니다. '5주차'처럼 일이 없는 표현은 쓰지 않았습니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>'처음 확인'은 병원에 간 날입니다. 병원마다 초음파 일정이 달라 실제로 보이기 시작한 시점보다 늦을 수 있습니다.</li>
  <li>블로거가 적은 주수는 병원 기준이며 이식일 기준 계산과 하루 이틀 다를 수 있습니다.</li>
  <li>의학적 판단 근거가 아닙니다.</li>
</ul></section>
</div>
</div>
"""


def main():
    cases = dedupe(read_csv(CASES))
    log = read_csv(os.path.join(DATA, "milestone_log.csv"))
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "milestone_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(cases, log))
    print(f"→ {path}")


if __name__ == "__main__":
    main()
