// 우리 단지 거래 추적: the listing tracker (pure functions, no DOM), shared by the page and the tests.
//
// A listing snapshot is the 매매 articles Naver 부동산 shows for one complex at one moment. The same flat
// is often listed by several agents (several articles), so articles are grouped into units: complex +
// 동 + floor + 전용면적 + direction. A unit that stops showing up in two successful snapshots at least
// 20 hours after it was last seen is taken as sold (「거래 추정」). When the 국토교통부 실거래 data later
// shows a trade in that complex with the same size and floor, near that date and price, the guess
// becomes 「실거래 확인」. A unit that comes back within 21 days was only taken down (「재등록」).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Tracker = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const HOUR = 3600e3, DAY = 24 * HOUR;
  const GONE_AFTER_MISSES = 2;        // successful snapshots without the unit
  const GONE_AFTER = 20 * HOUR;       // …and at least this long since it was last seen
  const REAPPEAR_WINDOW = 21 * DAY;   // back within this long → it was only taken down
  const SNAP_KEEP = 400, EVENT_KEEP = 1500;

  function emptyState() {
    return { v: 1, complexes: [], listings: {}, units: {}, gone: [], events: [], snaps: [], daily: {} };
  }

  const num = s => { const n = parseFloat(String(s ?? "").replace(/,/g, "")); return isFinite(n) ? n : null; };

  // "13/25" → {floor:"13", total:25}; "중/25" → {floor:"중", total:25}
  function parseFloor(s) {
    const m = String(s || "").match(/^\s*([^/\s]+)\s*\/\s*(\d+)/);
    return m ? { floor: m[1], total: +m[2] } : { floor: String(s || "").trim() || "?", total: null };
  }

  // 원 단위가 아니라 만원: "8억 5,000" → 85000, "9억" → 90000
  function parseHanPrice(s) {
    const m = String(s || "").replace(/\s/g, "").match(/^(?:(\d+)억)?([\d,]+)?$/);
    if (!m || (!m[1] && !m[2])) return null;
    return (+(m[1] || 0)) * 10000 + (+(String(m[2] || "0").replace(/,/g, "")));
  }

  function formatPrice(manwon) {
    if (manwon == null) return "-";
    const eok = Math.floor(manwon / 10000), rest = manwon % 10000;
    if (!eok) return `${rest.toLocaleString("ko-KR")}만`;
    return rest ? `${eok}억 ${rest.toLocaleString("ko-KR")}` : `${eok}억`;
  }

  const toManwon = p => p != null && p > 1e6 ? Math.round(p / 10000) : p;

  // prices stored in 원 by a background check before they were converted: back to 만원, and the
  // 「가격 올림/내림」 those made between the two scales (the same price) dropped
  function repairPrices(st) {
    let n = 0;
    const fix = (o, k) => { if (o && o[k] != null && o[k] > 1e6) { o[k] = toManwon(o[k]); n++; } };
    for (const l of Object.values(st.listings)) {
      fix(l, "price");
      if (l.price != null && l.priceText && /^\d{5,}억/.test(l.priceText)) l.priceText = formatPrice(l.price);
      (l.history || []).forEach(h => fix(h, "price"));
      l.history = (l.history || []).filter((h, i, a) => i === 0 || h.price !== a[i - 1].price);
    }
    for (const u of Object.values(st.units)) { fix(u, "lastPrice"); fix(u, "firstPrice"); }
    for (const g of st.gone) { fix(g, "lastPrice"); fix(g, "firstPrice"); }
    for (const e of st.events) { fix(e, "price"); fix(e, "from"); fix(e, "to"); }
    const before = st.events.length;
    st.events = st.events.filter(e => !(e.type === "price" && e.from === e.to));
    return n + (before - st.events.length);
  }

  // one article from m.land.naver.com/complex/getComplexArticleList → our shape
  function normalizeArticle(a, cx) {
    const f = parseFloor(a.flrInfo);
    const area = num(a.spc2);
    // 만원; the new Naver list gives 원 (no flat here costs 100억 만원, so a bigger number is 원)
    const price = toManwon(num(a.prc) ?? parseHanPrice(a.hanPrc));
    const dong = String(a.bildNm || "").trim();
    const dir = String(a.direction || "").trim();
    return {
      no: String(a.atclNo),
      cx: String(cx),
      dong, floor: f.floor, floorTotal: f.total,
      area, supply: num(a.spc1),
      price, priceText: a.hanPrc || formatPrice(price),
      dir,
      desc: String(a.atclFetrDesc || "").trim(),
      tags: Array.isArray(a.tagList) ? a.tagList.slice(0, 6) : [],
      realtor: String(a.rltrNm || "").trim(),
      confirmed: String(a.atclCfmYmd || "").trim(),
      unit: unitKey(cx, dong, f.floor, area, dir),
    };
  }

  function unitKey(cx, dong, floor, area, dir) {
    return [cx, dong || "?", floor || "?", area != null ? area.toFixed(1) : "?", dir || "?"].join("|");
  }

  function addEvent(st, e) {
    st.events.push(e);
    if (st.events.length > EVENT_KEEP) st.events.splice(0, st.events.length - EVENT_KEEP);
  }

  function addSnap(st, s) {
    st.snaps.push(s);
    if (st.snaps.length > SNAP_KEEP) st.snaps.splice(0, st.snaps.length - SNAP_KEEP);
  }

  const dayOf = ts => {
    const d = new Date(ts + 9 * HOUR);   // KST
    return d.toISOString().slice(0, 10);
  };

  /**
   * Takes in one snapshot of a complex. `articles` are raw m.land articles (매매 only).
   * Returns {accepted, added, gone, back, priced}. Failed fetches must not be passed here
   * (call recordFailure instead): only successful snapshots can make a unit disappear.
   */
  function ingest(st, cx, ts, articles) {
    cx = String(cx);
    const res = { accepted: true, added: 0, gone: 0, back: 0, priced: 0 };
    const visibleBefore = Object.values(st.listings).filter(l => l.cx === cx).length;
    // an empty answer where there were many listings is more likely a block than a sell-out:
    // believe it only when the previous snapshot of this complex was also empty
    if (!articles.length && visibleBefore >= 5) {
      const last = [...st.snaps].reverse().find(s => s.cx === cx);
      if (!last || !last.suspectEmpty) {
        addSnap(st, { t: ts, cx, ok: false, count: 0, suspectEmpty: true, err: "매물 0건 (일시적 차단일 수 있어 다음 확인까지 보류)" });
        res.accepted = false;
        return res;
      }
    }

    const seen = new Map();
    for (const raw of articles) {
      const tt = raw.tradTpCd || raw.tradeTypeCode;
      if (tt && tt !== "A1") continue;
      const a = normalizeArticle(raw, cx);
      if (!seen.has(a.no)) seen.set(a.no, a);
    }

    const presentUnits = new Set();
    for (const a of seen.values()) {
      presentUnits.add(a.unit);
      const old = st.listings[a.no];
      if (!old) {
        st.listings[a.no] = { ...a, firstSeen: ts, lastSeen: ts, history: [{ t: ts, price: a.price }] };
      } else {
        if (a.price != null && old.price != null && a.price !== old.price) {
          addEvent(st, { t: ts, type: "price", cx, unit: a.unit, no: a.no, from: old.price, to: a.price });
          old.history.push({ t: ts, price: a.price });
          res.priced++;
        }
        Object.assign(old, a, { firstSeen: old.firstSeen, history: old.history, lastSeen: ts });
      }
    }
    for (const [no, l] of Object.entries(st.listings)) {
      if (l.cx === cx && !seen.has(no)) delete st.listings[no];
    }

    // units
    for (const key of presentUnits) {
      const ls = [...seen.values()].filter(a => a.unit === key);
      const prices = ls.map(a => a.price).filter(p => p != null);
      const minPrice = prices.length ? Math.min(...prices) : null;
      let u = st.units[key];
      if (!u) {
        // came back soon after it went away → it was only taken down, not sold
        const g = [...st.gone].reverse().find(g => g.unit === key && g.status !== "재등록" && ts - g.lastSeen <= REAPPEAR_WINDOW);
        if (g && g.status !== "실거래 확인") {
          g.status = "재등록";
          g.backAt = ts;
          addEvent(st, { t: ts, type: "back", cx, unit: key, price: minPrice });
          res.back++;
          u = st.units[key] = { key, cx, dong: g.dong, floor: g.floor, floorTotal: g.floorTotal, area: g.area, supply: g.supply, dir: g.dir,
            firstSeen: g.firstSeen, lastSeen: ts, misses: 0, firstPrice: g.firstPrice, lastPrice: minPrice, articles: [] };
        } else {
          const a = ls[0];
          u = st.units[key] = { key, cx, dong: a.dong, floor: a.floor, floorTotal: a.floorTotal, area: a.area, supply: a.supply, dir: a.dir,
            firstSeen: ts, lastSeen: ts, misses: 0, firstPrice: minPrice, lastPrice: minPrice, articles: [] };
          // the very first snapshot of a complex is the starting inventory, not news
          if (st.snaps.some(s => s.cx === cx && s.ok)) {
            addEvent(st, { t: ts, type: "new", cx, unit: key, price: minPrice });
            res.added++;
          }
        }
      }
      u.lastSeen = ts;
      u.misses = 0;
      u.firstMiss = null;
      if (minPrice != null) u.lastPrice = minPrice;
      u.articles = ls.map(a => a.no);
      // what the listings looked like last, kept when the flat goes (the listings themselves are dropped)
      u.lastListings = ls.slice(0, 8).map(a => ({ no: a.no, priceText: a.priceText, realtor: a.realtor, desc: a.desc, confirmed: a.confirmed }));
      u.floorTotal = u.floorTotal || ls[0].floorTotal;
      u.supply = u.supply || ls[0].supply;
    }

    for (const [key, u] of Object.entries(st.units)) {
      if (u.cx !== cx || presentUnits.has(key)) continue;
      u.misses = (u.misses || 0) + 1;
      if (!u.firstMiss) u.firstMiss = ts;
      if (u.misses >= GONE_AFTER_MISSES && ts - u.lastSeen >= GONE_AFTER) {
        // the same flat still listed under another floor label (「22/25」 by one agent, 「고/25」 by another):
        // not gone, only one label dropped
        const twin = Object.values(st.units).find(v => v !== u && presentUnits.has(v.key) && sameFlat(u, v));
        if (twin) { delete st.units[key]; continue; }
        st.gone.push({ unit: key, cx, dong: u.dong, floor: u.floor, floorTotal: u.floorTotal, area: u.area, supply: u.supply, dir: u.dir,
          firstSeen: u.firstSeen, lastSeen: u.lastSeen, firstMiss: u.firstMiss, firstPrice: u.firstPrice, lastPrice: u.lastPrice,
          lastListings: u.lastListings || [], status: "거래 추정" });
        addEvent(st, { t: ts, type: "gone", cx, unit: key, price: u.lastPrice, lastSeen: u.lastSeen });
        delete st.units[key];
        res.gone++;
      }
    }

    st.daily[cx] = st.daily[cx] || {};
    st.daily[cx][dayOf(ts)] = presentUnits.size;
    addSnap(st, { t: ts, cx, ok: true, count: seen.size, units: presentUnits.size });
    return res;
  }

  function recordFailure(st, cx, ts, err) {
    addSnap(st, { t: ts, cx: String(cx), ok: false, count: 0, err: String(err || "실패").slice(0, 200) });
  }

  // ── 실거래 matching ────────────────────────────────────────────────

  // 저/중/고 → which third of the building
  // two floor labels that can be the same floor: equal, or a number and the third (저/중/고) it falls in
  function floorsMeet(a, b, total) {
    if (String(a) === String(b)) return true;
    const na = isFinite(+a) && String(a).trim() !== "", nb = isFinite(+b) && String(b).trim() !== "";
    if (na === nb) return false;
    return na ? floorFits(b, total, +a) : floorFits(a, total, +b);
  }

  // one flat listed twice under different labels: same complex, 동, size and direction, floors that can
  // meet, asking prices within 5%
  function sameFlat(u, v) {
    if (u.cx !== v.cx || (u.dong || "") !== (v.dong || "")) return false;
    if (u.area != null && v.area != null && Math.abs(u.area - v.area) > 0.3) return false;
    if (u.dir && v.dir && u.dir !== v.dir) return false;
    if (!floorsMeet(u.floor, v.floor, u.floorTotal || v.floorTotal)) return false;
    if (u.lastPrice && v.lastPrice && Math.abs(u.lastPrice - v.lastPrice) / Math.max(u.lastPrice, v.lastPrice) > 0.05) return false;
    return true;
  }

  function floorFits(unitFloor, total, tradeFloor) {
    const f = +unitFloor;
    if (isFinite(f) && String(unitFloor).trim() !== "") return f === tradeFloor;
    if (!total) return true;
    const third = tradeFloor / total;
    if (unitFloor === "저") return third <= 0.4;
    if (unitFloor === "중") return third > 0.25 && third <= 0.75;
    if (unitFloor === "고") return third > 0.6;
    return true;
  }

  const tradeTime = t => Date.parse(t.date + "T12:00:00+09:00");

  /**
   * trades: [{date:"2026-06-30", cx (our complex no, or null), area, floor, price, cancelled}]
   * Marks gone units that a trade explains as 「실거래 확인」. A 계약 is reported within 30 days,
   * and the listing usually comes down around the contract, so the trade may be dated up to 30 days
   * before the unit was last seen... or a little after (the agent may leave it up a few days).
   */
  // a deal dated more than a week before we first saw the listing is not that listing's sale (it went up
  // after it, or it is another flat): tracking began after it
  const BEFORE_FIRST_SEEN = 7 * DAY;
  const tooEarly = (g, t) => tradeTime(t) < g.firstSeen - BEFORE_FIRST_SEEN;
  // a deal at 90–103% of the last asking price (a 13억 listing selling for 11억 2,000 is another flat)
  const PRICE_LOW = 0.90, PRICE_HIGH = 1.03;
  const priceOff = (g, t) => g.lastPrice && (t.price / g.lastPrice < PRICE_LOW || t.price / g.lastPrice > PRICE_HIGH);

  function matchTrades(st, trades) {
    // flats taken as gone while still listed under another floor label: they were only relabelled
    for (const g of st.gone) {
      if (g.status === "재등록") continue;
      if (Object.values(st.units).some(v => v.lastSeen > g.lastSeen && sameFlat({ ...g, cx: g.cx }, v))) {
        g.status = "재등록";
        g.backAt = g.backAt || Date.now();
        delete g.trade;
        st.events = st.events.filter(e => !(e.type === "trade" && e.unit === g.unit && e.cx === g.cx));
      }
    }
    // confirmations made before these rules: back to 「거래 추정」
    for (const g of st.gone) {
      if (g.status === "실거래 확인" && g.trade && (tooEarly(g, g.trade) || priceOff(g, g.trade))) {
        g.status = "거래 추정";
        delete g.trade;
        st.events = st.events.filter(e => !(e.type === "trade" && e.unit === g.unit && e.cx === g.cx));
      }
    }
    const used = new Set(st.gone.filter(g => g.trade).map(g => g.trade.id));
    let n = 0;
    for (const g of st.gone) {
      if (g.status !== "거래 추정") continue;
      let best = null, bestScore = Infinity;
      for (const t of trades) {
        if (t.cancelled || String(t.cx) !== g.cx || used.has(t.id)) continue;
        if (g.area != null && Math.abs(t.area - g.area) > 1.0) continue;
        if (!floorFits(g.floor, g.floorTotal, t.floor)) continue;
        const dt = tradeTime(t) - g.lastSeen;
        if (dt < -30 * DAY || dt > 20 * DAY || tooEarly(g, t)) continue;
        let score = Math.abs(dt) / DAY;
        if (g.lastPrice) {
          const r = t.price / g.lastPrice;
          if (r < PRICE_LOW || r > PRICE_HIGH) continue;
          score += Math.abs(1 - r) * 200;
        }
        if (score < bestScore) { best = t; bestScore = score; }
      }
      if (best) {
        g.status = "실거래 확인";
        g.trade = { id: best.id, date: best.date, price: best.price, floor: best.floor, area: best.area };
        used.add(best.id);
        addEvent(st, { t: Date.now(), type: "trade", cx: g.cx, unit: g.unit, price: best.price, date: best.date });
        n++;
      }
    }
    return n;
  }

  // a trade's id: the fields that make it one deal
  const tradeId = t => [t.cx, t.date, t.area, t.floor, t.price, t.dong || ""].join("|");

  return { emptyState, ingest, recordFailure, matchTrades, repairPrices, normalizeArticle, parseFloor, parseHanPrice, formatPrice,
    floorFits, floorsMeet, sameFlat, tradeId, dayOf, unitKey, HOUR, DAY };
});
