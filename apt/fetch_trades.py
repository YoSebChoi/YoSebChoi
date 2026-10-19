"""국토교통부 아파트 매매 실거래가(공공데이터포털)에서 반송동 거래를 받아 apt/data/trades.json에 모아요.

- 키: 공공데이터포털(data.go.kr) 「국토교통부_아파트 매매 실거래가 자료」 활용 신청 → 일반 인증키를
  저장소 Secret MOLIT_KEY에 넣어요 (Decoding 키, Encoding 키 둘 다 돼요). 키가 없으면 있던 기록을 그대로 둬요.
- 지역코드: 화성시는 41590. 2026년 2월 동탄구가 생기면서 코드가 바뀌었을 수 있어, 그 달에 반송동 거래가
  나오는 코드를 찾아 기록해 둬요.
- 지난 달까지는 한 번 받으면 끝이고, 최근 4개월은 매번 다시 받아요 (신고는 계약 후 30일 안, 해제도 나중에 붙어요).

python3 apt/fetch_trades.py [--since 2015-01]
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC / "data/trades.json"
COMPLEXES = SRC / "data/complexes.json"
URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
HWASEONG = "41590"
# 동탄구 신설(2026-02) 뒤의 코드 후보: 화성시 41590 다음 번호들
CANDIDATES = [HWASEONG] + [f"4159{i}" for i in range(1, 10)]
REFRESH_MONTHS = 4


def months(since, until):
    y, m = since
    while (y, m) <= until:
        yield f"{y:04d}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def call(key, lawd, ym, page, retries=2):
    k = key if "%" in key else urllib.parse.quote(key, safe="")
    qs = urllib.parse.urlencode({"LAWD_CD": lawd, "DEAL_YMD": ym, "pageNo": page, "numOfRows": 1000})
    last = None
    for attempt in range(retries + 1):
        time.sleep(random.uniform(0.3, 0.8))
        try:
            with urllib.request.urlopen(f"{URL}?serviceKey={k}&{qs}", timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"실거래 API 실패 {lawd} {ym}: {last}")


def text(item, tag):
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def fetch_month(key, lawd, ym, dong):
    """→ (그 지역코드의 거래 수, 반송동 거래들). 키·한도 오류는 RuntimeError."""
    rows, total, page = [], 0, 1
    while True:
        body = call(key, lawd, ym, page)
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise RuntimeError(f"실거래 API가 XML이 아닌 답을 줬어요: {body[:200]}")
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or ""
        if code and code not in ("00", "000"):
            msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or ""
            raise RuntimeError(f"실거래 API 오류 {code} {msg}")
        items = root.findall(".//item")
        total += len(items)
        for it in items:
            if text(it, "umdNm") != dong:
                continue
            amount = text(it, "dealAmount").replace(",", "")
            rows.append({
                "date": f"{text(it, 'dealYear')}-{int(text(it, 'dealMonth') or 0):02d}-{int(text(it, 'dealDay') or 0):02d}",
                "nm": text(it, "aptNm"),
                "jibun": text(it, "jibun"),
                "area": float(text(it, "excluUseAr") or 0),
                "floor": int(text(it, "floor") or 0),
                "price": int(amount) if amount.isdigit() else None,
                "aptDong": text(it, "aptDong"),
                "cancelled": text(it, "cdealType") == "O",
                "cancelDate": text(it, "cdealDay"),
                "gbn": text(it, "dealingGbn"),
                "built": text(it, "buildYear"),
            })
        n_total = int(root.findtext(".//totalCount") or 0)
        if page * 1000 >= n_total or not items:
            return total, rows
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2015-01")
    args = ap.parse_args()
    key = os.environ.get("MOLIT_KEY", "").strip()
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"months": {}, "trades": []}
    if not key:
        print("MOLIT_KEY가 없어서 실거래 기록을 그대로 둬요 (apt/README.md 참고)", file=sys.stderr)
        return
    dong = {c.get("dong", "반송동") for c in json.loads(COMPLEXES.read_text(encoding="utf-8"))["complexes"]}
    if len(dong) != 1:
        raise SystemExit("complexes.json의 단지들이 한 법정동에 있어야 해요")
    dong = dong.pop()

    today = dt.date.today()
    sy, sm = map(int, args.since.split("-"))
    all_months = list(months((sy, sm), (today.year, today.month)))
    fresh = set(all_months[-REFRESH_MONTHS:])
    done = old.get("months", {})
    by_month = {}
    for t in old.get("trades", []):
        by_month.setdefault(t["date"][:7].replace("-", ""), []).append(t)

    errors = 0
    for ym in all_months:
        if ym in done and ym not in fresh:
            continue
        # 지난번에 맞았던 코드부터, 그다음 화성시, 그다음 후보들
        tried, got = [], None
        order = [done.get(ym, {}).get("lawd")] if done.get(ym, {}).get("lawd") else []
        prev = next((done[m]["lawd"] for m in sorted(done, reverse=True) if m < ym and done[m].get("lawd")), None)
        order += [c for c in [prev] + CANDIDATES if c and c not in order]
        if ym < "202602":
            order = [HWASEONG]
        try:
            for lawd in order:
                tried.append(lawd)
                total, rows = fetch_month(key, lawd, ym, dong)
                if rows:
                    got = (lawd, rows)
                    break
                if total and lawd == HWASEONG and ym < "202602":
                    got = (lawd, [])
                    break
        except RuntimeError as e:
            print(e, file=sys.stderr)
            errors += 1
            if errors >= 3:
                print("오류가 이어져서 여기까지만 받아요", file=sys.stderr)
                break
            continue
        if got:
            by_month[ym] = got[1]
            done[ym] = {"lawd": got[0], "n": len(got[1]), "at": today.isoformat()}
        else:
            done[ym] = {"lawd": None, "n": 0, "at": today.isoformat(), "tried": tried}
        print(f"{ym}: {done[ym]['n']}건 ({done[ym]['lawd']})")

    trades = sorted((t for ts in by_month.values() for t in ts), key=lambda t: (t["date"], t["nm"], t["floor"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated": today.isoformat(), "dong": dong, "months": done, "trades": trades},
                              ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{dong} 실거래 {len(trades)}건 → {OUT}")


if __name__ == "__main__":
    main()
