// Checks the built app (docs/apt) in Chromium, run by the data workflow after each build and by hand:
//  1. as a plain web page: no errors, the 실거래 and 블로그 tabs render;
//  2. as the Android app, with a stand-in for the native bridge (AptNet) that serves synthetic Naver
//     listings and moves the clock: a flat whose listings vanish becomes 「거래 추정」, a trade in the
//     data turns it into 「실거래 확인」, and a flat that comes back becomes 「재등록」.
// node apt/check/check_app.mjs   (needs playwright; npm i playwright in this folder or globally)
import { chromium } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const root = new URL("../../docs/", import.meta.url).pathname;
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".webmanifest": "application/manifest+json" };
const DAY = 864e5, t0 = Date.parse("2026-09-20T09:00:00+09:00");

// data.json with one known trade of KCC (key "kcc") 2 days before the flat disappears
async function data() {
  const d = JSON.parse(await readFile(join(root, "apt/data.json"), "utf8"));
  d.trades = [...d.trades.filter(t => t.date < "2026-01-01"),
    ...["2024-03-02", "2024-08-15", "2025-01-20", "2025-06-11", "2025-11-03", "2026-03-27", "2026-06-30"].map((date, i) =>
      ({ date, nm: "시범한빛마을케이씨씨스위첸", jibun: "19", area: 84.6517, floor: 3 + i * 2, price: 61000 + i * 4000, aptDong: "10" + i, cancelled: i === 4, gbn: "중개거래", cx: "kcc" })),
    { date: "2026-09-21", nm: "시범한빛마을케이씨씨스위첸", jibun: "19", area: 84.6517, floor: 13, price: 84500, aptDong: "101", cancelled: false, gbn: "중개거래", cx: "kcc" }];
  d.tradeMonths = ["202609"];
  return JSON.stringify(d);
}
const server = http.createServer(async (req, res) => {
  let path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (path.endsWith("/")) path += "index.html";
  try {
    const body = path === "/apt/data.json" && req.headers["x-mock"] !== "no" ? await data() : await readFile(join(root, path));
    res.writeHead(200, { "content-type": types[extname(path)] || "application/octet-stream" }).end(body);
  } catch { res.writeHead(404).end(); }
}).listen(8766);

const fail = [];
const browser = await chromium.launch();

// 1. web
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("web: page error: " + e.message));
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  if (!(await page.locator("text=매물 추적은 Android 앱에서").count())) fail.push("web: no app note");
  await page.click("#tab-trades");
  if (!(await page.locator("#panel-trades .row").count())) fail.push("web: no trades rows");
  await page.click("#tab-news");
  if (!(await page.locator("#panel-news .row").count())) fail.push("web: no blog rows");
  await page.screenshot({ path: new URL("./web.png", import.meta.url).pathname, fullPage: true });
  await page.close();
}

// 2. app with a fake bridge
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("app: page error: " + e.message));
  page.on("dialog", d => d.accept());
  await page.clock.install({ time: t0 });
  await page.addInitScript(() => {
    const art = (no, o = {}) => ({ atclNo: no, atclNm: "동탄시범한빛마을KCC스위첸", tradTpCd: "A1", bildNm: "101동", flrInfo: "13/25", spc1: "106.3", spc2: "84.65",
      prc: 85000, hanPrc: "8억 5,000", direction: "남향", rltrNm: "한빛공인", atclCfmYmd: "26.09.20.", tagList: ["25년이상", "역세권"], ...o });
    // what Naver shows, per phase (window.__phase is moved by the test)
    const phases = {
      0: [art("1"), art("2", { rltrNm: "시범공인", prc: 86000, hanPrc: "8억 6,000" }), art("3", { bildNm: "103동", flrInfo: "5/25", prc: 79000, hanPrc: "7억 9,000" }),
          art("4", { bildNm: "105동", flrInfo: "고/25", prc: 92000, hanPrc: "9억 2,000" })],
      1: [art("3", { bildNm: "103동", flrInfo: "5/25", prc: 77000, hanPrc: "7억 7,000" }), art("4", { bildNm: "105동", flrInfo: "고/25", prc: 92000, hanPrc: "9억 2,000" })],
      2: [art("3", { bildNm: "103동", flrInfo: "5/25", prc: 77000, hanPrc: "7억 7,000" })],
      3: [art("3", { bildNm: "103동", flrInfo: "5/25", prc: 77000, hanPrc: "7억 7,000" }), art("9", { bildNm: "105동", flrInfo: "고/25", prc: 90000, hanPrc: "9억", rltrNm: "새공인" })],
    };
    window.__phase = 0;
    window.__calls = [];
    const AptNet = {
      async get({ url }) {
        window.__calls.push(url);
        if (url.includes("complexList")) {
          // like Naver: a wide box answers 20 complexes and KCC is not among them; a small one has it
          const q = new URL(url).searchParams, wide = +q.get("top") - +q.get("btm") > 0.01;
          const others = [{ hscpNo: "1002", hscpNm: "동탄시범한빛마을동탄아이파크", totHsehCnt: 748, lat: 37.2050, lng: 127.0740 },
            { hscpNo: "2001", hscpNm: "동탄시범나루마을한화꿈에그린우림필유", totHsehCnt: 444, lat: 37.21, lng: 127.08 }];
          for (let i = 0; i < 18; i++) others.push({ hscpNo: String(3000 + i), hscpNm: `다른단지${i}`, lat: 37.19, lng: 127.06 });
          const kcc = { hscpNo: "1001", hscpNm: "동탄시범한빛마을KCC스위첸", totHsehCnt: 484, lat: 37.2046, lng: 127.0731 };
          return { status: 200, body: JSON.stringify({ result: wide ? others : [kcc, others[0]] }) };
        }
        const no = new URL(url).searchParams.get("hscpNo");
        const list = no === "1001" ? phases[window.__phase] : [];
        return { status: 200, body: JSON.stringify({ result: { list, moreDataYn: "N", totAtclCnt: list.length } }) };
      },
      async schedule(o) { window.__scheduled = o; },
      async collect() { return { snapshots: [] }; },
    };
    window.Capacitor = { isNativePlatform: () => true, Plugins: { AptNet, App: { addListener() {}, getInfo: async () => ({ build: "999" }) } } };
  });
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  // the app pauses between requests (setTimeout); with the clock installed, time only moves when told to
  const run = async () => { const p = page.evaluate(() => window.__aptwatch.refresh(true)); await page.clock.runFor(20000); await p; await page.clock.runFor(20000); };
  await page.clock.runFor(20000);
  await run();
  const st = () => page.evaluate(() => window.__aptwatch.S);
  let s = await st();
  const cfg = await page.evaluate(() => window.__aptwatch.cfg);
  if (cfg.links.kcc?.no !== "1001") fail.push("app: KCC not auto-linked: " + JSON.stringify(cfg.links));
  if (cfg.links.hanwha) fail.push("app: 나루마을 한화 linked as 한빛마을 한화");
  if (Object.keys(s.units).length !== 3) fail.push(`app: expected 3 flats from 4 listings, got ${Object.keys(s.units).length}`);
  // a day later 101동 13층 is gone (both agents), 103동 is cheaper
  await page.evaluate(() => { window.__phase = 1; });
  for (const dt of [0.5, 1.1]) { await page.clock.setSystemTime(t0 + dt * DAY); await run(); }
  s = await st();
  const g = s.gone.find(x => x.unit.includes("101동|13|"));
  if (!g) fail.push("app: 101동 13층 not taken as sold");
  else if (g.status !== "실거래 확인") fail.push("app: 101동 13층 should be confirmed by the trade, is " + g.status);
  if (!s.events.some(e => e.type === "price" && e.to === 77000)) fail.push("app: price cut not recorded");
  // 105동 고층 goes, then comes back 4 days later with another agent
  await page.evaluate(() => { window.__phase = 2; });
  for (const dt of [1.6, 2.4]) { await page.clock.setSystemTime(t0 + dt * DAY); await run(); }
  s = await st();
  if (!s.gone.some(x => x.unit.includes("105동|고|") && x.status === "거래 추정")) fail.push("app: 105동 not 거래 추정");
  await page.evaluate(() => { window.__phase = 3; });
  await page.clock.setSystemTime(t0 + 6 * DAY); await run();
  s = await st();
  if (!s.gone.some(x => x.unit.includes("105동|고|") && x.status === "재등록")) fail.push("app: 105동 not 재등록");
  const sch = await page.evaluate(() => window.__scheduled);
  if (!sch || !sch.jobs.length || sch.hours !== 12) fail.push("app: background check not scheduled");
  for (const t of ["home", "list", "gone", "trades"]) {
    await page.click("#tab-" + t);
    if (t === "trades" && !(await page.locator("#panel-trades svg.chart circle").count())) fail.push("app: no 실거래 chart");
    await page.screenshot({ path: new URL(`./app-${t}.png`, import.meta.url).pathname, fullPage: true });
  }
  if (!(await page.locator("#panel-gone .badge.b-ok").count())) fail.push("app: no 실거래 확인 badge on 거래 추정 tab");
  await page.click("#settingsBtn");
  await page.screenshot({ path: new URL("./app-settings.png", import.meta.url).pathname, fullPage: true });
}

// 3. the complex search comes back empty: the app says why, and 네트워크 진단 shows Naver's answer
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("empty search: page error: " + e.message));
  await page.addInitScript(() => {
    const AptNet = {
      async get({ url }) { return { status: 302, location: "https://fin.land.naver.com/", body: "" }; },
      async schedule() {}, async collect() { return { snapshots: [] }; },
    };
    window.Capacitor = { isNativePlatform: () => true, Plugins: { AptNet, App: { addListener() {}, getInfo: async () => ({ build: "999" }) } } };
  });
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  if (!(await page.locator("#panel-home .note.warn", { hasText: "HTTP 302" }).count())) fail.push("empty search: home does not say why");
  await page.click("#settingsBtn");
  await page.click("text=네트워크 진단");
  if (!(await page.locator("#settingsBody", { hasText: "fin.land.naver.com" }).count())) fail.push("empty search: 네트워크 진단 does not show the redirect");
  await page.screenshot({ path: new URL("./app-diagnose.png", import.meta.url).pathname, fullPage: true });
  await page.close();
}

// 6. both mobile-site lists answer null (what the phone got): the new fin.land list is read (POST),
//    prices in 원 become 만원, the agents' copies of one flat stay one flat, and the background check follows
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("fin: page error: " + e.message));
  await page.addInitScript(() => {
    localStorage.setItem("aw-cfg", JSON.stringify({ links: { kcc: { no: "1001", name: "동탄시범한빛마을KCC스위첸", hh: 484, lat: 37.2046, lng: 127.0731, approx: 0 } }, hours: 12, notify: true, askedNotify: true }));
    window.__reqs = [];
    const flat = (no, dong, floor, price, broker) => ({ articleNumber: no, complexName: "동탄시범한빛마을KCC스위첸", dongName: dong,
      articleDetail: { floorInfo: floor, direction: "남향" }, spaceInfo: { supplySpace: 106.3, exclusiveSpace: 84.65 },
      priceInfo: { dealPrice: price }, brokerInfo: { brokerageName: broker } });
    const AptNet = {
      async get({ url }) {
        if (url.includes("complex/info") || url.includes("fin.land.naver.com/complexes")) return { status: 200, body: "<html></html>" };
        return { status: 200, body: "null" };
      },
      async request({ url, method, body }) {
        window.__reqs.push({ url, method, body });
        const second = Array.isArray(body.lastInfo) && body.lastInfo.length;
        const list = second ? [{ representativeArticleInfo: flat("A3", "105동", "고/25", 920000000, "새공인") }]
          : [{ representativeArticleInfo: flat("A1", "101동", "13/25", 850000000, "한빛공인"),
               duplicatedArticleInfo: { articleInfoList: [flat("A2", "101동", "13/25", 860000000, "시범공인")] } }];
        return { status: 200, body: JSON.stringify({ isSuccess: true, result: { list, hasNextPage: !second, lastInfo: second ? null : ["cursor1"] } }) };
      },
      async schedule(o) { window.__scheduled = o; }, async collect() { return { snapshots: [] }; },
    };
    window.Capacitor = { isNativePlatform: () => true, Plugins: { AptNet, App: { addListener() {}, getInfo: async () => ({ build: "999" }) } } };
  });
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__scheduled, null, { timeout: 60000 }).catch(() => {});
  const s = await page.evaluate(() => window.__aptwatch.S);
  const units = Object.values(s.units).filter(u => u.cx === "1001");
  if (units.length !== 2) fail.push(`fin: expected 2 flats (3 listings), got ${units.length}: ${JSON.stringify(s.snaps.slice(-2))}`);
  const u101 = units.find(u => u.dong === "101동");
  if (!u101 || u101.lastPrice !== 85000 || u101.articles.length !== 2) fail.push("fin: 101동 should be 8억 5,000 with 2 agents: " + JSON.stringify(u101));
  const snap = s.snaps.filter(x => x.cx === "1001").at(-1);
  if (!snap || snap.src !== "fin") fail.push("fin: snapshot not marked fin");
  const job = (await page.evaluate(() => window.__scheduled))?.jobs?.find(j => j.cx === "1001");
  if (!job || job.method !== "POST" || !job.map || job.priceDiv !== 10000 || !job.listPath) fail.push("fin: background job not on the fin list: " + JSON.stringify(job));
  const reqs = await page.evaluate(() => window.__reqs);
  if (reqs.length !== 2 || !reqs[1].body.lastInfo?.length) fail.push("fin: second page not asked with the cursor");
  await page.close();
}

// 5. KCC linked earlier without coordinates, the wide search leaves it out, and the complex list answers null:
//    one search in small boxes finds its coordinates and the map list is read
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("no coords: page error: " + e.message));
  await page.addInitScript(() => {
    localStorage.setItem("aw-cfg", JSON.stringify({ links: { kcc: { no: "1001", name: "동탄시범한빛마을KCC스위첸", hh: 484 } }, hours: 12, notify: true, askedNotify: true }));
    window.__urls = [];
    const AptNet = {
      async get({ url }) {
        window.__urls.push(url);
        if (url.includes("complexList")) {
          const q = new URL(url).searchParams, wide = +q.get("top") - +q.get("btm") > 0.01;
          // like the phone saw: no coordinates in the complexes at all; KCC only in the small box over it
          const others = Array.from({ length: 20 }, (_, i) => ({ hscpNo: String(3000 + i), hscpNm: i ? `다른단지${i}` : "동탄시범한빛마을동탄아이파크", totHsehCnt: 700 }));
          const lat = +q.get("lat"), lng = +q.get("lon");
          const overKcc = Math.abs(lat - 37.2045) < 0.004 && Math.abs(lng - 127.0725) < 0.004;
          return { status: 200, body: JSON.stringify({ result: wide ? others : overKcc ? [{ hscpNo: "1001", hscpNm: "동탄시범한빛마을KCC스위첸", totHsehCnt: 484 }] : [] }) };
        }
        if (url.includes("getComplexArticleList")) return { status: 200, body: "null" };
        if (url.includes("cluster/ajax/articleList")) return { status: 200, body: JSON.stringify({ code: "success", more: false, body: [
          { atclNo: "1", atclNm: "동탄시범한빛마을KCC스위첸", tradTpCd: "A1", bildNm: "101동", flrInfo: "13/25", spc2: "84.65", prc: 85000, direction: "남향" }] }) };
        return { status: 404, body: "" };
      },
      async schedule(o) { window.__scheduled = o; }, async collect() { return { snapshots: [] }; },
    };
    window.Capacitor = { isNativePlatform: () => true, Plugins: { AptNet, App: { addListener() {}, getInfo: async () => ({ build: "999" }) } } };
  });
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__scheduled, null, { timeout: 60000 }).catch(() => {});
  const s = await page.evaluate(() => window.__aptwatch.S);
  if (!Object.values(s.units).some(u => u.cx === "1001")) fail.push("no coords: KCC's listing not read from the map: " + JSON.stringify(s.snaps.slice(-3)));
  const urls = await page.evaluate(() => window.__urls);
  const wideSearches = urls.filter(u => u.includes("complexList") && (+new URL(u).searchParams.get("top") - +new URL(u).searchParams.get("btm")) > 0.01).length;
  if (wideSearches > 2) fail.push(`no coords: the wide complex search ran ${wideSearches} times`);
  const mapUrl = urls.find(u => u.includes("articleList"));
  if (mapUrl) { const q = new URL(mapUrl).searchParams; if (+q.get("top") - +q.get("btm") > 0.01) fail.push("no coords: map list box too wide " + mapUrl); }
  await page.close();
}

// 4. the complex list comes back empty but the map shows listings: the app reads them from the map,
//    keeps only this complex's, and points the background check at the map list
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.on("pageerror", e => fail.push("map list: page error: " + e.message));
  await page.addInitScript(() => {
    const art = (no, o = {}) => ({ atclNo: no, atclNm: "동탄시범한빛마을KCC스위첸", tradTpCd: "A1", bildNm: "101동", flrInfo: "13/25", spc1: "106.3", spc2: "84.65",
      prc: 85000, hanPrc: "8억 5,000", direction: "남향", rltrNm: "한빛공인", ...o });
    window.__urls = [];
    const AptNet = {
      async get({ url }) {
        window.__urls.push(url);
        if (url.includes("complexList")) return { status: 200, body: JSON.stringify({ result: [
          { hscpNo: "1001", hscpNm: "동탄시범한빛마을KCC스위첸", totHsehCnt: 484, lat: 37.2046, lng: 127.0731, dealCnt: 3 }] }) };
        // an answer in another shape (what the phone got): the map list must still be read
        if (url.includes("getComplexArticleList")) return { status: 200, body: JSON.stringify({ isSuccess: true, body: { articleList: [] } }) };
        if (url.includes("cluster/ajax/articleList")) return { status: 200, body: JSON.stringify({ code: "success", more: false, body: [
          art("1"), art("2", { bildNm: "103동", flrInfo: "5/25" }), art("3", { bildNm: "104동", flrInfo: "7/25" }),
          art("8", { atclNm: "동탄시범한빛마을동탄아이파크", bildNm: "201동" })] }) };
        return { status: 404, body: "" };
      },
      async schedule(o) { window.__scheduled = o; }, async collect() { return { snapshots: [] }; },
    };
    window.Capacitor = { isNativePlatform: () => true, Plugins: { AptNet, App: { addListener() {}, getInfo: async () => ({ build: "999" }) } } };
  });
  await page.goto("http://localhost:8766/apt/", { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__scheduled, null, { timeout: 30000 }).catch(() => {});
  const s = await page.evaluate(() => window.__aptwatch.S);
  const units = Object.values(s.units).filter(u => u.cx === "1001");
  if (units.length !== 3) fail.push(`map list: expected KCC's 3 flats (not the neighbour's), got ${units.length}`);
  const snap = s.snaps.filter(x => x.cx === "1001").at(-1);
  if (!snap || snap.src !== "지도") fail.push("map list: snapshot not marked 지도: " + JSON.stringify(snap));
  const job = (await page.evaluate(() => window.__scheduled))?.jobs?.find(j => j.cx === "1001");
  if (!job || !job.url.includes("articleList") || job.hscpNo !== "1001") fail.push("map list: background job not on the map list: " + JSON.stringify(job));
  await page.close();
}

await browser.close();
server.close();
if (fail.length) { console.error(fail.join("\n")); process.exit(1); }
console.log("apt app check passed");
