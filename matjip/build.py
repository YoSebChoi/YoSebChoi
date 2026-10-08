#!/usr/bin/env python3
"""Build 노포 지도 (백년가게 · 백반기행 맛집 지도) into docs/matjip/ for GitHub Pages.

    python3 matjip/build.py            # geocode what is new, then build
    python3 matjip/build.py --offline  # build from the geocode cache only

Data lives in matjip/data/:
  - baekban.csv          백반기행 restaurants (상호, 주소, 메뉴, 방송, 출처)
  - baeknyeon_seed.csv   a few 백년가게 restaurants, used until the official list is added
  - any other *.csv      the official 백년가게 list from data.go.kr
                         (소상공인시장진흥공단_전국 백년가게 지정리스트 현황 정보);
                         column names are detected, and only restaurants are kept
  - geocode_cache.json   address -> [lat, lng], so each address is looked up once

Addresses are geocoded with the Kakao Local API when KAKAO_REST_KEY is set
(most accurate for Korean addresses), otherwise with OpenStreetMap Nominatim
(no key, one request per second).
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "matjip"
DATA = SRC / "data"
OUT = ROOT / "docs" / "matjip"
CACHE_FILE = DATA / "geocode_cache.json"
TV_FILE = DATA / "baekban_kakao.json"     # 백반기행 places from Kakao Map's broadcast info
KINDS_FILE = DATA / "baeknyeon_kinds.csv"   # 업체명,구분(음식점|기타) for names the rules cannot decide

BAEKBAN = "bb"     # 허영만의 백반기행
BAEKNYEON = "bn"   # 백년가게

# column name candidates, matched after removing spaces
COLS = {
    "name": ["상호", "상호명", "업체명", "가게명", "업소명", "점포명", "기업명", "사업장명", "식당명"],
    "addr": ["도로명주소", "주소", "업체주소", "가게주소", "점포주소", "소재지", "소재지주소", "사업장주소", "소재지도로명주소", "지번주소", "소재지지번주소"],
    "kind": ["업종", "업종명", "업태", "업종분류", "세부업종", "업종(세부)", "주요업종"],
    "menu": ["메뉴", "대표메뉴", "주메뉴", "주요메뉴", "주요품목", "주요상품", "취급품목", "대표품목"],
    "phone": ["전화", "전화번호", "연락처", "대표전화"],
    "year": ["지정연도", "지정년도", "선정연도", "선정년도", "지정일", "지정일자", "선정일"],
    "since": ["창업연도", "창업년도", "개업연도", "설립연도", "창업일", "개업일", "업력"],
    "episode": ["방송", "회차", "방송일"],
    "source": ["출처"],
    "lat": ["위도", "lat", "latitude", "y좌표"],
    "lng": ["경도", "lng", "lon", "longitude", "x좌표"],
}
FOOD = re.compile(r"음식|식당|한식|중식|일식|양식|분식|외식|주점|요리|제과|베이커리|빵|떡|국밥|면|고기|구이|횟집|회|카페|커피|다방|치킨|냉면|국수|김밥|만두|족발|찜|탕|갈비")
NOT_FOOD = re.compile(r"소매|도매|판매|수리|제조|이용|미용|세탁|사진|인쇄|철물|의류|양복|한복|안경|시계|서점|문구|약국|한약|공구|가구|침구|정비|목공|공방")

# When the list has no 업종 column (the 2026 file has only 업체명 · 업체주소 · 연락처),
# the store name decides; names it cannot decide are looked up in KINDS_FILE.
NAME_FOOD = re.compile(
    r"식당|음식|국밥|순대|냉면|면옥|밀면|막국수|국수|칼국수|해장국|설렁탕|설농탕|곰탕|육개장|갈비|불고기|숯불|구이|곱창|막창|족발|보쌈|"
    r"통닭|치킨|닭강정|닭갈비|닭발|닭한마리|삼계|추어|매운탕|감자탕|감자국|아구|아귀|물텀벙|복집|복국|복어|횟집|회집|회관|물회|장어|파전|"
    r"분식|반점|만두|완당|우동|소바|돈까스|돈가스|일식|초밥|스시|제과|베이커리|블랑제리|부랑제|과자|빵|떡집|떡방|찹쌀|단팥|빙수|"
    r"카페|커피|다방|다원|찻집|가든|보리밥|굴밥|산채|두부|순두부|청국장|전골|찜|짜글|찌개|백반|한정식|주막|선지|부대고기|오리|"
    r"한우|흑돼지|삼겹살|주물럭|식육식당|생고기|육회|오뎅|김밥|떡볶이|짬뽕|짜장|탕수육|양념|비빔|쌈밥|게장|낙지|쏘가리|송어|"
    r"다슬기|백숙|흑염소|해물|수제비|황태|고등어|호프|주점|포차|막걸리|피자|경양식|레스토랑|본가|할매|할머니|뚝배기|솥|휴게소|"
    r"식당$|집$|집\s|집\(|관$|관\s|옥$|옥\s|루$|각$|원$|춘$|정$|장$")
NAME_NOT = re.compile(
    r"이발관|미장원|수족관|직매장|사우나|감상실|상사|상회|스포츠|의료기|보청기|보조기|외국어|전자|한약|약방|약국|약업|서점|서림|서적|문고|문구|안경|미용|헤어|머리|바버|살롱|뷰티|"
    r"이용원|이용소|이용샵|양복|테일러|제화|신발|슈즈|한복|주단|이불|직물|실크|명주|의상|복장|가운|보석|주얼리|시계|사진|포토|스튜디오|"
    r"현상소|인쇄|필방|화방|한지|건재|건축|건설|자재|인테리어|조명|밸브|도기|철물|공구|카센타|카클리닉|카토피아|오토바이|자전거|바이크|"
    r"모터|정비|악기|음향|뮤직|사무기|금고|진열대|종묘|농약|영농|농원|농장|원예|분재|기름집|참기름|제유|방앗간|정육점|식육점|축산$|"
    r"수산$|수산\b|청과|건어물|젓갈|슈퍼|수퍼|마트|백화점|그릇|주방|꽃|플라워|화원|호스텔|모텔|여관|호텔|그린텔|학원|스쿨|교육|"
    r"태권도|체육사|화문석|보세|공업사|산업사|유통|소리사|사무소$|패션|공방|공예|목탁|가구|침구|세탁|크린|표구|갤러리|아트센타|도장|"
    r"열쇠|국기|상패|가발|애드벌룬|웨딩|폐백|혼수|장갑|타올|벨트|앵글|완구|가스|염전|개발|통상|총판|요$|기공사|TV|인삼|홍삼|파스텍|태양광")


def read_csv(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"{path.name}: cannot read the file's text encoding")
    rows = list(csv.reader(io.StringIO(text)))
    # some public files put a title line above the header; take the first row naming a store
    for i, row in enumerate(rows[:10]):
        keys = [c.replace(" ", "").strip() for c in row]
        if any(k in COLS["name"] for k in keys):
            return keys, rows[i + 1:]
    raise SystemExit(f"{path.name}: no store-name column (one of {', '.join(COLS['name'])})")


def pick(header, field):
    for cand in COLS[field]:
        if cand in header:
            return header.index(cand)
    return None


def clean_addr(a):
    a = re.sub(r"\s+", " ", (a or "").replace(" ", " ")).strip()
    a = re.sub(r"\(.*?\)", "", a).strip()          # (중동, 굿모닝프라자)
    # drop floor / building details after the building number: "… 37-1 1층" -> "… 37-1"
    m = re.match(r"^(.*?(?:로|길|대로)\s*\d+(?:-\d+)?(?:번길\s*\d+(?:-\d+)?)?)\b", a)
    if m:
        return m.group(1).strip()
    m = re.match(r"^(.*?\S+[동리가]\s*(?:산\s*)?\d+(?:-\d+)?)\b", a)   # 지번: "… 용수리 4021"
    return m.group(1).strip() if m else a.split(",")[0].strip()


def load(geo=None):
    stores = []
    files = sorted(DATA.glob("*.csv"))
    official = [f for f in files if f.name not in ("baekban.csv", "baeknyeon_seed.csv", KINDS_FILE.name)]
    kinds = {}
    if KINDS_FILE.exists():
        header, rows = read_csv(KINDS_FILE)
        kinds = {r[0].strip(): r[1].strip() == "음식점" for r in rows if len(r) > 1}
    for f in files:
        if f == KINDS_FILE:
            continue
        if f.name == "baeknyeon_seed.csv" and official:
            continue   # the official list covers these
        tag = BAEKBAN if f.name == "baekban.csv" else BAEKNYEON
        header, rows = read_csv(f)
        ix = {k: pick(header, k) for k in COLS}
        if ix["addr"] is None:
            raise SystemExit(f"{f.name}: no address column (one of {', '.join(COLS['addr'])})")
        kept = skipped = 0
        unknown = []
        for r in rows:
            get = lambda k: (r[ix[k]].strip() if ix[k] is not None and ix[k] < len(r) else "")
            name, addr = get("name"), get("addr")
            if not name or not addr:
                continue
            kind = get("kind")
            if tag == BAEKNYEON:
                if ix["kind"] is not None:
                    food = not ((NOT_FOOD.search(kind) or not FOOD.search(kind)) and not FOOD.search(get("menu")))
                else:
                    food = name_is_food(name, kinds)
                    if food is None and geo:
                        food = geo.kakao_is_food(name, addr)
                if food is None:
                    unknown.append(name)
                if not food:
                    skipped += 1
                    continue
            # "로쏘 주식회사(성심당)" -> "로쏘(성심당)": drop company-form words from the shown name
            shown = re.sub(r"\s*(주식회사|유한회사|농업회사법인|㈜|\(주\)|\(유\))\s*", " ", name)
            shown = re.sub(r"\s+(?=\()", "", re.sub(r"\s+", " ", shown)).strip() or name
            s = {"n": shown, "a": addr, "t": [tag]}
            for k, key in (("menu", "m"), ("phone", "p"), ("episode", "e"), ("source", "u"), ("kind", "k")):
                if get(k):
                    s[key] = get(k)
            year = re.search(r"(19|20)\d\d", get("year"))
            if year:
                s["y"] = int(year.group(0))
            since = re.search(r"(18|19|20)\d\d", get("since"))
            if since:
                s["s"] = int(since.group(0))
            try:
                lat, lng = float(get("lat")), float(get("lng"))
                if 33 < lat < 39 and 124 < lng < 132:
                    s["ll"] = [round(lat, 6), round(lng, 6)]
            except ValueError:
                pass
            stores.append(s)
            kept += 1
        print(f"{f.name}: {kept} restaurants" + (f", {skipped} non-restaurant stores left out" if skipped else ""))
        if unknown:
            print(f"  {len(unknown)} names could not be told apart as restaurants or not; add them to {KINDS_FILE.name}:")
            print("  " + " | ".join(unknown))
    stores += load_tv()
    return merge(stores)


def load_tv():
    """백반기행 restaurants collected from Kakao Map (see collect_tv)."""
    if not TV_FILE.exists():
        return []
    data = json.loads(TV_FILE.read_text(encoding="utf-8"))
    out = []
    for d in data["places"]:
        s = {"n": d["name"], "a": d["addr"], "t": [BAEKBAN], "ll": [d["lat"], d["lng"]]}
        if d.get("menu"):
            s["m"] = d["menu"]
        if d.get("phone"):
            s["p"] = d["phone"]
        if d.get("url"):
            s["u"] = d["url"]
        if d.get("cat"):
            s["c"] = d["cat"]
        out.append(s)
    print(f"{TV_FILE.name}: {len(out)} restaurants (Kakao Map, {data['keyword']}, {data['fetched']})")
    return out


KOREA = (124.5, 33.0, 131.0, 38.7)   # lng/lat box around South Korea


def collect_tv(geo, keyword="백반기행"):
    """Kakao Map tags places with the TV shows that featured them, and its keyword
    search matches those tags. One query returns at most 45 places, so the country
    is split into smaller boxes until every box returns all of its places."""
    found, calls = {}, 0

    def search(box, depth):
        nonlocal calls
        rect = ",".join(f"{v:.6f}" for v in box)
        page, total = 1, 0
        while True:
            url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode(
                {"query": keyword, "rect": rect, "page": page, "size": 15})
            res = geo._get(url, {"Authorization": f"KakaoAK {geo.kakao}"})
            calls += 1
            total = res["meta"]["total_count"]
            if total > 45 and depth < 10:
                break   # too many to page through here: split the box
            for d in res["documents"]:
                found[d["id"]] = d
            if res["meta"]["is_end"] or page == 3:
                return
            page += 1
        x1, y1, x2, y2 = box
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        for sub in ((x1, y1, mx, my), (mx, y1, x2, my), (x1, my, mx, y2), (mx, my, x2, y2)):
            search(sub, depth + 1)

    search(KOREA, 0)
    places = []
    for d in found.values():
        if d.get("category_group_code") not in ("FD6", "CE7"):   # restaurants and cafés only
            continue
        cat = d.get("category_name", "").split(" > ")
        places.append({
            "name": d["place_name"], "addr": d.get("road_address_name") or d.get("address_name", ""),
            "lat": round(float(d["y"]), 6), "lng": round(float(d["x"]), 6),
            "menu": cat[-1] if len(cat) > 1 else "", "cat": d.get("category_name", ""),
            "phone": d.get("phone", ""), "url": d.get("place_url", ""),
        })
    places.sort(key=lambda p: (p["addr"], p["name"]))
    TV_FILE.write_text(json.dumps({"keyword": keyword, "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                   "places": places}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"collected {len(places)} {keyword} restaurants from Kakao Map ({len(found)} places, {calls} searches)")


def name_is_food(name, kinds):
    """True / False from the name, or None when it cannot tell."""
    bare = re.sub(r"^\s*(주식회사|유한회사|농업회사법인|\(주\)|㈜|\(유\))\s*|\s*(주식회사|유한회사|\(주\)|㈜)\s*$", "", name).strip()
    if name in kinds:
        return kinds[name]
    if bare in kinds:
        return kinds[bare]
    # a strong food word wins over a shop word (역전통닭(닭사무소), 축산본점식육식당)
    if re.search(r"식당|회관|국밥|냉면|갈비|통닭|막국수|제과|베이커리|과자점|삼겹살|가든|게장|곰탕|매운탕|삼계탕", bare):
        return True
    if NAME_NOT.search(bare):
        return False
    if NAME_FOOD.search(bare):
        return True
    return None


PROVINCES = [("충청북", "충북"), ("충청남", "충남"), ("전라북", "전북"), ("전라남", "전남"), ("경상북", "경북"), ("경상남", "경남"),
             ("전남광주", "전남"), ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("광주", "광주"),
             ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"), ("강원", "강원"), ("충북", "충북"),
             ("충남", "충남"), ("전북", "전북"), ("전남", "전남"), ("경북", "경북"), ("경남", "경남"), ("제주", "제주")]


def province(name):
    """서울특별시/서울, 충청남도/충남 … → the short form."""
    for long, short in PROVINCES:
        if name.startswith(long):
            return short
    return name


def addr_key(a):
    """서울특별시/서울, 충청남도/충남 … spelled one way, spaces dropped."""
    a = clean_addr(a)
    first, _, rest = a.partition(" ")
    for long, short in PROVINCES:
        if first.startswith(long):
            first = short
            break
    return (first + rest).replace(" ", "")


# food kinds for the filter, from Kakao's category path, the menu and the name (first match wins)
GROUPS = [
    ("빵·카페", r"제과|베이커리|빵|카페|커피|다방|디저트|떡|과자|케익|케이크|빙수|단팥|찻집|다원|블랑제리"),
    ("중식", r"중식|중국|반점|짬뽕|짜장|탕수육|딤섬|만두"),
    ("일식·양식", r"일식|초밥|스시|돈까스|돈가스|양식|레스토랑|경양식|피자|이탈리|스테이크|소바|우동"),
    ("면", r"냉면|국수|칼국수|막국수|밀면|면옥|라면|쫄면|수제비|모밀|메밀|국시"),
    ("해산물", r"해물|생선|횟집|회집|회센터|물회|복집|복국|복어|아구|아귀|물텀벙|장어|낙지|게장|굴밥|조개|대게|꽃게|갈치|고등어|조기|굴비|"
              r"생태|동태|명태|황태|코다리|꼬막|전복|문어|오징어|쭈꾸미|주꾸미|새우|홍어|민어|짱뚱어|다슬기|재첩|매운탕|어죽|(^|\s)회(\s|$)"),
    ("국밥·탕", r"국밥|해장국|설렁탕|설농탕|곰탕|탕|찌개|전골|순대|추어|육개장|감자국|선지|국$"),
    ("고기", r"육류|고기|갈비|불고기|숯불|구이|곱창|막창|족발|보쌈|삼겹|한우|닭|오리|치킨|통닭|돼지|정육|식육|주물럭"),
    ("한식", r"한식|한정식|백반|정식|밥|두부|비빔|쌈|묵|산채|기사식당|식당|분식|김밥|떡볶이"),
]


def group_of(s):
    text = " ".join(filter(None, [s.get("c", "").replace("음식점 >", ""), s.get("m", ""), s["n"]]))
    return next((g for g, rx in GROUPS if re.search(rx, text)), "기타")


def norm_name(n):
    return re.sub(r"\s+|본점|\(.*?\)|식당$", "", n)


def merge(stores):
    """A place that is both a 백년가게 and on 백반기행 becomes one entry with both tags."""
    out, seen = [], {}
    for s in stores:
        # the same place is spelled differently across lists ("사직로 12길8" / "사직로12길 8",
        # "감골식당 성서본점" / "감골식당"), so match on the address without spaces and the
        # first two letters of the name
        key = (norm_name(s["n"])[:2], addr_key(s["a"]))
        if key in seen:
            prev = seen[key]
            for t in s["t"]:
                if t not in prev["t"]:
                    prev["t"].append(t)
            for k, v in s.items():
                prev.setdefault(k, v)
            continue
        seen[key] = s
        out.append(s)
    return out


class Geocoder:
    def __init__(self, offline):
        self.offline = offline
        self.kakao = os.environ.get("KAKAO_REST_KEY", "").strip()
        self.cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
        # "place:" lookups matched by address only; "place2:" replaced them
        self.cache = {k: v for k, v in self.cache.items() if not k.startswith("place:")}
        self.last = 0.0
        self.looked_up = 0

    def _get(self, url, headers):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if "kakao" in url and e.code in (401, 403):
                # a refused key fails every lookup: stop rather than publish a mostly empty map
                body = e.read().decode("utf-8", "replace")[:300]
                raise SystemExit(
                    f"Kakao refused the key (HTTP {e.code}): {body}\n"
                    "401: KAKAO_REST_KEY is not a REST API key (check 앱 > 플랫폼 키 > REST API 키, no spaces).\n"
                    "403: turn on 앱 > 제품 설정 > 카카오맵 > 사용 설정, and leave 허용 IP empty.")
            raise

    def _kakao(self, query, keyword=False):
        kind = "keyword" if keyword else "address"
        url = f"https://dapi.kakao.com/v2/local/search/{kind}.json?" + urllib.parse.urlencode({"query": query, "size": 1})
        docs = self._get(url, {"Authorization": f"KakaoAK {self.kakao}"}).get("documents", [])
        return [float(docs[0]["y"]), float(docs[0]["x"])] if docs else None

    def _nominatim(self, query):
        wait = 1.1 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": query, "format": "jsonv2", "countrycodes": "kr", "limit": 1, "accept-language": "ko"})
        hits = self._get(url, {"User-Agent": "nopo-map-builder/1.0 (github.com/YoSebChoi/YoSebChoi)"})
        return [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None

    def _find_place(self, name, addr, ll=None):
        """The Kakao place for a store: keyword search for "<시/도 시/군/구> <name>", kept when
        its road or lot address matches, or — the official lists often carry old or lot
        addresses — when it lies within 300 m of the store's location and the names agree."""
        region = " ".join(addr.split()[:2])
        url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode({"query": f"{region} {name}", "size": 10})
        docs = self._get(url, {"Authorization": f"KakaoAK {self.kakao}"}).get("documents", [])
        road = clean_addr(addr).split()[-2:]
        want = addr_key(addr)
        key = norm_name(name)[:2]

        def near(d):
            if not ll:
                return False
            dy = (float(d["y"]) - ll[0]) * 111000
            dx = (float(d["x"]) - ll[1]) * 111000 * 0.8
            return dx * dx + dy * dy < 300 * 300

        for d in docs:
            ra, ja = d.get("road_address_name") or "", d.get("address_name") or ""
            if want in (addr_key(ra), addr_key(ja)) or (ra and all(t in ra for t in road)) or (ja and all(t in ja for t in road)):
                return d
        return next((d for d in docs if near(d) and norm_name(d["place_name"]).startswith(key)), None)

    def kakao_place(self, name, addr, ll=None):
        """(checked, place) — place is {u, c, p} when Kakao lists the store at its address.
        A store Kakao does not list may have closed or moved. Looked up again after 60 days."""
        key = "place2:" + name + "@" + clean_addr(addr)   # place2: lookups that also match by location
        hit = self.cache.get(key)
        fresh = hit and (datetime.now(timezone.utc).date() - datetime.fromisoformat(hit["d"]).date()).days < 60
        if hit and (fresh or self.offline or not self.kakao):
            return True, hit["r"]
        if self.offline or not self.kakao:
            return False, None
        try:
            d = self._find_place(re.sub(r"\(.*?\)", "", name).strip() or name, addr, ll)
        except SystemExit:
            raise
        except Exception as e:
            print("  place lookup failed:", name, "-", e)
            return False, None
        r = d and {"u": d.get("place_url", ""), "c": d.get("category_name", ""), "p": d.get("phone", "")}
        self.cache[key] = {"d": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "r": r}
        return True, r

    def region(self, ll):
        """시도 / 시군구 / 법정동 of a location (Kakao coord2regioncode), so the app can list
        every place in a region the person searches for ("화성시 동탄구", "울산 동구")."""
        key = f"region:{ll[0]:.5f},{ll[1]:.5f}"
        if key in self.cache:
            return self.cache[key]
        if self.offline or not self.kakao:
            return None
        try:
            url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?" + urllib.parse.urlencode({"x": ll[1], "y": ll[0]})
            docs = self._get(url, {"Authorization": f"KakaoAK {self.kakao}"}).get("documents", [])
        except SystemExit:
            raise
        except Exception as e:
            print("  region lookup failed:", ll, "-", e)
            return None
        d = next((d for d in docs if d.get("region_type") == "B"), docs[0] if docs else None)
        r = d and [province(d["region_1depth_name"]), d["region_2depth_name"], d["region_3depth_name"]]
        self.cache[key] = r
        return r

    def kakao_is_food(self, name, addr):
        """Ask Kakao what kind of place this store is (음식점 FD6 / 카페 CE7); None without a key."""
        key = "kind:" + name + "@" + clean_addr(addr)
        if key in self.cache:
            return self.cache[key]
        if self.offline or not self.kakao:
            return None
        try:
            hit = self._find_place(name, addr)
        except SystemExit:
            raise
        except Exception as e:
            print("  kind lookup failed:", name, "-", e)
            return None
        food = None if hit is None else hit.get("category_group_code") in ("FD6", "CE7")
        self.cache[key] = food
        return food

    def locate(self, s):
        addr = clean_addr(s["a"])
        hit = self.cache.get(addr, False)
        # with a Kakao key, retry what OpenStreetMap missed or only placed on the street
        if hit is not False and not (self.kakao and not self.offline and (hit is None or len(hit) > 2)):
            return hit
        if self.offline:
            return None
        ll = None
        try:
            if self.kakao:
                ll = self._kakao(addr) or self._kakao(f"{addr.split(' ')[0]} {s['n']}", keyword=True)
            else:
                ll = self._nominatim(addr)
                # fall back to the road (without the building number), which OSM knows far more often
                road = re.sub(r"\s*\d+(-\d+)?$", "", addr)
                if not ll and road != addr:
                    ll = self._nominatim(road)
                    if ll:
                        ll.append(0)   # marks an approximate (street-level) location
        except Exception as e:   # network trouble: leave it for the next run
            print("  geocode failed:", addr, "-", e)
            return None
        self.looked_up += 1
        if ll:
            ll = [round(ll[0], 6), round(ll[1], 6)] + ll[2:]
        self.cache[addr] = ll   # a miss is cached as null so it is not retried every run
        if self.looked_up % 25 == 0:
            self.save()
            print(f"  {self.looked_up} addresses looked up…")
        return ll

    def save(self):
        CACHE_FILE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


MANIFEST = {
    "name": "노포 지도",   # shown under the icon on older launch screens: keep it short
    "short_name": "노포 지도",
    "description": "내 주변 또는 지도에서 고른 곳 근처의 백년가게와 허영만의 백반기행 맛집을 찾아요.",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#12161c",
    "theme_color": "#12161c",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

SW = """// 노포 지도 service worker: the app shell is served from cache; the store list
// is fetched fresh when online and falls back to the cached copy offline.
const CACHE = "nopo-map-__VERSION__";
const SHELL = ["./", "./index.html", "./stores.json", "./manifest.webmanifest", "./icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, { cache: "reload" })))));
});
self.addEventListener("message", e => { if (e.data === "skip-waiting") self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith("nopo-map-") && k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  if (req.mode === "navigate") {
    e.respondWith(caches.open(CACHE).then(c => c.match("./index.html")).then(hit => hit || fetch(req)));
    return;
  }
  if (url.origin === location.origin && url.pathname.endsWith("/stores.json")) {
    e.respondWith(caches.open(CACHE).then(c => fetch(req).then(res => { if (res.ok) c.put("./stores.json", res.clone()); return res; })
      .catch(() => c.match("./stores.json"))));
    return;
  }
  // map tiles and place search always go to the network; the library and fonts are cached
  if (/tile\\.openstreetmap|cartocdn|nominatim/.test(url.hostname)) return;
  e.respondWith(caches.open(CACHE).then(c => c.match(req).then(hit => hit || fetch(req).then(res => {
    if (res.ok || res.type === "opaque") c.put(req, res.clone());
    return res;
  }))));
});
"""


def icon(size, maskable=False):
    """A rice bowl under a map pin, on soy-brown."""
    im = Image.new("RGB", (size, size), "#7a3b2e")
    d = ImageDraw.Draw(im)
    k = size / 512 * (0.74 if maskable else 1.0)
    c = size / 2
    P = lambda x, y: (c + (x - 256) * k, c + (y - 256) * k)
    # pin
    d.ellipse([*P(156, 70), *P(356, 270)], fill="#f6f1e7")
    d.polygon([P(176, 220), P(336, 220), P(256, 330)], fill="#f6f1e7")
    d.ellipse([*P(206, 120), *P(306, 220)], fill="#c7472f")
    # bowl
    d.chord([*P(110, 300), *P(402, 470)], 0, 180, fill="#f6f1e7")
    d.rectangle([*P(110, 378), *P(402, 386)], fill="#f6f1e7")
    d.rectangle([*P(206, 452), *P(306, 466)], fill="#f6f1e7")
    return im


def main():
    offline = "--offline" in sys.argv
    geo = Geocoder(offline)
    if geo.kakao and not offline:
        collect_tv(geo)
    stores = load(geo)
    if not offline:
        print("geocoding with", "Kakao" if geo.kakao else "OpenStreetMap Nominatim")
    placed, missing, approx = [], [], 0
    for s in stores:
        ll = s.pop("ll", None) or geo.locate(s)
        if ll:
            s["ll"] = ll[:2]
            if len(ll) > 2:
                s["x"] = 1   # approximate
                approx += 1
            placed.append(s)
        else:
            missing.append(s)
    # 백년가게 the list gives no Kakao page for: look each up, which also tells which may have closed
    closed = 0
    for s in placed:
        if BAEKNYEON in s["t"] and "place.map.kakao.com" not in s.get("u", ""):
            checked, r = geo.kakao_place(s["n"], s["a"], s["ll"])
            if r:
                s["u"] = r["u"]
                s.setdefault("c", r["c"])
                if r["p"]:
                    s.setdefault("p", r["p"])
            elif checked:
                s["q"] = 1   # not on Kakao Map at this address: may have closed or moved
                closed += 1
    if closed:
        print(f"{closed} 백년가게 not found on Kakao Map at their address (marked 영업 확인 필요)")
    for s in placed:
        r = geo.region(s["ll"])
        if r:
            s["r"] = r
    geo.save()
    for i, s in enumerate(placed):
        s["id"] = i
        s["g"] = group_of(s)
        # a key that survives rebuilds, for shared links
        s["k"] = hashlib.sha1((norm_name(s["n"]) + addr_key(s["a"])).encode()).hexdigest()[:8]
    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "counts": {t: sum(t in s["t"] for s in stores) for t in (BAEKNYEON, BAEKBAN)},
        "stores": placed,
        "unplaced": [{k: s[k] for k in ("n", "a", "t") if k in s} for s in missing],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (OUT / "stores.json").write_text(data, encoding="utf-8")
    page = (SRC / "index.html").read_text(encoding="utf-8")
    version = hashlib.sha256((page + SW + data + json.dumps(MANIFEST)).encode()).hexdigest()[:8]
    # the JavaScript key is public by design (it only works on the domains registered for it)
    js_key = os.environ.get("KAKAO_JS_KEY", "").strip()
    if not js_key and (SRC / "kakao_js_key.txt").exists():
        js_key = (SRC / "kakao_js_key.txt").read_text().strip()
    (OUT / "index.html").write_text(page.replace("__VERSION__", version).replace("__KAKAO_JS_KEY__", js_key), encoding="utf-8")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    # the signboard icons in matjip/assets (drawn by assets/draw_icons.py); the plain drawing is a fallback
    for name, size, mask in (("icon-192.png", 192, False), ("icon-512.png", 512, False), ("icon-maskable-512.png", 512, True)):
        drawn = SRC / "assets" / name
        if drawn.exists():
            shutil.copyfile(drawn, OUT / name)
        else:
            icon(size, maskable=mask).save(OUT / name)
    print(f"built {version}: {len(placed)} on the map ({approx} approximate), {len(missing)} without a location")


if __name__ == "__main__":
    main()
