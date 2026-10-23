"""심장소리 확인 케이스의 출산 여부 추적 — 같은 블로그의 이후 글 '제목'만 보고 판정해 data/birth_log.csv에 한 줄씩 남긴다.

status
  출산      이후 글 제목에 출산·분만·조리원 입소·생후 N개월 등 출산 이후 표현
            (글 작성일이 이식 후 충분히 지난 것만 — 이전 아이 육아 글, 백일해 접종·출산 준비물 글 배제)
  유산      심장소리 확인 뒤 계류·사산·중기유산 등(심장소리 전 유산은 이미 실패로 분류됨)
  진행중    출산 표현 없이 임신 주수 글만 있음(last_week = 제목에 나온 가장 큰 주수)
  추적불가  이후 임신 관련 글이 없음
due_passed  출산 예정일(이식일 + 261일 전후)이 오늘 이전인지 — 아직 예정일 전이면 출산 여부를 판단할 수 없다.

사용: python birth.py collect   # 블로그 글 목록 수집(이미 수집한 블로그는 캐시 사용)
      python birth.py review    # 자동 판정 중 확인이 필요한 줄만 제목과 함께 출력
      python birth.py set < 줄   # case_id|status|last_week|근거(짧게)  수동 판정 기록
"""
import bisect
import datetime as dt
import json
import os
import re
import sys

from cases import PATH as CASES
from common import CACHE, DATA, parse_post_url, read_csv, write_csv
from followup import post_list

LOG = os.path.join(DATA, "birth_log.csv")
FIELDS = ["case_id", "embryo_day", "reversal_day", "case_date", "due_date", "due_passed", "status", "last_week",
          "evidence", "evidence_url", "checked", "manual"]
CDIR = os.path.join(CACHE, "birth")
# (패턴, 이식일 기준 최소 경과일) — 경과일보다 이른 글은 이전 아이 이야기로 보고 무시
BIRTH = [(re.compile(r"출산\s*(후기|기록|일기|했|완료|D\+)|분만\s*(후기|기록)|자연분만|브이백|유도분만|"
                     r"제왕절개\s*(후기|출산|\d일차|수술\s*후)|응급\s*제왕|태어났|탄생|지구\s*상륙|"
                     r"조리원\s*(\d주|후기|입소|생활|퇴소|일상|\d일)|\d+\s*주\s*\d*\s*일?\s*(출산|조산)|"
                     r"신생아\s*(시기|졸업|집\s*적응)|젖몸살|유축|모유\s*수유|육아\s*일기"), 140),
         (re.compile(r"생후\s*\d+\s*일|\d+\s*일\s*(차\s*)?아기|백일(?!해)|[1-3]\s*개월\s*아기"), 280),
         (re.compile(r"생후\s*\d+\s*개월|[4-9]\s*개월\s*(아기|육아)|1[0-1]\s*개월\s*(아기|육아)"), 360),
         (re.compile(r"돌잔치|돌끝|\d{2}\s*개월\s*(아기|육아)"), 600)]
# 출산 '전' 준비·계획 글(출산가방, 유도분만 날짜, 자연분만 고민 등)은 출산 근거로 쓰지 않는다
PLAN = re.compile(r"가방|준비|택일|고민|욕심|가능할까|앞둔|날짜|결정|교육|막달\s*운동|전날|하루\s*전|D-|예약|도치맘")
LOSS = re.compile(r"계류|(?<!습관성 )유산(?!균)|사산|심정지|심장\s*멈|소파|중기\s*유산|임신\s*종결")
WEEK = re.compile(r"(\d{1,2})\s*주")


def case_date(c, cands):
    if c.get("transfer_date"):
        return dt.date.fromisoformat(c["transfer_date"])
    pd = cands.get(c["url"], "")
    if len(pd) == 8:
        d = dt.date(int(pd[:4]), int(pd[4:6]), int(pd[6:]))
        back = int(c["reversal_day"]) if c.get("reversal_day", "").isdigit() else 15
        return d - dt.timedelta(days=back)
    return None


def titles_after(blog, log_no):
    os.makedirs(CDIR, exist_ok=True)
    p = os.path.join(CDIR, f"{blog}.json")
    if os.path.exists(p):
        items = json.load(open(p, encoding="utf-8"))
    else:
        items = post_list(blog, pages=40, stop_at=int(log_no))
        json.dump(items, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return sorted((it for it in items if it["logNo"] > int(log_no)), key=lambda it: it["logNo"])


def log_dates():
    """후보 글의 (logNo, 작성일)로 logNo → 대략적 작성일 보간용 표를 만든다(post-list에는 날짜가 없음)."""
    pts = []
    for r in read_csv(os.path.join(DATA, "candidates.csv")):
        n, d = parse_post_url(r["url"])[1], r["postdate"]
        if len(d) == 8:
            pts.append((int(n), dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).toordinal()))
    pts.sort()
    return pts


def est_date(pts, log_no):
    i = bisect.bisect_left(pts, (log_no, 0))
    if i == 0 or i == len(pts):
        return dt.date.fromordinal(pts[min(i, len(pts) - 1)][1])
    (a, da), (b, db) = pts[i - 1], pts[i]
    return dt.date.fromordinal(round(da + (db - da) * (log_no - a) / max(1, b - a)))


def judge(items, start=None, pts=None):
    def ok(it, min_days):
        return start is None or (est_date(pts, it["logNo"]) - start).days >= min_days
    birth = next((it for it in items for rx, md in BIRTH if rx.search(it["title"]) and not PLAN.search(it["title"]) and ok(it, md)), None)
    if birth:
        return "출산", "", birth
    weeks = [(int(m.group(1)), it) for it in items if not ok(it, 300)
             for m in WEEK.finditer(it["title"]) if 4 <= int(m.group(1)) <= 42]
    loss = next((it for it in items if LOSS.search(it["title"]) and not ok(it, 280)), None)  # 다음 임신 이야기는 제외
    if loss:
        return "유산?", "", loss
    if weeks:
        w, it = max(weeks, key=lambda x: x[0])
        return "진행중", str(w), it
    return "추적불가", "", None


def keyword(status, week, ev):
    """근거로 제목 전체 대신 판정에 쓴 표현만 남긴다(원문 저장 안 함)."""
    if not ev:
        return ""
    if status == "진행중":
        return f"{week}주"
    rxs = [rx for rx, _ in BIRTH] if status == "출산" else [LOSS]
    m = next((m for rx in rxs for m in [rx.search(ev["title"])] if m), None)
    return m.group(0) if m else ""


def collect():
    today = dt.date.today()
    cands = {r["url"]: r["postdate"] for r in read_csv(os.path.join(DATA, "candidates.csv"))}
    old = {r["case_id"]: r for r in read_csv(LOG)}
    pts = log_dates()
    rows = []
    for c in read_csv(CASES):
        if c["outcome"] != "심장소리확인" or c["embryo_day"] not in ("3", "4", "5"):
            continue
        prev = old.get(c["case_id"])
        if prev and prev.get("manual"):
            prev["evidence"] = ""  # 수동 판정은 manual 칸의 메모가 근거
            rows.append(prev)
            continue
        blog, log_no = parse_post_url(c["url"])
        if c.get("followup_url"):
            log_no = str(min(int(log_no), int(parse_post_url(c["followup_url"])[1])))
        d = case_date(c, cands)
        status, week, ev = judge(titles_after(blog, log_no), d, pts)
        due = d + dt.timedelta(days=261 + (5 - int(c["embryo_day"]))) if d else None
        rows.append({"case_id": c["case_id"], "embryo_day": c["embryo_day"], "reversal_day": c["reversal_day"],
                     "case_date": d.isoformat() if d else "", "due_date": due.isoformat() if due else "",
                     "due_passed": "" if not due else ("Y" if due <= today else "N"), "status": status,
                     "last_week": week, "evidence": keyword(status, week, ev), "evidence_url": ev["url"] if ev else "",
                     "checked": today.isoformat(), "manual": ""})
    write_csv(LOG, rows, FIELDS)
    print(f"{len(rows)}건 → {LOG}")


def review():
    for r in read_csv(LOG):
        if r["manual"]:
            continue
        if r["status"] in ("유산?", "추적불가") or (r["status"] == "진행중" and r["due_passed"] == "Y"):
            print(f"{r['case_id']} | {r['status']} {r['last_week']} | 예정일 {r['due_date']} | {r['evidence']} {r['evidence_url']}")


def after_hb():
    """심장소리 확인 케이스의 결과 — 출산 / 유지12(출산 글은 없지만 12주 이상까지 유지 확인) / 유산 / ''(미상).
    심장소리 후 유산은 대부분 7~10주에 일어나므로, 12주를 넘긴 진행 중 케이스를 '초기 유산 없이 넘김'으로 센다.
    (예정일이 지난 케이스만 세면 결과가 일찍 확정되는 유산만 들어가 출산 비율이 낮게 치우친다.)"""
    out = {}
    for r in read_csv(LOG):
        if r["status"] in ("출산", "유산"):
            out[r["case_id"]] = r["status"]
        elif r["last_week"].isdigit() and int(r["last_week"]) >= 12:
            out[r["case_id"]] = "유지12"
        else:
            out[r["case_id"]] = ""
    return out


def set_manual():
    rows = read_csv(LOG)
    by = {r["case_id"]: r for r in rows}
    for line in sys.stdin:
        if not line.strip():
            continue
        cid, status, week, note = (line.rstrip("\n").split("|", 3) + [""] * 4)[:4]
        r = by[cid]
        r["status"] = status
        if week:
            r["last_week"] = week
        r["manual"] = note or "수동 확인"
    write_csv(LOG, rows, FIELDS)
    print("기록", sum(bool(r["manual"]) for r in rows))


if __name__ == "__main__":
    {"collect": collect, "review": review, "set": set_manual}[sys.argv[1]]()
