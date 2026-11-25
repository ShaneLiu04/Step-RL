// Usage: node shot.mjs <url> <out.png> [width] [height] [scale]   (SHOT_TRANSPARENT=1 for alpha)
import { launch } from "./cdp.mjs";

const [url, out, w = "1600", h = "960", s = "1"] = process.argv.slice(2);
const b = await launch({ width: +w, height: +h, scale: +s, port: 9334 });
if (process.env.SHOT_TRANSPARENT) {
  await b.send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
}
await b.goto(url, 1500);
await b.shot(out);
await b.close();
console.log("saved", out);
