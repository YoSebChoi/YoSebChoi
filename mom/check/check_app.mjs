// Smoke test for the built app, run by the workflow after each build: opens docs/mom in Chromium
// with the real network and fails when the map tiles do not load, no places show, a place does not
// open with its sources, the 정책 tab is empty, or the page throws. Results are run annotations.
import { chromium } from "playwright";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const root = new URL("../../docs/", import.meta.url).pathname;
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".webmanifest": "application/manifest+json" };
const server = http.createServer(async (req, res) => {
  let path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (path.endsWith("/")) path += "index.html";
  try { res.writeHead(200, { "content-type": types[extname(path)] || "application/octet-stream" }).end(await readFile(join(root, path))); }
  catch { res.writeHead(404).end(); }
}).listen(8766);

const fail = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on("pageerror", e => fail.push("page error: " + e.message));
await page.goto("http://localhost:8766/mom/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
if (await page.locator("#intro").isVisible()) await page.click("#introMap");
await page.click('#radius button[data-r="0"]');
await page.waitForTimeout(800);
const pins = await page.locator(".pin, .cluster").count();
if (!pins) fail.push("no places on the map");
const items = await page.locator(".item").count();
if (!items) fail.push("the list is empty");
const tiles = await page.evaluate(() => [...document.querySelectorAll(".base-tiles img")].filter(i => i.complete && i.naturalWidth > 0).length);
if (!tiles) fail.push("no map tiles loaded");
await page.locator(".item").first().click();
await page.waitForTimeout(500);
const sources = await page.locator("#detail .src").count();
if (!sources) fail.push("a place opened without sources");
await page.click("#back");
await page.click("#polChip");
await page.waitForTimeout(500);
const policyCards = await page.locator("#polBody .pcard").count();
if (!policyCards) fail.push("the 정책 tab is empty");
const result = { pins, items, tiles, sources, policyCards };
console.log(`::notice::app check ${JSON.stringify(result)}`);
await browser.close();
server.close();
if (fail.length) { console.log("::error::App check failed: " + fail.join("; ")); process.exit(1); }
console.log("App check passed");
