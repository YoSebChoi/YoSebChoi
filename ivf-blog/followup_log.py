"""3단계 후속 읽기 기록 — 이미 읽은 글을 다시 읽지 않도록 케이스별 판정 요약을 남긴다.
data/followup_log.csv: case_id, blog_id, checked(마지막 확인일), last_logno(그때까지 본 마지막 글),
  seen(후보로 본 글 수), outcome, outcome_week, followup_url, note(판정 근거 한 줄)
사용:
  python followup_log.py build              # cases.csv '후속:' 메모 + followup_queue.csv로 기록 생성/갱신
  python followup_log.py status [--unknown] # 케이스당 한 줄 요약(원문 재열람 없이 검토)
  python followup_log.py recheck [--all]    # 미확인(또는 전부) 케이스의 last_logno 이후 새 글만 조회
  python followup_log.py snip CASE_ID       # 아직 기록에 없는 새 후보 글만 결과 키워드 주변 짧게 출력
"""
import argparse
import datetime
import os
import re

from cases import PATH as CASES
from common import DATA, parse_post_url, read_csv, write_csv
from followup import OUT as QUEUE, OUTCOME_WORDS, post_list

LOG = os.path.join(DATA, "followup_log.csv")
FIELDS = ["case_id", "blog_id", "checked", "last_logno", "seen", "outcome", "outcome_week", "followup_url", "note"]
KW = re.compile(r"심장|심박|bpm|BPM|계류|화유|자궁외|졸업|소파|성별|니프티|\d+\s*주\s*\d+\s*일")


def _note(ambiguous):
    return " / ".join(p.split("후속:", 1)[1].strip() for p in ambiguous.split("; ") if "후속:" in p)


def build(today):
    cases = read_csv(CASES)
    queue = read_csv(QUEUE)
    old = {r["case_id"]: r for r in read_csv(LOG)}
    rows = []
    for c in cases:
        cq = [q for q in queue if q["case_id"] == c["case_id"]]
        if not cq and "후속:" not in c["ambiguous"] and c["case_id"] not in old:
            continue
        blog_id, log_no = parse_post_url(c["url"])
        prev = old.get(c["case_id"], {})
        last = max([int(log_no), int(prev.get("last_logno") or 0)] + [int(parse_post_url(q["url"])[1]) for q in cq])
        rows.append({"case_id": c["case_id"], "blog_id": blog_id, "checked": prev.get("checked") or today,
                     "last_logno": last, "seen": len(cq), "outcome": c["outcome"],
                     "outcome_week": c["outcome_week"], "followup_url": c["followup_url"], "note": _note(c["ambiguous"])})
    write_csv(LOG, rows, FIELDS)
    print(f"{len(rows)}건 → {LOG}")


def status(unknown):
    for r in read_csv(LOG):
        if unknown and r["outcome"] not in ("미확인", ""):
            continue
        print(f"{r['case_id']} | {r['outcome']} {r['outcome_week']} | {r['checked']} | {r['note'][:70]}")


def recheck(all_cases, today):
    log = read_csv(LOG)
    queue = read_csv(QUEUE)
    known = {q["url"] for q in queue}
    for r in log:
        if not all_cases and r["outcome"] not in ("미확인", ""):
            continue
        last = int(r["last_logno"])
        items = [it for it in post_list(r["blog_id"], stop_at=last) if it["logNo"] > last]
        new = [it for it in items if OUTCOME_WORDS.search(it["title"]) and it["url"] not in known]
        for it in new:
            queue.append({"case_id": r["case_id"], "url": it["url"], "title": it["title"], "date": today, "source": "recheck"})
        if items:
            r["last_logno"] = max(it["logNo"] for it in items)
        r["checked"] = today
        print(f"{r['case_id']}: 새 글 {len(items)}건, 후보 {len(new)}건")
    write_csv(QUEUE, queue, ["case_id", "url", "title", "date", "source"])
    write_csv(LOG, log, FIELDS)


def snip(case_id, limit=380):
    from fetch_posts import fetch
    r = next(x for x in read_csv(LOG) if x["case_id"] == case_id)
    for q in read_csv(QUEUE):
        if q["case_id"] != case_id or q["source"] != "recheck":
            continue
        p = fetch(*parse_post_url(q["url"]))
        body = " / ".join(re.sub(r"\s+", " ", t) for k, t in p["blocks"] if k == "text")
        out = " … ".join(body[max(0, m.start() - 40):m.end() + 40] for m in KW.finditer(body))
        print(f"--- {q['url']} | {p['title'][:40]} | {p['published'][:12]}\n  {out[:limit]}")
    print(f"(기존 판정: {r['outcome']} {r['outcome_week']} — {r['note'][:80]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "status", "recheck", "snip"])
    ap.add_argument("case_id", nargs="?")
    ap.add_argument("--unknown", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    today = datetime.date.today().isoformat()
    if a.cmd == "build":
        build(today)
    elif a.cmd == "status":
        status(a.unknown)
    elif a.cmd == "recheck":
        recheck(a.all, today)
    else:
        snip(a.case_id)


if __name__ == "__main__":
    main()
