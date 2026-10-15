"""2·3단계 판정 보조 도구 — 원문 전체를 읽지 않고 필요한 문장만 짧게 보여 주고, 판정은 한 줄씩 기록한다.

토큰을 아끼는 순서:
  1) read    후보 글에서 '역전' 주변·날짜·결과 문장만 발췌(이미 review_log에 있는 글은 건너뜀)
  2) add     판정 한 줄(케이스) 또는 X 줄(제외)을 cases.csv / review_log.csv에 기록
  3) titles  미확인 케이스의 후속 글 '제목'만 한 줄로 — 대부분 제목만으로 결과 판정 가능
  4) snip    제목으로 애매한 케이스만 후속 글에서 결과 문장 발췌
  5) outcome 결과 한 줄 기록(후속 글은 제목 키워드로 지정) → 이후 followup_log.py build
판정 근거는 evidence / ambiguous('후속: …', '나이: …')에 남으므로 다시 볼 때는 cases.csv·followup_log.csv만 보면 된다.

사용:
  python review.py read START END --day 4 [--auto] [--reopen 정규식]
  python review.py add --day 4 < lines      # idx|신선/동결|이식일|basis|역전일|결과|쌍둥이|근거[|애매|후속URL]  또는  X|idx|사유
  python review.py titles --day 4
  python review.py snip CASE_ID ...
  python review.py outcome < lines          # case_id|결과|주수|제목키워드|쌍둥이|메모
"""
import argparse
import json
import os
import re
import sys

from cases import FIELDS, PATH as CASES
from common import CACHE, DATA, parse_post_url, read_csv, write_csv

CANDS = os.path.join(DATA, "candidates.csv")
LOG = os.path.join(DATA, "review_log.csv")
QUEUE = os.path.join(DATA, "followup_queue.csv")
OUTCOME_KW = re.compile(r"심장|심박|bpm|계류|화유|화학적|자궁외|졸업|소파|고사|유산|아기집|난황|\d+\s*주\s*\d*\s*일")


def day_re(day):
    extra = {"3": r"|분할\s*배아|8세포|초기\s*배아", "4": r"|상실배|모룰라|3일\s*동결\S*\s*(후|하고)\s*1일"}.get(day, "")
    return re.compile(rf"(?<!\d){day}일\s*(배아|배양|배|짜리|된|째\s*배아)|(?<!\d){day}일배{extra}")


def body_of(url):
    b, n = parse_post_url(url)
    p = os.path.join(CACHE, "posts", f"{b}_{n}.json")
    if not os.path.exists(p):
        return None, None
    d = json.load(open(p, encoding="utf-8"))
    text = " / ".join(t for k, t in d["blocks"] if k == "text")
    return d, re.sub(r"[​﻿]", "", re.sub(r"\s+", " ", text))


def spans(body, pats, cap):
    sp = []
    for rx, w, n in pats:
        for m in list(rx.finditer(body))[:n]:
            sp.append([max(0, m.start() - w), min(len(body), m.end() + w)])
    sp.sort()
    out = []
    for a, b in sp:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return " … ".join(body[a:b] for a, b in out)[:cap]


def cmd_read(a):
    rows = read_csv(CANDS)
    log = read_csv(LOG)
    reopen = re.compile(a.reopen) if a.reopen else None
    done = {r["url"] for r in log if not (reopen and reopen.search(r["reason"]))}
    dre = day_re(a.day)
    pats = [(re.compile("역전"), 80, 12),
            (re.compile(r"이식(일|날)?\s*(은|:)?\s*\d+\s*[/월.]\s*\d+|\d+\s*[/월]\s*\d+\s*일?\s*(신선|동결)?\s*이식"), 40, 3),
            (re.compile(r"심장|심박|계류|화유|화학적|자궁외|아기집|난황"), 30, 3),
            (re.compile(r"만\s*\d{2}\s*세|\d{2}\s*살|년생|노산|고령"), 25, 1)]
    for i in range(a.start, min(a.end, len(rows))):
        r = rows[i]
        if r["url"] in done:
            continue
        d, body = body_of(r["url"])
        if body is None:
            continue
        if a.auto:
            if "역전" not in body:
                print(f"X|{i}|역전 언급 없음")
            elif not dre.search(body + d["title"]):
                print(f"X|{i}|{a.day}일배아 아님")
            continue
        if "역전" not in body or not dre.search(body + d["title"]):
            continue
        e = dre.search(body)
        emb = body[max(0, e.start() - 30):e.end() + 30] if e else ""
        b, n = parse_post_url(r["url"])
        print(f"\n#{i} {b}/{n} | {d['title'][:50]} | {d['published'][:12]}\n 배아: {emb}\n {spans(body, pats, 900)}")


def cmd_add(a):
    cands = read_csv(CANDS)
    cases = read_csv(CASES)
    log = read_csv(LOG)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        p = line.split("|")
        if p[0] == "X":
            url, status, reason = cands[int(p[1])]["url"], "제외", "|".join(p[2:])
            cases = [c for c in cases if c["url"] != url]
        else:
            p += [""] * 10
            idx, tt, date, basis, rev, out, tw, ev, amb, fu = p[:10]
            url = cands[int(idx)]["url"]
            row = {f: "" for f in FIELDS}
            row.update(url=url, embryo_day=a.day, transfer_type=tt or "불명", transfer_date=date,
                       count_basis=basis or "불명", day_from_transfer=rev if rev.isdigit() else "",
                       test_d13="기록없음", test_d14="기록없음", test_d15="기록없음", reversal_day=rev,
                       evidence=ev, outcome=out or "미확인", twins=tw or "불명", ambiguous=amb)
            if a.day == "5":  # 5일배는 test_dN을 직접 채우므로 기본값을 비워 둔다
                row.update(test_d13="", test_d14="", test_d15="")
            b, n = parse_post_url(url)
            row["case_id"] = f"{b}_{date}" if date else f"{b}_{n}"
            row["followup_url"] = fu or (url if row["outcome"] not in ("", "미확인") else "")
            cases = [c for c in cases if c["url"] != url] + [row]
            status, reason = "case", row["case_id"]
        log = [r for r in log if r["url"] != url] + [{"url": url, "status": status, "reason": reason}]
    write_csv(CASES, cases, FIELDS)
    write_csv(LOG, log, ["url", "status", "reason"])
    print(f"cases {len(cases)} / reviewed {len(log)}")


def cmd_titles(a):
    q = read_csv(QUEUE)
    for c in read_csv(CASES):
        if (a.day and c["embryo_day"] != a.day) or c["outcome"] not in ("미확인", "") or "후속:" in c["ambiguous"]:
            continue
        t = [x["title"] for x in q if x["case_id"] == c["case_id"]]
        print(f"{c['case_id']} r{c['reversal_day']} [{len(t)}] " + " ‖ ".join(s[:34] for s in t[:8]))


def cmd_snip(a):
    from fetch_posts import fetch
    q = read_csv(QUEUE)
    t = re.compile(r"심장|계류|화유|자궁외|유산|소파|고사|졸업|주차|종결|결과|아기집|난황|초음파")
    for cid in a.case_ids:
        items = [x for x in q if x["case_id"] == cid]
        items = ([x for x in items if t.search(x["title"])] or items)[:3]
        print(f"##### {cid}")
        for it in items:
            p = fetch(*parse_post_url(it["url"]))
            body = re.sub(r"\s+", " ", " / ".join(x for k, x in p["blocks"] if k == "text"))
            print(f" -- {it['url'][-15:]} {p['title'][:40]} | {p['published'][:12]}\n   "
                  + spans(body, [(OUTCOME_KW, 35, 40)], 450))


def cmd_outcome(a):
    q = read_csv(QUEUE)
    rows = read_csv(CASES)
    by = {r["case_id"]: r for r in rows}
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        p = line.split("|")
        cid, out, wk, kw, tw, note = (p[:5] + ["|".join(p[5:])]) if len(p) >= 6 else (p + [""] * 6)[:6]
        url = ""
        if kw:
            m = [x["url"] for x in q if x["case_id"] == cid and kw in x["title"]]
            if not m:
                print(f"!! 후속 글 제목 못 찾음: {cid} '{kw}'")
                continue
            url = m[0]
        r = by[cid]
        if out:
            r["outcome"] = out
        if wk:
            r["outcome_week"] = wk
        if url:
            r["followup_url"] = url
        if tw:
            r["twins"] = tw
        if note:
            r["ambiguous"] = (r["ambiguous"] + "; " if r["ambiguous"] else "") + "후속: " + note
    write_csv(CASES, rows, FIELDS)
    print("미확인 남음", sum(r["outcome"] in ("미확인", "") for r in rows))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("start", type=int)
    r.add_argument("end", type=int)
    r.add_argument("--day", default="5")
    r.add_argument("--auto", action="store_true")
    r.add_argument("--reopen", help="review_log 사유가 이 정규식에 맞는 제외 글을 다시 보여 줌")
    ad = sub.add_parser("add")
    ad.add_argument("--day", default="5")
    t = sub.add_parser("titles")
    t.add_argument("--day")
    s = sub.add_parser("snip")
    s.add_argument("case_ids", nargs="+")
    sub.add_parser("outcome")
    a = ap.parse_args()
    {"read": cmd_read, "add": cmd_add, "titles": cmd_titles, "snip": cmd_snip, "outcome": cmd_outcome}[a.cmd](a)


if __name__ == "__main__":
    main()
