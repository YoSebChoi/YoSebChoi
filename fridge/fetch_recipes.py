"""Downloads the 식품의약품안전처 「조리식품의 레시피 DB」 (식품안전나라 Open API, service COOKRCP01)
and writes fridge/data/foodsafety.json in the compact shape the app reads.

    FOODSAFETY_KEY=... python3 fridge/fetch_recipes.py
    python3 fridge/fetch_recipes.py --from raw.json    # parse a saved API answer (for testing)

The key is free: foodsafetykorea.go.kr → 공공데이터 활용 → 인증키 신청. Without it nothing is
downloaded and the app keeps the recipes it already has. Licence: 공공누리 제1유형 (출처표시).
"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "foodsafety.json"
API = "https://openapi.foodsafetykorea.go.kr/api/{key}/COOKRCP01/json/{start}/{end}"
PAGE = 1000   # the API's largest page

KIND = {"반찬": "반찬", "국&찌개": "국·찌개", "국": "국·찌개", "찌개": "국·찌개", "일품": "메인", "밥": "밥", "후식": "간식", "기타": "기타"}


def fetch_all(key):
    rows, start, total = [], 1, None
    while total is None or start <= total:
        url = API.format(key=key, start=start, end=start + PAGE - 1)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:   # the API is slow at times
                if attempt == 3:
                    raise
                print("retrying:", e)
                time.sleep(5 * (attempt + 1))
        body = data.get("COOKRCP01") or {}
        res = body.get("RESULT") or data.get("RESULT") or {}
        if res.get("CODE") not in (None, "INFO-000"):
            raise SystemExit(f"식품안전나라 API: {res.get('CODE')} {res.get('MSG')}")
        total = int(body.get("total_count") or 0)
        page = body.get("row") or []
        rows += page
        print(f"{len(rows)} / {total}")
        if not page:
            break
        start += PAGE
    return rows


def https(url):
    url = (url or "").strip()
    return re.sub(r"^http://", "https://", url) if url.startswith("http") else ""


SECTION = re.compile(r"^[\s●•·\-\[\(]*([가-힣A-Za-z ]{1,10}?)\s*[\]\)]?\s*[:：]\s*")
AMOUNT = re.compile(r"^(.*?[가-힣A-Za-z\)])\s*([\d½⅓¼⅔¾][\s\S]*|약간|적당량|조금|소량|한\s*줌|약\s*[\d][\s\S]*)$")


def parse_parts(text, name):
    """「재료 연두부 75g(3/4모), 달걀 30g(1/2개)\n양념 간장 5g(1작은술)」 → [[이름, 분량, 구분]]"""
    out, section = [], ""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"\[([가-힣 ]{1,10})\]", r"\n\1: ", text)   # 「적당량[조림장]간장 1g」
    for line in re.split(r"[\n\r]+", text):
        line = line.strip()
        if not line or line == name:
            continue
        m = SECTION.match(line)
        if m:
            section, line = m.group(1).strip(), line[m.end():]
        elif "," not in line and not re.search(r"\d", line) and len(line) <= 12 and not AMOUNT.match(line):
            section = line.strip("●•·[]() ")   # a heading line such as 「고명」 or 「양념장」
            continue
        # a section that starts mid-line: 「베이비채소 5 소스: 마요네즈 4」
        line = re.sub(r"\s+([가-힣]{1,6})\s*[:：]\s*", r", \1: ", line)
        # commas inside parentheses belong to the amount: 「두부 100g(1/3모, 부침용)」
        for item in re.split(r",(?![^()]*\))", line):
            item = item.strip(" ●•·\t")
            m = SECTION.match(item) or re.match(r"^\(([가-힣 ]{1,8})\)\s*", item)   # 「(반죽재료) 강력분」
            if m:
                section, item = m.group(1).strip(), item[m.end():].strip()
            if not item:
                continue
            m = AMOUNT.match(item)
            nm, amt = (m.group(1), m.group(2)) if m else (item, "")
            # 「양파(20g)」: the amount in brackets after the name
            m = re.fullmatch(r"(.+?)\s*\(([\d½⅓¼⅔¾][^()]*|약간|적당량|조금)\)", nm)
            if m and not amt:
                nm, amt = m.group(1), m.group(2)
            # 「돼지고기(통삼겹살, 200g)」, 「갈치(70g(1토막))」: whatever has a number in the brackets is the amount
            m = re.fullmatch(r"([^()]+?)\s*\((.*\d.*)\)\.?", nm)
            if m and not amt:
                nm, amt = m.group(1), m.group(2)
            nm = nm.rstrip(". ")
            # 「대구살 60」: grams without the unit
            if re.fullmatch(r"[\d.]+", amt):
                amt += "g"
            nm = re.sub(r"^\[[^\]]*\]\s*|^\(?\d+\s*인분\)?\s*(기준)?\s*", "", nm)   # 「[2인분] 밥」
            nm = re.sub(r"^(재료|주재료|부재료|양념|소스|고명)\s+", "", nm).strip()
            if 0 < len(nm) <= 20:
                out.append([nm, amt.strip(), section if section not in ("재료", "주재료", "필수재료", "기본재료") else ""])
    return out


def clean_step(s):
    s = re.sub(r"\s*\n\s*", " ", s or "")   # the DB wraps lines inside a step
    s = re.sub(r"^\s*\d+\s*[.)]\s*", "", s).strip()
    s = re.sub(r"\s*\([a-z]\)\s*$", "", s)   # 「…굽는다. (c)」
    return re.sub(r"(?<=[가-힣.)])\s*[a-z]$", "", s).strip()   # the DB ends many steps with a stray letter


def convert(rows):
    recipes = []
    for r in rows:
        name = (r.get("RCP_NM") or "").strip()
        if not name:
            continue
        steps = []
        for i in range(1, 21):
            t = clean_step(r.get(f"MANUAL{i:02d}"))
            if t:
                steps.append([t, https(r.get(f"MANUAL_IMG{i:02d}"))])
        ing = parse_parts(r.get("RCP_PARTS_DTLS"), name)
        if not steps or not ing:
            continue
        num = lambda k: round(float(r.get(k) or 0)) if re.fullmatch(r"[\d.]+", str(r.get(k) or "").strip()) else None
        recipes.append({
            "id": "fs" + str(r.get("RCP_SEQ") or len(recipes)),
            "n": name,
            "k": KIND.get((r.get("RCP_PAT2") or "").strip(), "기타"),
            "w": (r.get("RCP_WAY2") or "").strip(),
            "img": https(r.get("ATT_FILE_NO_MK") or r.get("ATT_FILE_NO_MAIN")),
            "kcal": num("INFO_ENG"), "na": num("INFO_NA"), "pro": num("INFO_PRO"),
            "ing": ing,
            "steps": steps,
            "tip": (r.get("RCP_NA_TIP") or "").strip(),
            "tag": (r.get("HASH_TAG") or "").strip(),
        })
    recipes.sort(key=lambda x: x["n"])
    return recipes


def main():
    if "--from" in sys.argv:
        raw = json.loads(Path(sys.argv[sys.argv.index("--from") + 1]).read_text(encoding="utf-8"))
        rows = (raw.get("COOKRCP01") or {}).get("row") or []
    else:
        key = os.environ.get("FOODSAFETY_KEY", "").strip()
        if not key:
            print("FOODSAFETY_KEY is not set: keeping the recipes already in fridge/data/")
            return
        try:
            rows = fetch_all(key)
        except Exception as e:   # the API is down now and then: keep what we have, try again next time
            print(f"::warning::식품안전나라 API를 받지 못했어요 ({e}). 지금 있는 레시피를 그대로 써요.")
            return
    recipes = convert(rows)
    if len(recipes) < 0.8 * len(rows) or not recipes:
        raise SystemExit(f"only {len(recipes)} of {len(rows)} recipes could be read: not replacing the data")
    OUT.parent.mkdir(exist_ok=True)
    payload = {"source": "식품의약품안전처 식품안전나라 조리식품의 레시피 DB", "updated": time.strftime("%Y-%m-%d"), "recipes": recipes}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(recipes)} recipes to {OUT.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
