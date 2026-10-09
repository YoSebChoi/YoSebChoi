// Renders icon.svg to the app's icon PNGs with Chromium (Playwright).
//   node fridge/assets/render_icon.mjs   (needs playwright; set CHROMIUM to a browser binary if needed)
import { chromium } from "playwright";
import fs from "fs";
import { fileURLToPath } from "url";
import path from "path";
const dir = path.dirname(fileURLToPath(import.meta.url));
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf8");
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 512, height: 512 } });
// maskable: the fridge inside the safe circle; "any": the same picture a little closer
for (const [file, scale] of [["icon-maskable-512.png", 1], ["icon-512.png", 1.12]]) {
  await page.setContent(`<style>html,body{margin:0;background:#1f6f62;overflow:hidden}svg{display:block;width:512px;height:512px;transform:scale(${scale})}</style>${svg}`);
  await page.screenshot({ path: path.join(dir, file) });
}
await browser.close();
