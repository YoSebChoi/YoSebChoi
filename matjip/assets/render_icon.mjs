// Renders icon.svg to the app's icon PNGs with Chromium (Playwright), then Pillow scales the small one.
//   node matjip/assets/render_icon.mjs   (needs `npm i playwright`; set CHROMIUM to a browser binary if needed)
import { chromium } from "playwright";
import fs from "fs";
import { fileURLToPath } from "url";
import path from "path";
const dir = path.dirname(fileURLToPath(import.meta.url));
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf8");
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 512, height: 512 } });
// maskable: the bowl inside the safe circle; "any": the same picture a little closer
for (const [file, scale] of [["icon-maskable-512.png", 1], ["icon-512.png", 1.12]]) {
  await page.setContent(`<style>html,body{margin:0;background:#b3221a;overflow:hidden}svg{display:block;width:512px;height:512px;transform:scale(${scale})}</style>${svg}`);
  await page.screenshot({ path: path.join(dir, file) });
}
await browser.close();
