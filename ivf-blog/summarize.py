"""4단계: data/cases.csv → results/summary.md
주 지표 = 심장소리확인 / (심장소리확인 + 실패[계류·화유·자궁외]), 미확인은 분모 제외·개수 별도.
"""
import math
import os
import sys

from cases import FAILURES, PATH as CASES, dedupe, validate
from common import RESULTS, read_csv

GROUPS = ["역전", "동일진하기", "미역전(연함)"]


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def stats(rows):
    hb = sum(r["outcome"] == "심장소리확인" for r in rows)
    fail = {f: sum(r["outcome"] == f for r in rows) for f in sorted(FAILURES)}
    unk = sum(r["outcome"] in ("미확인", "") for r in rows)
    n = hb + sum(fail.values())
    lo, hi = wilson(hb, n)
    return {"n_total": len(rows), "hb": hb, "fail": fail, "unk": unk, "n": n,
            "rate": hb / n if n else float("nan"), "lo": lo, "hi": hi,
            "twins": sum(r.get("twins") == "쌍둥이" for r in rows if r["outcome"] == "심장소리확인")}


def fmt_pct(x):
    return "—" if math.isnan(x) else f"{x * 100:.1f}%"


def row_md(label, s):
    f = s["fail"]
    return (f"| {label} | {s['n_total']} | {s['hb']} | {f['아기집만(계류)']} | {f['화학적유산']} | {f['자궁외']} "
            f"| {s['n']} | {s['unk']} | {fmt_pct(s['rate'])} | {fmt_pct(s['lo'])}–{fmt_pct(s['hi'])} |")


HEAD = ("| 그룹 | 케이스 | 심장소리 | 계류 | 화유 | 자궁외 | 분모 | 미확인(제외) | 비율 | Wilson 95% CI |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")


def table(rows, day, by=None):
    lines = [HEAD]
    for g in GROUPS:
        sub = [r for r in rows if r.get(day) == g]
        if by is None:
            lines.append(row_md(g, stats(sub)))
        else:
            for v in by[1]:
                lines.append(row_md(f"{g} · {v}", stats([r for r in sub if r.get(by[0]) == v])))
    return "\n".join(lines)


REV_BINS = [("경과 12일 이전", lambda d: d <= 12), ("경과 13일", lambda d: d == 13), ("경과 14일", lambda d: d == 14),
            ("경과 15일", lambda d: d == 15), ("경과 16일", lambda d: d == 16), ("경과 17일", lambda d: d == 17),
            ("경과 18일 이후", lambda d: d >= 18)]
REV_COARSE = [("경과 13일 이전", lambda d: d <= 13), ("경과 14~15일", lambda d: 14 <= d <= 15),
              ("경과 16~17일", lambda d: 16 <= d <= 17), ("경과 18일 이후", lambda d: d >= 18)]


def reversal_table(rows, bins):
    """reversal_day(첫 역전 경과일) 구간별 심장소리 비율. 미관찰·미상은 따로 한 줄씩."""
    lines = [HEAD.replace("| 그룹 |", "| 첫 역전 |", 1)]
    days = [r for r in rows if r.get("reversal_day", "").isdigit()]
    for label, f in bins:
        lines.append(row_md(label, stats([r for r in days if f(int(r["reversal_day"]))])))
    for v in ("미관찰", "미상"):
        lines.append(row_md(v, stats([r for r in rows if r.get("reversal_day") == v])))
    return "\n".join(lines)


MAIN_DAYS = [("test_d14", "경과 14일(이식일 포함 15일차)"), ("test_d15", "경과 15일(이식일 포함 16일차)")]


def main_line(label, s):
    return (f"- {label} 역전: **{fmt_pct(s['rate'])}** ({s['hb']}/{s['n']}, Wilson 95% CI "
            f"{fmt_pct(s['lo'])}–{fmt_pct(s['hi'])}), 미확인 {s['unk']}건 제외, 심장소리 확인 중 쌍둥이 {s['twins']}건")


def build(cases):
    five = [r for r in cases if r.get("embryo_day") == "5"]
    six = [r for r in cases if r.get("embryo_day") == "6"]
    out = [
        "# 5일배아 이식 후 경과 14·15일 임테기 역전 → 심장소리 확인 비율",
        "",
        f"- 판정 케이스(주기 단위, 중복 제거): {len(cases)}  · 5일배 {len(five)} · 6일배 {len(six)} (별도)",
        "- 경과일은 이식일 = 0 기준. \"이식일 포함 15일차\" = 경과 14일, \"이식일 포함 16일차\" = 경과 15일.",
        "- 주 지표 = 심장소리확인 / (심장소리확인 + 계류 + 화유 + 자궁외). 미확인은 분모에서 제외하고 개수만 표기.",
        "",
        "## 주 결과 (5일배)",
        "",
    ]
    out += [main_line(label, stats([r for r in five if r.get(day) == "역전"])) for day, label in MAIN_DAYS]
    both = [r for r in five if r.get("test_d14") == "역전" and r.get("test_d15") == "역전"]
    late = [r for r in five if r.get("test_d14") in ("동일진하기", "미역전(연함)") and r.get("test_d15") == "역전"]
    out += [main_line("경과 14·15일 모두", stats(both)),
            main_line("경과 14일 미역전 → 경과 15일", stats(late)), ""]
    out += ["## 첫 역전 시기별 심장소리 비율 (5일배)", "",
            "- reversal_day = 블로거가 처음 '역전'이라 적은 날(경과일). 그 전 날짜 기록이 없으면 실제 역전은 더 빨랐을 수 있다.",
            "- 미관찰 = 기록된 기간 안에 역전이 없거나 애매했던 케이스(임테기를 일찍 멈춘 경우 포함).", "",
            reversal_table(five, REV_BINS), "", "### 묶어서 보기 (5일배)", "", reversal_table(five, REV_COARSE), "",
            "### 참고: 배아 일수 무관 전체", "", reversal_table(cases, REV_COARSE), ""]
    for day, label in MAIN_DAYS:
        out += [f"## {label} 결과별 비교 (5일배)", "", table(five, day), "",
                f"### 하위분석: 신선 vs 동결 ({label}, 5일배)", "",
                table(five, day, ("transfer_type", ["신선", "동결", "불명"])), ""]
    out += ["## 참고: 경과 13일 (5일배)", "", table(five, "test_d13"), ""]
    for day, label in MAIN_DAYS:
        out += [f"## 참고: 6일배 {label} (분석 대상 외)", "", table(six, day), ""]
    out += [
        "## 한계",
        "",
        "- **후기 작성자 편향**: 블로그 후기는 결과가 좋을 때(또는 극적일 때) 더 많이 쓰이고, 실패 후 후속 글이 "
        "끊기는 경우가 많아 '미확인'이 실패 쪽으로 치우쳐 있을 가능성이 크다. 미확인을 분모에서 빼면 비율이 과대추정될 수 있다.",
        "- **역전 판단의 주관성**: 사진 밝기·촬영 시간·건조 정도에 따라 진하기가 달라지고, 판정은 블로거 서술과 사진 설명에 의존한다.",
        "- **임테기 브랜드 차이**: 브랜드별 민감도·발색이 달라 같은 hCG 수치에서도 역전 시점이 다르다.",
        "- **일차 표기 불일치**: 이식일을 0일차/1일차로 세는 방식이 섞여 있어 날짜가 없는 글은 ±1일 오차 가능.",
        "- **검색 노출 편향**: 검색 API 상위 노출 글만 표본에 들어가며, 키워드 자체가 '역전' 사례를 과대 포함한다.",
        "- 의학적 판단 근거로 쓰기 어렵다. 피검 hCG와 초음파가 기준이다.",
    ]
    return "\n".join(out) + "\n"


def main():
    rows = read_csv(CASES)
    errs = validate(rows)
    if errs:
        print("\n".join(errs))
        sys.exit(1)
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, "summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build(dedupe(rows)))
    print(f"→ {path}")


if __name__ == "__main__":
    main()
