"""임신 초기 증상(입덧·가슴통증 등)이 갑자기 사라져 불안해한 후기를 모아 이후 경과(출산/유산/진행중)를 추적

data/symptom_cases.csv : blog, url, postdate, week(증상이 사라진 주수), symptom, hb(그 글에서 심장소리 확인 여부 Y/N), status, last_week, manual
원문은 저장하지 않는다(URL·주수·키워드·판정만).

사용: python symptoms.py run      # 검색 → 본문 확인 → 이후 글로 경과 판정
      python symptoms.py show
"""
import os
import re
import sys

from birth import LOSS
from common import DATA, blog_search, canonical_url, parse_post_url, read_csv, strip_tags, write_csv
from fetch_posts import fetch
from natural import IVF, judge_titles
from followup import post_list

OUT = os.path.join(DATA, "symptom_cases.csv")
FIELDS = ["blog", "url", "postdate", "week", "symptom", "ivf", "hb", "status", "last_week", "manual"]
QUERIES = ["임신 초기 증상 사라짐", "입덧 갑자기 사라졌어요 임신 초기", "임신 초기 입덧 없어짐 불안", "가슴통증 사라짐 임신 초기",
           "임신 증상 없어짐 걱정 초음파", "입덧 사라짐 심장소리", "임신 초기 증상 없어졌는데 괜찮을까", "6주 입덧 사라짐",
           "7주 증상 사라짐 걱정", "8주 입덧 없어짐 유산", "임신 초기 증상 갑자기 없어짐 출산", "가슴 말랑해짐 임신 초기 입덧 줄어듦",
           "임신증상 사라짐 계류 걱정", "증상이 사라졌어요 임신 5주", "증상 사라짐 9주 초음파 괜찮"]
SYM = r"(입덧|구역|메스꺼|울렁|속\s*울렁|가슴\s*(통증|몽우리|뭉침|땡김|아픔|이\s*아프)|유방\s*통|피곤|졸림|졸려|임신\s*증상|증상|빈뇨|두통)"
GONE = r"(사라(졌|지|진|짐|져)|없어(졌|지|진|짐|져)|없네|없다|줄었|줄어(들|든|듦|서)|덜해|약해(졌|지)|안\s*(나|느껴|아파|아프|해)|뚝\s*(끊|그쳤)|신기하게\s*괜찮)"
RX = re.compile(SYM + r"[^.!?\n]{0,28}" + GONE)
BAD = re.compile(r"사라지면|없어지면|사라질\s*수|없어질\s*수|일반적|정상입니다|흔한|알려|원인|무조건|[?？]\s*$")
WEEK = re.compile(r"(\d{1,2})\s*주\s*(\d)?\s*일?")


def scan(blog, no, date):
    p = fetch(blog, no)
    txt = " ".join(p.get("blocks", []))
    if not txt or len(txt) < 200:
        return None
    hits = []
    for m in RX.finditer(txt):
        s = txt[max(0, m.start() - 40): m.end() + 40]
        if BAD.search(txt[m.start(): m.end() + 10]):
            continue
        hits.append(m)
    if not hits:
        return None
    ws = [int(w.group(1)) for w in WEEK.finditer(p.get("title", "") + " " + txt[:1500]) if 4 <= int(w.group(1)) <= 11]
    if not ws:
        return None
    worry = bool(re.search(r"불안|걱정|무서|두려|유산|계류|심란", txt))
    if not worry:
        return None
    sym = hits[0].group(1)
    hb = "Y" if re.search(r"심장\s*(소리|박동)|심박|bpm", txt) else "N"
    return {"week": max(set(ws), key=ws.count), "symptom": sym, "hb": hb, "ivf": "Y" if IVF.search(p.get("title", "") + txt[:800]) else "N"}


def run():
    old = {r["url"]: r for r in read_csv(OUT)}
    cands = {}
    for q in QUERIES:
        for start in (1, 101):
            try:
                items = blog_search(q, start=start, display=100).get("items", [])
            except Exception as e:  # noqa: BLE001
                print("검색 실패", q, e)
                break
            for it in items:
                ids = parse_post_url(it.get("link", ""))
                if ids and it.get("postdate", "") >= "20210101" and "원인" not in strip_tags(it["title"]):
                    cands[canonical_url(*ids)] = (ids, it.get("postdate", ""))
            if len(items) < 100:
                break
    print("후보", len(cands))
    new = 0
    for url, (ids, date) in cands.items():
        if url in old:
            continue
        try:
            r = scan(ids[0], ids[1], date)
        except Exception as e:  # noqa: BLE001
            continue
        if r:
            old[url] = {"blog": ids[0], "url": url, "postdate": date, "status": "", "last_week": "", "manual": "", **r}
            new += 1
    print("증상 소실 글", new)
    for r in old.values():
        if r["manual"] or r["status"] in ("출산",):
            continue
        start = int(parse_post_url(r["url"])[1])
        items = None
        for _ in range(3):
            try:
                items = [it for it in post_list(r["blog"], pages=40, stop_at=start) if it["logNo"] > start]
                break
            except Exception:  # noqa: BLE001
                pass
        if items is None:
            continue
        st, wk, _ = judge_titles(sorted(items, key=lambda it: it["logNo"]))
        r["status"], r["last_week"] = st, wk
    write_csv(OUT, sorted(old.values(), key=lambda r: r["postdate"], reverse=True), FIELDS)
    from collections import Counter
    print(Counter(r["status"] for r in old.values()))


if __name__ == "__main__":
    run()
