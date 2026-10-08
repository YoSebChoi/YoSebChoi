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
import sys
import time
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
            s = {"n": name, "a": addr, "t": [tag]}
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
    return merge(stores)


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


def norm_name(n):
    return re.sub(r"\s+|본점|\(.*?\)|식당$", "", n)


def merge(stores):
    """A place that is both a 백년가게 and on 백반기행 becomes one entry with both tags."""
    out, seen = [], {}
    for s in stores:
        key = (norm_name(s["n"]), clean_addr(s["a"]))
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
        self.last = 0.0
        self.looked_up = 0

    def _get(self, url, headers):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))

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

    def kakao_is_food(self, name, addr):
        """Ask Kakao what kind of place this store is (음식점 FD6 / 카페 CE7); None without a key."""
        if not self.kakao:
            return None
        key = "kind:" + name + "@" + clean_addr(addr)
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return None
        region = " ".join(addr.split()[:2])
        try:
            url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode({"query": f"{region} {name}", "size": 5})
            docs = self._get(url, {"Authorization": f"KakaoAK {self.kakao}"}).get("documents", [])
        except Exception as e:
            print("  kind lookup failed:", name, "-", e)
            return None
        road = clean_addr(addr).split()[-2:]   # match the place on the same road
        hit = next((d for d in docs if all(t in (d.get("road_address_name") or "") for t in road)), None)
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
    "name": "노포 지도 — 백년가게 · 백반기행",
    "short_name": "노포 지도",
    "description": "내 주변 또는 지도에서 고른 곳 근처의 백년가게와 허영만의 백반기행 맛집을 찾아요.",
    "lang": "ko",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#f6f1e7",
    "theme_color": "#7a3b2e",
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
  if (/tile\\.openstreetmap|nominatim/.test(url.hostname)) return;
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
    geo.save()
    for i, s in enumerate(placed):
        s["id"] = i
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
    (OUT / "index.html").write_text(page.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "sw.js").write_text(SW.replace("__VERSION__", version), encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2), encoding="utf-8")
    icon(192).save(OUT / "icon-192.png")
    icon(512).save(OUT / "icon-512.png")
    icon(512, maskable=True).save(OUT / "icon-maskable-512.png")
    print(f"built {version}: {len(placed)} on the map ({approx} approximate), {len(missing)} without a location")


if __name__ == "__main__":
    main()
