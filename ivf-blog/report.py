"""data/cases.csv → results/report.html (한 장짜리 결과 보고서, 외부 라이브러리 없이 SVG로 그림)
사용: python report.py
"""
import datetime
import html
import os

from cases import FAILURES, PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from summarize import REV_BINS, REV_COARSE, rev_day, stats

LOW = {"경과 18일 이후", "미관찰", "미상"}


def groups(rows, bins):
    days = [r for r in rows if rev_day(r) is not None]
    out = [(label, stats([r for r in days if f(rev_day(r))])) for label, f in bins]
    out += [(v, stats([r for r in rows if r.get("reversal_day") == v])) for v in ("미관찰",)]
    return out


def pct(x, d=1):
    return "—" if x != x else f"{x * 100:.{d}f}%"


def short(label):
    return label.replace("경과 ", "").replace("역전 ", "")


def bar_chart(data, title):
    """가로 막대 + 95% 신뢰구간. data: [(label, stats)]"""
    w, row, left, right, top = 680, 44, 118, 150, 30
    h = top + row * len(data) + 34
    plot = w - left - right
    x = lambda v: left + plot * v
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}" class="chart">']
    for t in (0, .25, .5, .75, 1):
        parts.append(f'<line x1="{x(t):.1f}" y1="{top - 8}" x2="{x(t):.1f}" y2="{h - 26}" class="grid"/>'
                     f'<text x="{x(t):.1f}" y="{h - 8}" class="tick" text-anchor="middle">{int(t * 100)}%</text>')
    for i, (label, s) in enumerate(data):
        y = top + i * row
        cls = "low" if label in LOW else "hi"
        tip = (f"{label}: {pct(s['rate'])} ({s['hb']}/{s['n']}), 95% CI {pct(s['lo'], 0)}–{pct(s['hi'], 0)}, "
               f"미확인 {s['unk']}건 제외")
        parts.append(f'<g class="row"><title>{html.escape(tip)}</title>'
                     f'<rect x="0" y="{y - 4}" width="{w}" height="{row}" class="hit"/>'
                     f'<text x="{left - 12}" y="{y + 19}" class="lab" text-anchor="end">{html.escape(short(label))}</text>')
        if s["n"]:
            bw = max(plot * s["rate"], 2)
            parts.append(f'<rect x="{left}" y="{y + 6}" width="{bw:.1f}" height="20" rx="4" class="bar {cls}"/>'
                         f'<line x1="{x(s["lo"]):.1f}" y1="{y + 16}" x2="{x(s["hi"]):.1f}" y2="{y + 16}" class="ci"/>'
                         f'<line x1="{x(s["lo"]):.1f}" y1="{y + 10}" x2="{x(s["lo"]):.1f}" y2="{y + 22}" class="ci"/>'
                         f'<line x1="{x(s["hi"]):.1f}" y1="{y + 10}" x2="{x(s["hi"]):.1f}" y2="{y + 22}" class="ci"/>'
                         f'<text x="{w - right + 14}" y="{y + 15}" class="val">{pct(s["rate"])}</text>'
                         f'<text x="{w - right + 14}" y="{y + 31}" class="sub">{s["hb"]}/{s["n"]} · 미확인 {s["unk"]}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def detail_table(data):
    head = ("<tr><th>첫 역전</th><th>심장소리</th><th>계류</th><th>화유</th><th>자궁외</th>"
            "<th>비율</th><th>95% 신뢰구간</th><th>미확인</th></tr>")
    body = []
    for label, s in data:
        f = s["fail"]
        body.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td><td>{s["hb"]}</td>'
                    f'<td>{f["아기집만(계류)"]}</td><td>{f["화학적유산"]}</td><td>{f["자궁외"]}</td>'
                    f'<td class="num"><b>{pct(s["rate"])}</b></td><td>{pct(s["lo"], 0)}–{pct(s["hi"], 0)}</td>'
                    f'<td class="muted">{s["unk"]}</td></tr>')
    return f'<div class="tbl"><table><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def by_embryo_table(sets):
    cols = "".join(f"<th>{html.escape(n)}</th>" for n, _ in sets)
    rows = []
    for label, _ in REV_COARSE + [("미관찰", None)]:
        cells = []
        for _, rs in sets:
            s = dict(groups(rs, REV_COARSE))[label]
            cells.append(f'<td><b>{pct(s["rate"], 0)}</b> <span class="muted">{s["hb"]}/{s["n"]}</span></td>'
                         if s["n"] else '<td class="muted">—</td>')
        rows.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td>{"".join(cells)}</tr>')
    return f'<div class="tbl"><table><thead><tr><th>첫 역전 (5일배 기준)</th>{cols}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def day_table(five):
    rows = []
    for day, name in (("test_d14", "경과 14일 (이식일 포함 15일차)"), ("test_d15", "경과 15일 (이식일 포함 16일차)")):
        for g in ("역전", "동일진하기", "미역전(연함)"):
            s = stats([r for r in five if r.get(day) == g])
            rows.append(f'<tr class="{"low" if g == "미역전(연함)" else ""}"><td>{name}</td><td>{g}</td>'
                        f'<td class="num"><b>{pct(s["rate"])}</b></td><td>{s["hb"]}/{s["n"]}</td>'
                        f'<td>{pct(s["lo"], 0)}–{pct(s["hi"], 0)}</td><td class="muted">{s["unk"]}</td></tr>')
    return ('<div class="tbl"><table><thead><tr><th>시점</th><th>그날 임테기</th><th>비율</th><th>심장소리/분모</th>'
            f'<th>95% 신뢰구간</th><th>미확인</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def age_table(cases):
    fails = [r for r in cases if r["outcome"] in FAILURES]
    cols = [("35이상", "만 35세 이상"), ("35미만", "만 35세 미만"), ("", "단서 없음")]
    rows = []
    for o, name in (("아기집만(계류)", "계류 (아기집만)"), ("화학적유산", "화학적 유산"), ("자궁외", "자궁외 임신")):
        sub = [r for r in fails if r["outcome"] == o]
        rows.append(f"<tr><td>{name}</td>" + "".join(f"<td>{sum(r.get('maternal_age', '') == c for r in sub)}</td>" for c, _ in cols)
                    + f"<td><b>{len(sub)}</b></td></tr>")
    rows.append("<tr class=\"total\"><td>합계</td>" + "".join(f"<td>{sum(r.get('maternal_age', '') == c for r in fails)}</td>" for c, _ in cols)
                + f"<td><b>{len(fails)}</b></td></tr>")
    return ('<div class="tbl"><table><thead><tr><th>결과</th>' + "".join(f"<th>{n}</th>" for _, n in cols)
            + f'<th>계</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


BIRTH_COLS = [("출산", "출산 확인", "var(--accent)"), ("유산", "심장소리 후 유산", "var(--low)"),
              ("진행24", "24주 이상까지 확인", "var(--mid)"), ("진행", "24주 전까지만 확인", "var(--grid)"),
              ("추적불가", "이후 글 없음", "var(--grid)"), ("예정일전", "아직 예정일 전", "var(--strip)")]


def birth_rows(cases, future=False):
    """심장소리 확인 케이스 중 예정일이 지났거나 결과(출산·유산)가 나온 케이스에 출산 판정을 붙인다."""
    log = {r["case_id"]: r for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    out = []
    for c in cases:
        b = log.get(c["case_id"])
        if c["outcome"] != "심장소리확인" or not b:
            continue
        st = b["status"]
        if st == "진행중":
            st = "진행24" if b["last_week"].isdigit() and int(b["last_week"]) >= 24 else "진행"
        if st in ("출산", "유산") or b["due_passed"] == "Y":
            out.append({**c, "birth": st})
        elif future:
            out.append({**c, "birth": "예정일전"})
    return out


def birth_count(rows):
    n = {k: sum(r["birth"] == k for r in rows) for k, _, _ in BIRTH_COLS}
    d = n["출산"] + n["유산"]
    return n, (n["출산"] / d if d else float("nan")), d


def birth_bar(rows):
    n, _, _ = birth_count(rows)
    tot = sum(n.values()) or 1
    segs = "".join(f'<i style="width:{n[k] / tot * 100:.2f}%;background:{c}" title="{name} {n[k]}"></i>'
                   for k, name, c in BIRTH_COLS if n[k])
    return f'<div class="stack">{segs}</div>'


def birth_table(sets):
    head = "".join(f"<th>{name}</th>" for _, name, _ in BIRTH_COLS)
    body = []
    for title, rows in sets:
        n, rate, d = birth_count(rows)
        body.append(f'<tr class="grp"><td colspan="{len(BIRTH_COLS) + 2}"><b>{html.escape(title)}</b> {birth_bar(rows)}</td></tr>')
        for label, f in REV_COARSE + [("미관찰", None)]:
            sub = [r for r in rows if (f(rev_day(r)) if f and rev_day(r) is not None else (not f and r.get("reversal_day") == label))]
            if not sub:
                continue
            m, rt, dd = birth_count(sub)
            body.append(f'<tr class="{"low" if label in LOW else ""}"><td>{html.escape(short(label))}</td>'
                        + "".join(f"<td>{m[k]}</td>" for k, _, _ in BIRTH_COLS)
                        + (f'<td class="num"><b>{pct(rt, 0)}</b> <span class="muted">{m["출산"]}/{dd}</span></td></tr>' if dd >= 10
                           else f'<td class="num muted">{m["출산"]}/{dd}</td></tr>'))
        body.append('<tr class="total"><td>합계</td>' + "".join(f"<td>{n[k]}</td>" for k, _, _ in BIRTH_COLS)
                    + (f'<td class="num"><b>{pct(rate)}</b> <span class="muted">{n["출산"]}/{d}</span></td></tr>' if d >= 10
                       else f'<td class="num muted">{n["출산"]}/{d}</td></tr>'))
    return (f'<div class="tbl"><table><thead><tr><th>첫 역전</th>{head}<th>출산 비율</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


CSS = """
:root{--bg:#f7f8fa;--panel:#ffffff;--fg:#1b2430;--muted:#5d6876;--line:#dde2e8;--grid:#e8ecf0;
--accent:#2f6db3;--low:#d0643b;--mid:#8fb3dc;--lowbg:#fbeee8;--strip:#e9edf2;
--sans:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14181d;--panel:#1b2027;--fg:#e8ecf1;--muted:#9aa5b2;
--line:#2c333d;--grid:#262c35;--accent:#5b8fd4;--low:#d0643b;--mid:#35557d;--lowbg:#2b211d;--strip:#262c35;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#14181d;--panel:#1b2027;--fg:#e8ecf1;--muted:#9aa5b2;--line:#2c333d;--grid:#262c35;
--accent:#5b8fd4;--low:#d0643b;--mid:#35557d;--lowbg:#2b211d;--strip:#262c35;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.6}
.wrap{max-width:880px;margin:0 auto;padding-block:32px 56px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:28px}
header{display:grid;grid-template-columns:auto 1fr;gap:24px;padding-left:14px;align-items:center}
.strip{width:46px;height:120px;border-radius:8px;background:var(--strip);position:relative;border:1px solid var(--line)}
.strip i{position:absolute;left:8px;right:8px;height:5px;border-radius:2px}
.strip .c{top:44px;background:var(--muted);opacity:.55}.strip .t{top:70px;background:var(--low)}
.strip span{position:absolute;left:-14px;font:600 10px var(--mono);color:var(--muted)}
h1{font-size:clamp(24px,4vw,32px);line-height:1.25;margin:0;text-wrap:balance;font-weight:700}
h2{font-size:20px;margin:0 0 4px;text-wrap:balance}
h3{font-size:15px;margin:18px 0 6px;color:var(--muted);font-weight:600}
p{margin:0}.lede{color:var(--muted);margin-top:6px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi b{display:block;font:600 24px var(--mono);font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:13px}
.key{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:16px 18px}
.key ul{margin:6px 0 0;padding-left:20px;display:grid;gap:4px}
section{display:grid;gap:10px;min-width:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;min-width:0;display:grid;gap:12px}
.tag{display:inline-block;font:600 11px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.chart{width:100%;height:auto;display:block}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .tick{fill:var(--muted);font:11px var(--mono)}
.chart .lab{fill:var(--fg);font:500 13px var(--sans)}.chart .val{fill:var(--fg);font:600 14px var(--mono)}
.chart .sub{fill:var(--muted);font:11px var(--sans)}.chart .bar.hi{fill:var(--accent)}.chart .bar.low{fill:var(--low)}
.chart .ci{stroke:var(--fg);stroke-width:1.5;opacity:.55}.chart .hit{fill:transparent}.chart .row:hover .hit{fill:var(--grid)}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--muted);font-size:13px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-weight:600;font-size:12.5px}
tr.low td{background:var(--lowbg)}tr.total td{border-top:2px solid var(--line)}
.muted{color:var(--muted)}.note{color:var(--muted);font-size:13.5px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.two>*{min-width:0}
.stack{display:flex;height:10px;border-radius:5px;overflow:hidden;margin-top:6px;background:var(--grid)}.stack i{display:block;height:100%}
.grp td{padding-top:14px}
ol,ul{margin:0}.method li,.limits li{margin-bottom:4px}
@media (max-width:640px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.two{grid-template-columns:1fr}header{grid-template-columns:1fr}.strip{display:none}}
"""


def build(cases):
    five = [r for r in cases if r.get("embryo_day") == "5"]
    four = [r for r in cases if r.get("embryo_day") == "4"]
    three = [r for r in cases if r.get("embryo_day") == "3"]
    allc = five + four + three
    g_all, g_five = groups(allc, REV_COARSE), groups(five, REV_COARSE)
    d_all, d_five = groups(allc, REV_BINS), groups(five, REV_BINS)
    known = sum(r["outcome"] not in ("미확인", "") for r in allc)
    by = dict(g_all)
    early = stats([r for r in allc if rev_day(r) is not None and rev_day(r) <= 17])
    late = by["경과 18일 이후"]
    none = by["미관찰"]
    legend = ('<div class="legend"><span><i style="background:var(--accent)"></i>경과 17일 이내 역전</span>'
              '<span><i style="background:var(--low)"></i>늦은 역전·역전 미관찰</span>'
              '<span>가는 선: 95% 신뢰구간</span></div>')
    today = datetime.date.today().isoformat()
    b_all = birth_rows(allc)
    b_five = birth_rows(five, future=True)
    bn, brate, bd = birth_count(b_all)
    hb_all = sum(r["outcome"] == "심장소리확인" for r in allc)
    blegend = ('<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{name}</span>'
                                                 for k, name, c in BIRTH_COLS if k != "추적불가") + '</div>')
    return f"""<title>임테기 역전과 심장소리</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · {today}</span>
  <h1>임테기 역전 시점과 심장소리 확인 비율</h1>
  <p class="lede">네이버 블로그 시험관 후기에서 이식 후 임테기가 처음 역전(시약선 T가 대조선 C보다 진해짐)된 날을 모으고, 이후 심장소리를 들었는지 추적했습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{len(allc)}</b><span>분석 케이스 (3·4·5일배)</span></div>
  <div class="kpi"><b>{len(five)}</b><span>5일배</span></div>
  <div class="kpi"><b>{len(four)} · {len(three)}</b><span>4일배 · 3일배</span></div>
  <div class="kpi"><b>{known}</b><span>결과 확인된 케이스</span></div>
</div>

<div class="key"><b>핵심 결과</b>
<ul>
  <li>첫 역전이 <b>5일배 기준 경과 17일 이내</b>면 심장소리 확인 비율이 <b>{pct(early['rate'])}</b> ({early['hb']}/{early['n']})로 높고, 13일 이전·14~15일·16~17일 사이 차이는 크지 않습니다.</li>
  <li>첫 역전이 <b>경과 18일 이후</b>면 <b>{pct(late['rate'])}</b> ({late['hb']}/{late['n']}), 기록 기간 안에 <b>역전이 없으면</b> <b>{pct(none['rate'])}</b> ({none['hb']}/{none['n']})로 떨어집니다. 화학적 유산은 대부분 이 그룹에서 나왔습니다.</li>
  <li>심장소리를 들은 뒤 출산 예정일이 지난 케이스에서 결과가 확인된 것 중 <b>{pct(brate)}</b> ({bn['출산']}/{bd})가 출산했습니다. 심장소리 이후 유산은 {bn['유산']}건이었습니다.</li>
  <li>5일배만 따로 봐도 같은 모양입니다. 3·4일배는 경과일을 5일배 기준으로 환산하면 5일배와 결과가 겹칩니다.</li>
</ul></div>

<section>
  <h2>1. 3·4·5일배 전체</h2>
  <p class="note">3일배는 경과일 −2, 4일배는 −1로 환산해 5일배와 같은 축에 놓았습니다. 비율 = 심장소리 확인 ÷ (심장소리 + 계류 + 화유 + 자궁외).</p>
  <div class="panel">{legend}{bar_chart(g_all, "3·4·5일배 전체 첫 역전 시기별 심장소리 비율")}
  <h3>하루 단위 상세</h3>{detail_table(d_all)}</div>
</section>

<section>
  <h2>2. 5일배아만</h2>
  <p class="note">환산 없이 실제 경과일(이식일 = 0일) 그대로입니다.</p>
  <div class="panel">{legend}{bar_chart(g_five, "5일배 첫 역전 시기별 심장소리 비율")}
  <h3>하루 단위 상세</h3>{detail_table(d_five)}
  <h3>특정 날의 임테기 상태별 (경과 14일·15일)</h3>{day_table(five)}</div>
</section>

<section>
  <h2>3. 배아 일수별 비교</h2>
  <div class="panel">{by_embryo_table([("5일배", five), ("4일배 (−1일)", four), ("3일배 (−2일)", three)])}
  <p class="note">셀: 심장소리 비율, 회색 숫자는 심장소리/분모. 4일배는 표본이 작아 구간마다 흔들림이 큽니다.</p></div>
</section>

<section>
  <h2>4. 심장소리를 못 들은 케이스의 산모 나이</h2>
  <div class="panel">{age_table(cases)}
  <p class="note">같은 블로그의 다른 글에서 나이 표현을 찾아 이식 시점 기준으로 판정했습니다. 성공 케이스의 나이는 조사하지 않아 비교 기준이 없으므로, 이 표만으로 나이의 영향을 말할 수는 없습니다.</p></div>
</section>

<section>
  <h2>5. 심장소리 확인 후 출산까지</h2>
  <p class="note">심장소리를 들은 {hb_all}건 중 출산 예정일이 지났거나 결과가 나온 {len(b_all)}건입니다. 출산 비율 = 출산 ÷ (출산 + 심장소리 후 유산). 이후 글이 임신 주수 기록에서 끊긴 케이스는 비율에서 빼고 개수만 표시했습니다.</p>
  <div class="panel">{blegend}{birth_table([("3·4·5일배 전체 (5일배 기준 환산)", b_all), ("5일배아만 (예정일 전 포함)", b_five)])}
  <p class="note">5일배 케이스는 대부분 2025~2026년 이식이라 아직 출산 예정일 전이어서, 5일배만은 예정일 전 케이스까지 모두 보여 줍니다(분모 10건 미만이면 비율 대신 개수만). 전체 표는 예정일이 지난 케이스만 셌으며, 그래서 대부분 3·4일배입니다.</p>
  <p class="note">심장소리 후 유산은 대부분 7~10주 계류유산이었습니다. 24주 이상까지 기록이 이어진 케이스는 출산 글만 없을 뿐 출산했을 가능성이 큽니다.</p></div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>키워드로 네이버 블로그 후기를 모아 글마다 배아 일수, 이식일, 첫 역전 날을 기록했습니다.</li>
  <li>경과일은 이식일 = 0일. "이식일 포함 N일차"는 N−1로 맞췄습니다.</li>
  <li>같은 블로거의 이후 글로 심장소리 확인, 계류, 화학적 유산, 자궁외 임신을 판정했습니다. 9주 이상 진행이나 난임병원 졸업도 심장소리 확인으로 봤습니다.</li>
  <li>출산 여부는 같은 블로그의 이식 이후 글 제목(출산 후기, 제왕절개·자연분만, 조리원, 생후 N일 등)으로 판정했습니다. 작성 시점이 이식 직후라 이전 아이 이야기일 수 있는 글과 출산 준비 글은 제외했습니다.</li>
  <li>결과를 끝내 알 수 없는 케이스(미확인)는 분모에서 빼고 개수만 표시했습니다. 신뢰구간은 Wilson 95%입니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>후기는 결과가 좋을 때 더 많이 남고, 실패하면 글이 끊기기 쉽습니다. 미확인을 빼면 비율이 높게 나올 수 있습니다.</li>
  <li>"첫 역전"은 처음 기록된 날이라 실제로는 더 빨랐을 수 있습니다. 역전 판단은 블로거의 눈과 임테기 제품에 따라 다릅니다.</li>
  <li>3·4일배는 2~3개 이식이 많아 쌍둥이가 흔합니다.</li>
  <li>의학적 판단 근거가 아닙니다. 피검 hCG와 초음파가 기준입니다.</li>
</ul></section>
</div>
</div>
"""


def main():
    cases = dedupe(read_csv(CASES))
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(cases))
    print(f"→ {path}")


if __name__ == "__main__":
    main()
