// Smoke test for the built app, run by the workflow after each build:
// opens docs/matjip in Chromium with the real network and fails when the map
// tiles are not real map images, no places show, or the page throws.
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
}).listen(8765);

const fail = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on("pageerror", e => fail.push("page error: " + e.message));
await page.goto("http://localhost:8765/matjip/", { waitUntil: "networkidle" });
await page.waitForTimeout(3000);

const places = await page.locator(".pin, .cluster").count();
if (!places) fail.push("no places on the map");
const items = await page.locator(".item").count();

// a tile over central Seoul: a real map tile is tens of KB; error images ("API KEY REQUIRED" and the like) are a few KB
const tile = await page.evaluate(async () => {
  const img = document.querySelector(".base-tiles img");
  if (!img) return { error: "no tile layer" };
  const url = img.src.replace(/\/\d+\/\d+\/\d+(@2x)?\.png.*$/, "/14/13970/6345.png");
  const res = await fetch(url);
  return { url, status: res.status, bytes: (await res.arrayBuffer()).byteLength, type: res.headers.get("content-type") };
});
if (tile.error) fail.push(tile.error);
else if (tile.status !== 200 || !/image/.test(tile.type || "") || tile.bytes < 10000) fail.push(`map tile looks wrong: ${JSON.stringify(tile)}`);

const loaded = await page.evaluate(() => [...document.querySelectorAll(".base-tiles img")].filter(i => i.complete && i.naturalWidth > 0).length);
if (!loaded) fail.push("no map tiles loaded");

console.log(JSON.stringify({ places, items, tilesLoaded: loaded, tile }));
await browser.close();
server.close();
if (fail.length) { console.error("App check failed:\n- " + fail.join("\n- ")); process.exit(1); }
console.log("App check passed");
