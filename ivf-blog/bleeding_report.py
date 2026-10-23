"""data/bleeding_log.csv → results/bleeding_report.html (임신 초기 피비침과 심장소리·출산, report.py와 같은 양식)
사용: python bleeding_report.py
"""
import collections
import datetime
import html
import os

import report
from cases import PATH as CASES, dedupe
from common import DATA, RESULTS, read_csv
from report import CSS, bar_chart, pct
from summarize import wilson

CATS = [("없음", "언급 없음"), ("brown", "갈색 소량"), ("spot", "피비침 (색 미상)"), ("red", "빨간 피·많은 양")]
report.LOW.update({"빨간 피·많은 양", "피비침 (색 미상)"})


def st(k, n, unk=0):
    lo, hi = wilson(k, n)
    return {"hb": k, "n": n, "rate": k / n if n else float("nan"), "lo": lo, "hi": hi, "unk": unk}


def rate_table(rows, per, ok, okname):
    body = []
    for c, name in CATS:
        s = [r for r in rows if r[per] == c]
        k = sum(ok(r) for r in s)
        x = st(k, len(s))
        body.append(f'<tr class="{"low" if c in ("red", "spot") else ""}"><td>{name}</td><td>{len(s)}</td><td>{k}</td>'
                    f'<td class="num"><b>{pct(x["rate"])}</b></td><td>{pct(x["lo"], 0)}–{pct(x["hi"], 0)}</td></tr>')
    return (f'<div class="tbl"><table><thead><tr><th>피비침</th><th>케이스</th><th>{okname}</th><th>비율</th>'
            f'<th>95% 신뢰구간</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def chart(rows, per, ok, title):
    data = []
    for c, name in CATS:
        s = [r for r in rows if r[per] == c]
        data.append((name, st(sum(ok(r) for r in s), len(s))))
    return bar_chart(data, title).replace("· 미확인 0", "").replace(", 미확인 0건 제외", "")


def overall_table(rows):
    """아기집 확인 케이스 기준 출산까지: 단계별 곱셈과 직접 계산을 나란히."""
    sac = [r for r in rows if r["outcome"] in ("심장소리확인", "아기집만(계류)")]
    body = []
    for c, name in CATS:
        s = [r for r in sac if r["pre"] == c]
        hb = sum(r["outcome"] == "심장소리확인" for r in s)
        born = sum(r["birth"] == "출산" for r in s)
        lost = sum(r["birth"] == "유산" for r in s)
        fail = len(s) - hb
        p1, p2 = hb / len(s), born / (born + lost) if born + lost else float("nan")
        body.append(f'<tr class="{"low" if c in ("red", "spot") else ""}"><td>{name}</td><td>{pct(p1)} <span class="muted">{hb}/{len(s)}</span></td>'
                    f'<td>{pct(p2)} <span class="muted">{born}/{born + lost}</span></td><td class="num"><b>{pct(p1 * p2)}</b></td>'
                    f'<td class="num">{pct(born / (born + lost + fail))} <span class="muted">{born}/{born + lost + fail}</span></td></tr>')
    return ('<div class="tbl"><table><thead><tr><th>심장 확인 전 피비침</th><th>심장소리</th><th>심장소리 후 출산</th>'
            '<th>출산까지 (곱셈)</th><th>출산까지 (직접)</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def build(rows):
    hb_ok = lambda r: r["outcome"] == "심장소리확인"
    born_ok = lambda r: r["birth"] == "출산"
    resolved = [r for r in rows if r["birth"] in ("출산", "유산")]
    born = [r for r in rows if r["birth"] == "출산"]
    any_pre = sum(r["pre"] != "없음" for r in born)
    brown_born = [r for r in resolved if r["pre"] == "brown"]
    none_born = [r for r in resolved if r["pre"] == "없음"]
    brown_hb = [r for r in rows if r["pre"] == "brown"]
    weeks = collections.Counter(int(r["first_ga"].split("w")[0]) for r in born if r["pre"] == "brown" and r["first_ga"])
    comp = collections.Counter(r["pre"] for r in born)
    hema = {h: [r for r in resolved if r["hematoma"] == h] for h in ("Y", "")}
    today = datetime.date.today().isoformat()
    legend = ('<div class="legend"><span><i style="background:var(--accent)"></i>언급 없음 · 갈색 소량</span>'
              '<span><i style="background:var(--low)"></i>색 미상 · 빨간 피·많은 양</span><span>가는 선: 95% 신뢰구간</span></div>')
    week_cells = "".join(f"<td>{weeks.get(w, 0)}</td>" for w in (4, 5, 6, 7))
    return f"""<title>초기 피비침과 결과</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="strip" aria-hidden="true"><i class="c"></i><span style="top:38px">C</span><i class="t"></i><span style="top:64px">T</span></div>
  <div><span class="tag">시험관 이식 후기 분석 · {today}</span>
  <h1>임신 초기 피비침과 심장소리·출산</h1>
  <p class="lede">시험관 후기 {len(rows)}건에서 임신 초기 피비침 언급을 찾아, 갈색 소량·빨간 피 등 유형별로 심장소리와 출산 비율을 비교했습니다.</p></div>
</header>

<div class="kpis">
  <div class="kpi"><b>{pct(any_pre / len(born))}</b><span>출산한 케이스 중 심장 확인 전 피비침 언급</span></div>
  <div class="kpi"><b>{pct(comp['brown'] / len(born))}</b><span>그중 갈색 소량 ({comp['brown']}/{len(born)})</span></div>
  <div class="kpi"><b>{pct(sum(map(hb_ok, brown_hb)) / len(brown_hb))}</b><span>갈색 소량 → 심장소리 ({sum(map(hb_ok, brown_hb))}/{len(brown_hb)})</span></div>
  <div class="kpi"><b>{pct(sum(map(born_ok, brown_born)) / len(brown_born))}</b><span>갈색 소량 + 심장소리 → 출산 ({sum(map(born_ok, brown_born))}/{len(brown_born)})</span></div>
</div>

<div class="key"><b>핵심 결과</b>
<ul>
  <li>피비침은 흔했습니다. <b>출산까지 간 케이스의 {pct(any_pre / len(born))}</b>가 심장소리 확인 전에 피비침을 적었고, 갈색 소량만 있었던 경우가 {pct(comp['brown'] / len(born))}, 빨간 피나 많은 양을 적은 경우도 {pct(comp['red'] / len(born))}였습니다.</li>
  <li><b>갈색 소량</b> 피비침이 있었던 케이스의 심장소리 비율은 {pct(sum(map(hb_ok, brown_hb)) / len(brown_hb))}로, 언급이 없던 케이스({pct(sum(map(hb_ok, [r for r in rows if r['pre'] == '없음'])) / sum(r['pre'] == '없음' for r in rows))})와 신뢰구간이 겹쳐 뚜렷한 차이가 없습니다.</li>
  <li>심장소리를 들은 뒤 출산 비율도 갈색 소량 {pct(sum(map(born_ok, brown_born)) / len(brown_born))} ({sum(map(born_ok, brown_born))}/{len(brown_born)}), 언급 없음 {pct(sum(map(born_ok, none_born)) / len(none_born))} ({sum(map(born_ok, none_born))}/{len(none_born)})로 비슷했습니다. 빨간 피·많은 양이나 색을 적지 않은 피비침 쪽이 조금 낮지만, 이 경우도 대부분 출산했습니다.</li>
  <li>갈색 피비침은 주로 <b>4~6주</b>에 처음 나타났습니다.</li>
</ul></div>

<section>
  <h2>1. 심장 확인 전 피비침 → 심장소리</h2>
  <p class="note">임신 4주 1일부터 심장을 처음 확인한 날 전까지의 피비침입니다(심장을 못 들은 케이스는 7주 6일까지). 비율 = 심장소리 ÷ (심장소리 + 계류·화유·자궁외).</p>
  <div class="panel">{legend}{chart(rows, "pre", hb_ok, "피비침 유형별 심장소리 비율")}
  {rate_table(rows, "pre", hb_ok, "심장소리")}</div>
</section>

<section>
  <h2>2. 심장소리를 들은 뒤 → 출산</h2>
  <p class="note">출산 예정일이 지나 결과(출산 또는 심장소리 후 유산)가 확인된 {len(resolved)}건입니다.</p>
  <div class="panel"><h3>심장 확인 전 피비침 기준</h3>{legend}{chart(resolved, "pre", born_ok, "심장 확인 전 피비침 유형별 출산 비율")}
  {rate_table(resolved, "pre", born_ok, "출산")}
  <h3>심장 확인 후 (~12주) 피비침 기준</h3>{chart(resolved, "post", born_ok, "심장 확인 후 피비침 유형별 출산 비율")}
  {rate_table(resolved, "post", born_ok, "출산")}</div>
</section>

<section>
  <h2>3. 아기집을 확인한 경우 출산까지</h2>
  <p class="note">자궁 안 아기집을 본 케이스(심장소리 + 아기집만 계류)만 봤습니다. <b>직접</b> = 출산 ÷ (출산 + 심장소리 후 유산 + 심장소리 못 들음). 실패는 일찍, 출산은 예정일 뒤에 확정되므로 진행 중 케이스가 빠지는 직접 계산은 낮게 치우칩니다. <b>곱셈</b> = 심장소리 비율 × 심장소리 후 출산 비율로 이 치우침을 줄인 값입니다. 실제는 두 값 사이로 봅니다.</p>
  <div class="panel">{overall_table(rows)}</div>
</section>

<section>
  <h2>4. 출산한 케이스의 피비침 시기 · 피고임</h2>
  <div class="panel"><div class="tbl"><table><thead><tr><th>갈색 피비침을 처음 적은 주수 (출산 케이스)</th><th>4주</th><th>5주</th><th>6주</th><th>7주</th></tr></thead>
  <tbody><tr><td>케이스 수</td>{week_cells}</tr></tbody></table></div>
  <div class="tbl"><table><thead><tr><th>피고임(융모막하 혈종) 언급</th><th>케이스</th><th>출산</th><th>비율</th></tr></thead><tbody>
  <tr><td>있음</td><td>{len(hema['Y'])}</td><td>{sum(map(born_ok, hema['Y']))}</td><td class="num"><b>{pct(sum(map(born_ok, hema['Y'])) / len(hema['Y']))}</b></td></tr>
  <tr><td>없음·언급 없음</td><td>{len(hema[''])}</td><td>{sum(map(born_ok, hema['']))}</td><td class="num"><b>{pct(sum(map(born_ok, hema[''])) / len(hema['']))}</b></td></tr>
  </tbody></table></div>
  <p class="note">피고임도 출산 비율과 뚜렷한 관계가 보이지 않았습니다. 갈색 피비침은 이전에 고였던 피가 나오는 경우가 많다고 블로거들이 병원에서 들은 설명을 자주 적었습니다.</p></div>
</section>

<div class="two">
<section><h2>분석 방법</h2>
<ul class="method note">
  <li>3·4·5일배 케이스의 이식 후기와 이식 후 75일 안의 후속 글에서 '피비침', '갈색혈·갈색냉', '선홍', '빨간 피', '하혈', '출혈' 문장을 찾았습니다.</li>
  <li>앞뒤 문장에 '없었다', '혹시 ~하면', 해시태그 같은 표현이 있으면 뺐습니다. 갈색이면서 많은 양 표현이 없으면 '갈색 소량', 선홍·빨간·하혈·생리처럼·많이 나옴이면 '빨간 피·많은 양'으로 나눴습니다.</li>
  <li>시기는 문장 근처의 임신 주수, 없으면 글 작성일로 정했습니다. 표본 대조에서 분류는 대략 8~9할이 맞았고, 틀린 몇 건은 직접 고쳤습니다.</li>
</ul></section>
<section><h2>해석할 때 주의</h2>
<ul class="limits note">
  <li>블로그에 적지 않은 피비침은 '언급 없음'으로 잡힙니다. 실제로 피비침이 있었던 비율은 더 높을 수 있습니다.</li>
  <li>유산된 케이스의 출혈은 진단 뒤(약 중단, 배출 과정)에 쓴 것이 섞여 있어, 실패 쪽 출혈 비율이 높게 보일 수 있습니다.</li>
  <li><b>병원에 바로 연락할 신호:</b> 생리처럼 많은 빨간 피, 덩어리, 심한 복통이나 한쪽 통증, 어지러움. 소량 갈색이라도 걱정되면 병원에 묻는 것이 기준입니다.</li>
  <li>의학적 판단 근거가 아닙니다.</li>
</ul></section>
</div>
</div>
"""


def main():
    ids = {c["case_id"] for c in dedupe(read_csv(CASES))}
    rows = [r for r in read_csv(os.path.join(DATA, "bleeding_log.csv"))
            if r["case_id"] in ids and not r["manual"].startswith("제외")]
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "bleeding_report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(rows))
    print(f"→ {path}")


if __name__ == "__main__":
    main()
