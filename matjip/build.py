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

BAEKBAN = "bb"     # 허영만의 백반기행
BAEKNYEON = "bn"   # 백년가게

# column name candidates, matched after removing spaces
COLS = {
    "name": ["상호", "상호명", "업체명", "가게명", "업소명", "점포명", "기업명", "사업장명", "식당명"],
    "addr": ["도로명주소", "주소", "소재지", "소재지주소", "사업장주소", "소재지도로명주소", "지번주소", "소재지지번주소"],
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


def load():
    stores = []
    files = sorted(DATA.glob("*.csv"))
    official = [f for f in files if f.name not in ("baekban.csv", "baeknyeon_seed.csv")]
    for f in files:
        if f.name == "baeknyeon_seed.csv" and official:
            continue   # the official list covers these
        tag = BAEKBAN if f.name == "baekban.csv" else BAEKNYEON
        header, rows = read_csv(f)
        ix = {k: pick(header, k) for k in COLS}
        if ix["addr"] is None:
            raise SystemExit(f"{f.name}: no address column (one of {', '.join(COLS['addr'])})")
        kept = skipped = 0
        for r in rows:
            get = lambda k: (r[ix[k]].strip() if ix[k] is not None and ix[k] < len(r) else "")
            name, addr = get("name"), get("addr")
            if not name or not addr:
                continue
            kind = get("kind")
            if tag == BAEKNYEON and kind and (NOT_FOOD.search(kind) or not FOOD.search(kind)) and not FOOD.search(get("menu")):
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
    return merge(stores)


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
    stores = load()
    geo = Geocoder(offline)
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
