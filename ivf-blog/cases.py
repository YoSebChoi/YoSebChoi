"""data/cases.csv 스키마, 일차 정규화, 검증.

한 행 = 한 이식 주기(case). 같은 주기를 다룬 글이 여러 개면 case_id(blogId + 이식일)로 묶는다.
판정값은 글을 직접 읽고 기록한다. 이 모듈은 값의 형식 검증과 일차 계산만 한다.

필드
- url              판정에 쓴 대표 글
- case_id          {blogId}_{transfer_date} (이식일 모르면 {blogId}_{logNo})
- embryo_day       5 / 6 / 3 / 불명   (분석 대상은 5, 6일배는 별도 기록)
- transfer_type    신선 / 동결 / 불명
- transfer_date    YYYY-MM-DD (알 수 있으면)
- maternal_age     35이상 / 35미만 / (빈칸=미상). 이식 시점 만 나이 기준, 근거는 ambiguous에 '나이:'로 기록
- count_basis      date(날짜로 계산) / zero(이식일=0일차) / one(이식일=1일차) / 불명
- test_d13, test_d14, test_d15
                   이식일=0 기준 경과일별 임테기 결과: 역전 / 동일진하기 / 미역전(연함) / 음성 / 기록없음
                   (test_d14 = 과제의 test_result_d14, "이식일 포함 15일차")
- reversal_day     블로거가 처음 역전이라 적은 날(이식일=0 기준 경과일, 숫자) / 미관찰(기록 안에서 역전 없음·애매) / 미상(역전은 했으나 일차 불명)
                   그 전 날짜 기록이 없으면 '처음 기록된 역전일'이라 실제 역전은 더 빨랐을 수 있다
- day_from_transfer 글에서 주로 다룬 임테기 시점(이식일=0 기준 경과일)
- hcg              "YYYY-MM-DD:값(dN)" 을 ; 로 연결. 예) 2026-03-10:312(d9);2026-03-12:780(d11)
- evidence         판정 근거 한 줄 요약(원문 복사 금지)
- outcome          심장소리확인 / 아기집만(계류) / 화학적유산 / 자궁외 / 미확인
- twins            단태 / 쌍둥이 / 불명
- outcome_week     확인 주수 (예: 6+3)
- followup_url     결과를 확인한 후속 글
- ambiguous        애매하면 사유 기록(중간보고용)
"""
import datetime as dt
import os
import sys

from common import DATA, read_csv, write_csv

PATH = os.path.join(DATA, "cases.csv")
FIELDS = ["url", "case_id", "embryo_day", "transfer_type", "transfer_date", "maternal_age", "count_basis",
          "day_from_transfer", "test_d13", "test_d14", "test_d15", "reversal_day", "hcg", "evidence",
          "outcome", "twins", "outcome_week", "followup_url", "ambiguous"]

ALLOWED = {
    "embryo_day": {"5", "6", "3", "불명"},
    "transfer_type": {"신선", "동결", "불명"},
    "maternal_age": {"35이상", "35미만", ""},
    "count_basis": {"date", "zero", "one", "불명"},
    "test_d13": {"역전", "동일진하기", "미역전(연함)", "음성", "기록없음", ""},
    "outcome": {"심장소리확인", "아기집만(계류)", "화학적유산", "자궁외", "미확인", ""},
    "twins": {"단태", "쌍둥이", "불명", ""},
}
ALLOWED["test_d14"] = ALLOWED["test_d15"] = ALLOWED["test_d13"]
FAILURES = {"아기집만(계류)", "화학적유산", "자궁외"}


def elapsed_days(transfer_date=None, test_date=None, blogger_day=None, basis=None):
    """이식일=0 기준 경과일.
    날짜가 둘 다 있으면 날짜 차이(가장 신뢰). 아니면 블로거 표기 N일차를 기준에 따라 변환:
    zero(이식일=0일차) → N, one(이식일=1일차, '이식일 포함') → N-1.
    """
    if transfer_date and test_date:
        return (dt.date.fromisoformat(test_date) - dt.date.fromisoformat(transfer_date)).days
    if blogger_day is None or basis not in ("zero", "one"):
        return None
    return int(blogger_day) - (1 if basis == "one" else 0)


def is_target(row, day="test_d14", result="역전"):
    return row.get("embryo_day") == "5" and row.get(day) == result


def dedupe(rows):
    """같은 case_id는 첫 행 우선, 빈 칸은 뒤 행 값으로 채움."""
    out = {}
    for r in rows:
        key = r.get("case_id") or r["url"]
        if key not in out:
            out[key] = dict(r)
        else:
            for k, v in r.items():
                if v and not out[key].get(k):
                    out[key][k] = v
    return list(out.values())


def validate(rows):
    errs = []
    for i, r in enumerate(rows, 2):
        for f, ok in ALLOWED.items():
            if r.get(f, "") not in ok:
                errs.append(f"{i}행 {f}={r.get(f)!r} 허용값 아님")
        rd = r.get("reversal_day", "")
        if rd not in ("", "미관찰", "미상") and not rd.isdigit():
            errs.append(f"{i}행 reversal_day={rd!r} 숫자/미관찰/미상 아님")
        if r.get("transfer_date"):
            try:
                dt.date.fromisoformat(r["transfer_date"])
            except ValueError:
                errs.append(f"{i}행 transfer_date 형식 오류")
        if r.get("outcome") and r["outcome"] != "미확인" and not r.get("followup_url"):
            errs.append(f"{i}행 outcome 있는데 followup_url 없음")
    return errs


if __name__ == "__main__":
    rows = read_csv(PATH)
    if not rows:
        write_csv(PATH, [], FIELDS)
        print(f"빈 템플릿 생성: {PATH}")
        sys.exit(0)
    errs = validate(rows)
    print("\n".join(errs) or f"OK: {len(rows)}행, case {len(dedupe(rows))}개")
    sys.exit(1 if errs else 0)
