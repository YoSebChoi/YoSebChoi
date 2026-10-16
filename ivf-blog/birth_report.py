"""data/cases.csv + data/birth_log.csv → results/birth_report.html (심장소리 확인 후 출산까지, report.py와 같은 양식)
사용: python birth_report.py
"""
import datetime
import html
import os

from cases import PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from report import BIRTH_COLS, CSS, LOW, bar_chart, birth_count, birth_rows, birth_table, pct, short
from summarize import REV_COARSE, rev_day, wilson


def bstats(rows):
    """bar_chart가 쓰는 모양으로: hb = 출산, n = 출산 + 유산, unk = 결과 미확인(진행·추적불가)"""
    n, rate, d = birth_count(rows)
    lo, hi = wilson(n["출산"], d)
    return {"hb": n["출산"], "n": d, "rate": rate, "lo": lo, "hi": hi,
            "unk": len(rows) - d - n["예정일전"]}


def rev_groups(rows):
    out = [(label, bstats([r for r in rows if rev_day(r) is not None and f(rev_day(r))])) for label, f in REV_COARSE]
    return out + [("미관찰", bstats([r for r in rows if r.get("reversal_day") == "미관찰"]))]


def compare_table(title, sets):
    body = []
    for name, rows in sets:
        n, _, _ = birth_count(rows)
        s = bstats(rows)
        rate = (f'<b>{pct(s["rate"])}</b> <span class="muted">{s["hb"]}/{s["n"]}</span>' if s["n"] >= 10
                else f'<span class="muted">{s["hb"]}/{s["n"]}</span>')
        ci = f'{pct(s["lo"], 0)}–{pct(s["hi"], 0)}' if s["n"] >= 10 else "—"
        body.append(f"<tr><td>{html.escape(name)}</td><td>{len(rows)}</td><td>{n['출산']}</td><td>{n['유산']}</td>"
                    f'<td class="muted">{s["unk"]}</td><td class="num">{rate}</td><td>{ci}</td></tr>')
    return (f'<div class="tbl"><table><thead><tr><th>{title}</th><th>케이스</th><th>출산</th><th>심장소리 후 유산</th>'
            f'<th>결과 미확인</th><th>출산 비율</th><th>95% 신뢰구간</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def loss_table(rows, log):
    loss = [r for r in rows if r["birth"] == "유산"]
    weeks = [int(log[r["case_id"]]["last_week"]) if log[r["case_id"]]["last_week"].isdigit() else None for r in loss]
    bins = [("7주 이하", lambda w: w <= 7), ("8주", lambda w: w == 8), ("9~12주", lambda w: 9 <= w <= 12),
            ("13주 이후", lambda w: w >= 13)]
    cells = [(name, sum(w is not None and f(w) for w in weeks)) for name, f in bins] + [("주수 미상", weeks.count(None))]
    return ('<div class="tbl"><table><thead><tr>' + "".join(f"<th>{n}</th>" for n, _ in cells) + "<th>계</th></tr></thead>"
            "<tbody><tr>" + "".join(f"<td>{c}</td>" for _, c in cells) + f"<td><b>{len(loss)}</b></td></tr></tbody></table></div>")


def build(cases):
    log = {r["case_id"]: r for r in read_csv(os.path.join(DATA, "birth_log.csv"))}
    allc = [r for r in cases if r.get("embryo_day") in ("3", "4", "5")]
    five = [r for r in allc if r["embryo_day"] == "5"]
    hb_all = [r for r in allc if r["outcome"] == "심장소리확인"]
    b_all = birth_rows(allc)
    b_five = birth_rows(five, future=True)
    every = birth_rows(allc, future=True)
    n, rate, d = birth_count(b_all)
    s_all = bstats(b_all)
    g_all = rev_groups(b_all)
    by = dict(g_all)
    late24 = n["진행24"]
    five_due = sum(r["birth"] != "예정일전" for r in b_five)
    fn, _, _ = birth_count(b_five)
    legend = ('<div class="legend"><span><i style="background:var(--accent)"></i>경과 17일 이내 역전</span>'
              '<span><i style="background:var(--low)"></i>늦은 역전·역전 미관찰</span>'
              '<span>가는 선: 95% 신뢰구간</span></div>')
    blegend = ('<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{name}</span>'
                                                 for k, name, c in BIRTH_COLS) + '</div>')
    today = datetime.date.today().isoformat()
    twin = lambda v: [r for r in b_all if (r.get("twins") == "쌍둥이") == v]
    return f"""<title>심장소리 이후 출산</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · {today}</span>
  <h1>심장소리 확인 후 출산까지</h1>
  <p class="lede">임테기 역전 분석에서 심장소리를 들은 케이스를 같은 블로그의 이후 글로 끝까지 따라가, 실제로 출산했는지 확인했습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{len(hb_all)}</b><span>심장소리 확인 (3·4·5일배)</span></div>
  <div class="kpi"><b>{len(b_all)}</b><span>예정일 지났거나 결과 나온 케이스</span></div>
  <div class="kpi"><b>{n['출산']}</b><span>출산 확인</span></div>
  <div class="kpi"><b>{pct(rate)}</b><span>출산 비율 (출산 ÷ 출산+유산)</span></div>
</div>

<div class="key"><b>핵심 결과</b>
<ul>
  <li>심장소리를 들은 뒤 결과가 확인된 {d}건 중 <b>{pct(rate)}</b> ({n['출산']}건)가 출산했습니다 (95% 신뢰구간 {pct(s_all['lo'], 0)}–{pct(s_all['hi'], 0)}). 심장소리 후 유산은 <b>{n['유산']}건</b>이고 대부분 10주 이전 계류유산입니다.</li>
  <li>첫 역전 시점별 출산 비율은 13일 이전 <b>{pct(by['경과 13일 이전']['rate'], 0)}</b>, 14~15일 <b>{pct(by['경과 14~15일']['rate'], 0)}</b>, 16~17일 <b>{pct(by['경과 16~17일']['rate'], 0)}</b>로, 일단 심장소리를 들은 뒤에는 역전 시점에 따른 차이가 크지 않습니다. 18일 이후는 {by['경과 18일 이후']['hb']}/{by['경과 18일 이후']['n']}건으로 표본이 적습니다.</li>
  <li>출산 글은 없지만 <b>24주 이상까지 기록이 이어진 {late24}건</b>은 대부분 출산했을 것으로 보여, 실제 출산 비율은 이보다 높을 수 있습니다.</li>
  <li><b>5일배아</b>는 대부분 2025~2026년 이식이라 {len(b_five)}건 중 {five_due}건만 예정일이 지났습니다. 아직 출산 비율을 말하기 어렵습니다.</li>
</ul></div>

<section>
  <h2>1. 3·4·5일배 전체</h2>
  <p class="note">3일배는 경과일 −2, 4일배는 −1로 환산한 첫 역전 시점별입니다. 비율 = 출산 ÷ (출산 + 심장소리 후 유산). 막대 오른쪽 '미확인'은 출산 글 없이 임신 주수 기록에서 끊긴 케이스입니다.</p>
  <div class="panel">{legend}{bar_chart(g_all, "첫 역전 시기별 심장소리 이후 출산 비율")}
  <h3>결과 구성</h3>{blegend}{birth_table([("3·4·5일배 전체 (5일배 기준 환산)", b_all)])}</div>
</section>

<section>
  <h2>2. 5일배아만</h2>
  <p class="note">5일배는 예정일이 지난 케이스가 {five_due}건뿐이어서, 아직 예정일 전인 케이스까지 모두 보여 줍니다. 분모 10건 미만이면 비율 대신 개수만 적었습니다.</p>
  <div class="panel">{blegend}{birth_table([("5일배아만 (예정일 전 포함)", b_five)])}
  <p class="note">지금까지 출산 {fn['출산']}건, 심장소리 후 유산 {fn['유산']}건이 확인됐습니다. 예정일 전 {fn['예정일전']}건은 몇 달 뒤 같은 방법으로 다시 확인하면 됩니다.</p></div>
</section>

<section>
  <h2>3. 배아 일수·쌍둥이별 비교</h2>
  <div class="panel">{compare_table("배아", [("5일배", [r for r in b_all if r["embryo_day"] == "5"]), ("4일배", [r for r in b_all if r["embryo_day"] == "4"]), ("3일배", [r for r in b_all if r["embryo_day"] == "3"])])}
  <h3>단태 · 쌍둥이</h3>{compare_table("임신", [("단태·불명", twin(False)), ("쌍둥이", twin(True))])}
  <p class="note">예정일이 지났거나 결과가 나온 케이스 기준입니다. 쌍둥이는 조산이 많지만 출산 자체는 '출산'으로 셌습니다. 쌍둥이 여부는 이후 글에서 확인된 경우가 많아, 일찍 유산된 쌍둥이 임신은 단태로 남았을 수 있습니다(쌍둥이 100%는 과대평가일 수 있음).</p></div>
</section>

<section>
  <h2>4. 심장소리 후 유산 시기</h2>
  <div class="panel">{loss_table(every, log)}
  <p class="note">유산을 알린 글의 제목에 나온 주수입니다. 주수가 나온 15건 중 10건이 8주 이하로, 심장소리를 들은 직후 심장이 멈춘 계류유산이 대부분이었습니다. 13주 이후는 2건입니다.</p></div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>심장소리를 확인한 3·4·5일배 케이스에서 같은 블로그의 이식 이후 글 목록(제목)을 모았습니다.</li>
  <li>출산 후기, 제왕절개·자연분만, 조리원, 생후 N일 같은 제목이면 출산, 계류·심장 멈춤 등이면 유산, 임신 주수 글만 있으면 마지막 주수까지 진행으로 판정했습니다.</li>
  <li>글 작성 시점을 추정해 이식 직후에 쓴 육아 글(이전 아이)과 출산가방·백일해 접종 같은 출산 전 글은 제외했습니다. 애매한 29건은 제목을 직접 보고 판정했습니다.</li>
  <li>출산 예정일은 이식일 + 261일(5일배 기준, 3·4일배는 +2·+1일)로 잡았습니다. 신뢰구간은 Wilson 95%입니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>출산 후 블로그를 쉬는 경우가 많아 출산 글을 못 찾은 케이스가 있습니다. 반대로 유산 후 글이 끊기면 유산이 빠질 수 있어, 미확인을 빼면 비율이 높게 나올 수 있습니다.</li>
  <li>제목만으로 판정해 사산·조산의 결과까지는 구분하지 않았습니다.</li>
  <li>예정일 계산은 대략적인 값이라 예정일 직후 케이스는 아직 글이 없을 수 있습니다.</li>
  <li>의학적 판단 근거가 아닙니다.</li>
</ul></section>
</div>
</div>
"""


def main():
    cases = dedupe(read_csv(CASES))
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "birth_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(cases))
    print(f"→ {path}")


if __name__ == "__main__":
    main()
