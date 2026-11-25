// Usage: node views.mjs [baseUrl] [outDir] — one PNG per Studio tab, light + dark.
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { launch } from "./cdp.mjs";

const [base = "http://127.0.0.1:8765", out = "outputs/showcase/views"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const page = await launch({ width: 1600, height: 1000, port: 9335 });
await page.goto(base, 1800);
const tabs = await page.eval(`[...document.querySelectorAll(".nav-item[data-tab]")].map((n) => n.dataset.tab)`);
for (const theme of ["light", "dark"]) {
  await page.eval(`document.documentElement.dataset.theme = ${JSON.stringify(theme)}`);
  for (const tab of tabs) {
    await page.click(`.nav-item[data-tab="${tab}"]`);
    await page.sleep(700);
    console.log("saved", await page.shot(join(out, `${theme}-${tab}.png`)));
  }
}
await page.close();
