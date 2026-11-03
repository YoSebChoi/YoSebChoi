"""임신 초기 증상(입덧·가슴통증 등)이 갑자기 사라져 불안해한 후기를 모아 이후 경과(출산/12주+ 유지/유산)를 추적

심장소리(심박수)를 먼저 확인한 뒤 증상이 사라진 본인 경험 글(cand=Y)만 경과를 따라간다.
판정 규칙은 시험관 출산 추적(birth.judge)과 같다: 출산 글(출산·분만·조리원 등, 날짜가 충분히 지난 것) → 출산,
12주 이상 진행이 제목으로 확인 → 12주+ 유지, 계류·유산·소파술 제목 → 유산?(본문을 읽고 확정).

data/symptom_cases.csv    : 검색으로 찾은 증상 소실 글. blog, url, postdate, week(글의 주수), symptom, ivf, hb(심장 언급), hbf(증상 문장보다
                            앞에 심장 확인), cand(심장 확인 뒤 증상이 사라진 본인 경험 글), auto(자동 판정), last_week, checked
data/symptom_outcomes.csv : 본문을 읽고 확정한 판정. blog, url, status(출산 / 유지12 / 유산 / 제외), note, checked
원문은 저장하지 않는다(URL·주수·키워드·판정만).

사용: python symptoms.py collect   # 검색 → 본문 확인(새 글 추가)
      python symptoms.py track     # cand 글의 이후 글로 자동 판정 → 확인할 케이스 출력(유지12인데 출산 제목이 보이는 글 포함, 확정은 직접)
      python symptoms.py show      # 확정 판정 집계
"""
import datetime as dt
import os
import re
import sys
from collections import Counter

import birth
from common import DATA, blog_search, canonical_url, parse_post_url, read_csv, strip_tags, write_csv
from fetch_posts import fetch
from followup import post_list
from natural import IVF

OUT = os.path.join(DATA, "symptom_cases.csv")
OUTCOMES = os.path.join(DATA, "symptom_outcomes.csv")
FIELDS = ["blog", "url", "postdate", "week", "symptom", "ivf", "hb", "hbf", "cand", "auto", "last_week", "checked"]
OF = ["blog", "url", "status", "note", "checked"]
QUERIES = ["임신 초기 증상 사라짐", "입덧 갑자기 사라졌어요 임신 초기", "임신 초기 입덧 없어짐 불안", "가슴통증 사라짐 임신 초기",
           "임신 증상 없어짐 걱정 초음파", "입덧 사라짐 심장소리", "임신 초기 증상 없어졌는데 괜찮을까", "6주 입덧 사라짐",
           "7주 증상 사라짐 걱정", "8주 입덧 없어짐 유산", "임신 초기 증상 갑자기 없어짐 출산", "가슴 말랑해짐 임신 초기 입덧 줄어듦",
           "임신증상 사라짐 계류 걱정", "증상이 사라졌어요 임신 5주", "증상 사라짐 9주 초음파 괜찮"]
QUERIES += [f"임신 {w}주 입덧 사라짐" for w in range(5, 13)] + [f"임신 {w}주 증상 사라짐 심장소리" for w in range(6, 12)]
QUERIES += ["심장소리 듣고 입덧 사라짐", "심장소리 확인 후 증상 없어짐 불안", "심박수 확인했는데 입덧이 없어졌어요", "입덧 사라져서 서브병원 심장소리",
            "입덧 사라짐 병원 갔더니 심장 잘 뛰어요", "가슴통증 사라져서 병원 갔더니 심장소리", "증상 사라짐 계류유산 후기 심장소리 들었는데",
            "심장소리 듣고도 유산 입덧 사라짐", "입덧 사라지고 유산 확인", "증상 사라져서 병원 갔더니 심장이 멈췄", "입덧 없어짐 출산 후기",
            "임신 초기 입덧 사라졌다 다시 돌아옴", "시험관 임신 입덧 사라짐 심장소리", "시험관 증상 사라짐 7주 심박수", "임신 초기 가슴통증 사라짐 후기",
            "임신 초기 증상 사라졌지만 출산했어요", "입덧 갑자기 없어졌는데 아기 잘 있어요", "입덧 갑자기 없어졌는데 유산이었어요"]
SYM = r"(입덧|구역|메스꺼|울렁|속\s*울렁|가슴\s*(통증|몽우리|뭉침|땡김|아픔|이\s*아프)|유방\s*통|피곤|졸림|졸려|임신\s*증상|증상|빈뇨|두통)"
GONE = r"(사라(졌|지|진|짐|져)|없어(졌|지|진|짐|져)|없네|없다|줄었|줄어(들|든|듦|서)|덜해|약해(졌|지)|안\s*(나|느껴|아파|아프|해)|뚝\s*(끊|그쳤)|신기하게\s*괜찮)"
RX = re.compile(SYM + r"[^.!?\n]{0,28}" + GONE)
BAD = re.compile(r"사라지면|없어지면|사라질\s*수|없어질\s*수|일반적|정상입니다|흔한|알려|원인|무조건|[?？]\s*$")
WEEK = re.compile(r"(\d{1,2})\s*주\s*(\d)?\s*일?")
HEARD = re.compile(r"(\d{2,3})\s*bpm|심장\s*(소리|박동|뛰)[^.\n]{0,12}(들|확인|보였|뛰|듣)|(들|확인)[^.\n]{0,10}심장\s*(소리|박동)")
# 일반 정보글 문장(안내·설명체)과 본인 경험 표현
GEN = re.compile(r"수\s*있|있습니다|가능성|일반적|걱정\s*(하지|마)|하세요|경우|합니다|됩니다|확인하세요|나타나|의심|주의|사람마다|개인차|해요\?")
PERS = re.compile(r"(나는|저는|제가|내가|나도|저도|우리|난|ㅠ|ㅜ|😭|ㅎㅎ|ㅋㅋ|했다|했어요|였다|였어요|더라|네요|었는데|다\.\s)")


def scan(blog, no, date):
    p = fetch(blog, no)
    txt = " ".join(b[1] if isinstance(b, list) else b for b in p.get("blocks", []) if not isinstance(b, list) or (len(b) > 1 and b[0] == "text"))
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
    first = hits[0]
    hb_pos = [h.start() for h in HEARD.finditer(txt)]
    hb_before = "Y" if any(p < first.start() for p in hb_pos) else "N"
    cand = "N"
    for m in hits:  # 심장 확인 뒤에 나오는, 본인 경험으로 쓴 증상 소실 문장
        if GEN.search(txt[m.start(): m.end() + 30]) or not PERS.search(txt[max(0, m.start() - 60): m.end() + 100]):
            continue
        cand = "Y" if hb_before == "Y" and any(p < m.start() for p in hb_pos) else "N"
        break
    sym = hits[0].group(1)
    hb = "Y" if re.search(r"심장\s*(소리|박동)|심박|bpm", txt) else "N"
    return {"week": max(set(ws), key=ws.count), "symptom": sym, "hb": hb, "hbf": hb_before, "cand": cand, "ivf": "Y" if IVF.search(p.get("title", "") + txt[:800]) else "N"}


def collect():
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
        except Exception:  # noqa: BLE001
            continue
        if r:
            old[url] = {"blog": ids[0], "url": url, "postdate": date, "auto": "", "last_week": "", "checked": "", **r}
            new += 1
    write_csv(OUT, sorted(old.values(), key=lambda r: r["postdate"], reverse=True), FIELDS)
    print(f"새 증상 소실 글 {new}건, 전체 {len(old)}건 (심장 확인 뒤 본인 경험 {sum(r['cand'] == 'Y' for r in old.values())}건)")


def _date(s):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s or "")
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def track(today=None):
    today = today or dt.date.today().isoformat()
    rows = read_csv(OUT)
    pts = birth.log_dates()  # logNo → 작성일 보간표(이 파일의 글 날짜도 더한다)
    pts += [(int(parse_post_url(r["url"])[1]), _date(r["postdate"]).toordinal()) for r in rows if _date(r["postdate"])]
    pts.sort()
    outs = {r["url"]: r for r in read_csv(OUTCOMES)}
    for r in rows:
        if r["cand"] != "Y":
            continue
        blog, no = parse_post_url(r["url"])
        start = _date(r["postdate"]) - dt.timedelta(days=int(r["week"]) * 7 - 19)  # 이식일(착상 무렵)에 해당하는 날로 환산
        items = None
        for _ in range(3):
            try:
                items = sorted((it for it in post_list(blog, pages=40, stop_at=int(no)) if it["logNo"] > int(no)), key=lambda it: it["logNo"])
                break
            except Exception:  # noqa: BLE001
                pass
        if items is None:
            continue
        st, wk, _ = birth.judge(items, start, pts)
        if st == "진행중" and wk.isdigit() and int(wk) >= 12:
            st = "유지12"
        r["auto"], r["last_week"], r["checked"] = st, wk, today
        o = outs.get(r["url"])
        if o and o["status"] == "유지12" and st == "출산":  # 제목만으로는 출산 전 글(막달 후기·준비 글)과 구분이 안 돼 읽고 바꾼다
            print("출산 확인 필요(확정은 유지12, 출산 제목이 보임)", r["url"])
        elif o and o["status"] in ("출산", "유지12") and st == "유산?":
            print("재확인 필요(확정은 출산·유지인데 유산 제목이 보임)", r["url"])
        elif not o and st in ("출산", "유지12", "유산?"):
            print(f"확인 필요(새 결과 {st}{' ' + wk + '주' if wk else ''})", r["url"])
    write_csv(OUT, rows, FIELDS)
    write_csv(OUTCOMES, list(outs.values()), OF)
    show()


def show():
    outs = read_csv(OUTCOMES)
    c = Counter(r["status"] for r in outs)
    ok, n = c["출산"] + c["유지12"], c["출산"] + c["유지12"] + c["유산"]
    print(f"확정: 출산 {c['출산']} · 12주+ 유지 {c['유지12']} · 유산 {c['유산']} → 출산·유지 {ok}/{n}"
          + (f" = {ok / n:.0%}" if n else "") + f" (제외 {c['제외']})")
    rows = read_csv(OUT)
    pend = [r for r in rows if r["cand"] == "Y" and r["url"] not in {o["url"] for o in outs}]
    print(f"아직 결과 없는 심장 확인 뒤 증상 소실 글 {len(pend)}건: {dict(Counter(r['auto'] or '미확인' for r in pend))}")


if __name__ == "__main__":
    {"collect": collect, "track": track, "show": show}[sys.argv[1]]()
