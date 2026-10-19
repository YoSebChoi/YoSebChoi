// node --test apt/tests
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const T = createRequire(import.meta.url)("../tracker.js");
const H = T.HOUR, D = T.DAY;
const t0 = Date.parse("2026-10-01T09:00:00+09:00");

const art = (no, o = {}) => ({ atclNo: no, tradTpCd: "A1", bildNm: "101동", flrInfo: "13/25", spc1: "106.3", spc2: "84.65",
  prc: 85000, hanPrc: "8억 5,000", direction: "남향", rltrNm: "공인", atclCfmYmd: "26.10.01.", ...o });

test("parses floors and prices", () => {
  assert.deepEqual(T.parseFloor("13/25"), { floor: "13", total: 25 });
  assert.deepEqual(T.parseFloor("중/25"), { floor: "중", total: 25 });
  assert.equal(T.parseHanPrice("8억 5,000"), 85000);
  assert.equal(T.parseHanPrice("9억"), 90000);
  assert.equal(T.formatPrice(85000), "8억 5,000");
  assert.equal(T.formatPrice(90000), "9억");
});

test("the first snapshot is the inventory, not news", () => {
  const st = T.emptyState();
  const r = T.ingest(st, "111", t0, [art("1"), art("2", { flrInfo: "5/25" })]);
  assert.equal(r.added, 0);
  assert.equal(Object.keys(st.units).length, 2);
  assert.equal(st.events.length, 0);
});

test("several agents' articles for one flat are one unit", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1"), art("2", { rltrNm: "다른공인", prc: 86000 })]);
  const units = Object.values(st.units);
  assert.equal(units.length, 1);
  assert.equal(units[0].lastPrice, 85000);
  assert.deepEqual(units[0].articles.sort(), ["1", "2"]);
});

test("a unit is gone after two misses and 20 hours, and a trade confirms it", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1"), art("2", { flrInfo: "5/25" })]);
  T.ingest(st, "111", t0 + 6 * H, [art("2", { flrInfo: "5/25" })]);      // miss 1
  assert.equal(st.gone.length, 0);
  T.ingest(st, "111", t0 + 12 * H, [art("2", { flrInfo: "5/25" })]);     // miss 2 but only 12h
  assert.equal(st.gone.length, 0);
  const r = T.ingest(st, "111", t0 + 24 * H, [art("2", { flrInfo: "5/25" })]);
  assert.equal(r.gone, 1);
  assert.equal(st.gone[0].status, "거래 추정");
  assert.equal(st.gone[0].lastPrice, 85000);
  assert.equal(st.gone[0].lastSeen, t0);

  const trades = [
    { date: "2026-09-28", cx: "111", area: 84.65, floor: 7, price: 84000 },   // wrong floor
    { date: "2026-09-29", cx: "111", area: 84.7, floor: 13, price: 84000 },
  ].map(t => ({ ...t, id: T.tradeId(t) }));
  assert.equal(T.matchTrades(st, trades), 1);
  assert.equal(st.gone[0].status, "실거래 확인");
  assert.equal(st.gone[0].trade.floor, 13);
  assert.equal(T.matchTrades(st, trades), 0);   // not twice
});

test("a unit that comes back was only taken down", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1"), art("9", { flrInfo: "3/25" })]);
  T.ingest(st, "111", t0 + 12 * H, [art("9", { flrInfo: "3/25" })]);
  T.ingest(st, "111", t0 + 30 * H, [art("9", { flrInfo: "3/25" })]);
  assert.equal(st.gone[0].status, "거래 추정");
  const r = T.ingest(st, "111", t0 + 5 * D, [art("77", { rltrNm: "새공인", prc: 83000 }), art("9", { flrInfo: "3/25" })]);
  assert.equal(r.back, 1);
  assert.equal(st.gone[0].status, "재등록");
  assert.equal(st.units[st.gone[0].unit].lastPrice, 83000);
});

test("an empty answer after many listings waits for a second one", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [1, 2, 3, 4, 5, 6].map(i => art(String(i), { flrInfo: `${i}/25` })));
  const r = T.ingest(st, "111", t0 + 24 * H, []);
  assert.equal(r.accepted, false);
  assert.equal(Object.keys(st.units).length, 6);
  T.ingest(st, "111", t0 + 48 * H, []);
  T.ingest(st, "111", t0 + 72 * H, []);
  assert.equal(st.gone.length, 6);
});

test("price cuts are events", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1")]);
  const r = T.ingest(st, "111", t0 + H, [art("1", { prc: 83000, hanPrc: "8억 3,000" })]);
  assert.equal(r.priced, 1);
  assert.equal(st.events.at(-1).type, "price");
  assert.equal(st.listings["1"].history.length, 2);
});

test("other complexes are left alone", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1")]);
  T.ingest(st, "222", t0 + 30 * H, [art("2")]);
  T.ingest(st, "222", t0 + 60 * H, [art("2")]);
  assert.equal(st.gone.length, 0);
  assert.ok(st.listings["1"]);
});

test("저/중/고 floors match by third", () => {
  assert.ok(T.floorFits("고", 25, 22));
  assert.ok(!T.floorFits("저", 25, 22));
  assert.ok(T.floorFits("중", 25, 12));
  assert.ok(T.floorFits("13", 25, 13));
  assert.ok(!T.floorFits("13", 25, 12));
});

test("prices in 원 become 만원, and the false price changes they made go away", () => {
  const st = T.emptyState();
  T.ingest(st, "111", t0, [art("1", { prc: 120000 })]);
  T.ingest(st, "111", t0 + H, [art("1", { prc: 1200000000 })]);   // a background check in 원 (now converted on the way in)
  assert.equal(st.listings["1"].price, 120000);
  assert.equal(st.events.filter(e => e.type === "price").length, 0);
  // what older checks left behind
  st.events.push({ t: t0, type: "price", cx: "111", unit: "u", from: 120000, to: 1200000000 });
  st.units[st.listings["1"].unit].lastPrice = 1200000000;
  T.repairPrices(st);
  assert.equal(st.events.filter(e => e.type === "price").length, 0);
  assert.equal(st.units[st.listings["1"].unit].lastPrice, 120000);
});
