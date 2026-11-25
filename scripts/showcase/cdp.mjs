// Minimal zero-dependency Chrome DevTools Protocol driver (Node >= 22 global WebSocket).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME_CANDIDATES = [
  process.env.CHROME_BIN,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch({ width = 1600, height = 960, port = 9333, scale = 1 } = {}) {
  const bin = CHROME_CANDIDATES.find((p) => existsSync(p));
  if (!bin) throw new Error("Chrome/Edge binary not found; set CHROME_BIN");
  const profile = mkdtempSync(join(tmpdir(), "steprl-cdp-"));
  const proc = spawn(
    bin,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      `--window-size=${width},${height}`,
      `--force-device-scale-factor=${scale}`,
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "--font-render-hinting=none",
      "about:blank",
    ],
    { stdio: "ignore" }
  );

  let targets = [];
  for (let i = 0; i < 50; i++) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      if (targets.some((t) => t.type === "page")) break;
    } catch {
      /* browser still booting */
    }
    await sleep(200);
  }
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  let seq = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: scale, mobile: false });

  const api = {
    send,
    sleep,
    async goto(url, settleMs = 900) {
      await send("Page.navigate", { url });
      await sleep(settleMs);
    },
    async eval(expression) {
      const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " :: " + expression.slice(0, 120));
      return r.result.value;
    },
    async click(selector) {
      const ok = await api.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false; el.scrollIntoView({block: "nearest"}); el.click(); return true; })()`);
      if (!ok) throw new Error(`click: selector not found: ${selector}`);
    },
    async waitFor(expr, timeoutMs = 30000, pollMs = 120) {
      const t0 = Date.now();
      while (Date.now() - t0 < timeoutMs) {
        if (await api.eval(`!!(${expr})`)) return true;
        await sleep(pollMs);
      }
      throw new Error(`waitFor timeout: ${expr}`);
    },
    async shot(file, { format = "png", quality = 92, clip } = {}) {
      const params = { format, captureBeyondViewport: false };
      if (format === "jpeg") params.quality = quality;
      if (clip) params.clip = { ...clip, scale: 1 };
      const { data } = await send("Page.captureScreenshot", params);
      writeFileSync(file, Buffer.from(data, "base64"));
      return file;
    },
    async close() {
      try {
        await send("Browser.close");
      } catch {
        /* already closed */
      }
      ws.close();
      proc.kill();
    },
  };
  return api;
}

// Records timestamped PNG frames for one scene; frames.json drives GIF timing.
export class Recorder {
  constructor(page, dir) {
    this.page = page;
    this.dir = dir;
    this.meta = [];
    mkdirSync(dir, { recursive: true });
  }

  async frame(holdMs = 0) {
    const file = join(this.dir, `${String(this.meta.length).padStart(4, "0")}.png`);
    await this.page.shot(file);
    this.meta.push({ file, t: Date.now(), hold: holdMs });
    if (holdMs) await sleep(Math.min(holdMs, 300));
  }

  async burst(durationMs, everyMs = 160) {
    const t0 = Date.now();
    while (Date.now() - t0 < durationMs) {
      await this.frame();
      await sleep(everyMs);
    }
  }

  async until(expr, everyMs = 160, timeoutMs = 90000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      await this.frame();
      if (await this.page.eval(`!!(${expr})`)) return;
      await sleep(everyMs);
    }
    throw new Error(`Recorder.until timeout: ${expr}`);
  }

  save() {
    writeFileSync(join(this.dir, "frames.json"), JSON.stringify(this.meta, null, 1));
    return this.meta.length;
  }
}
