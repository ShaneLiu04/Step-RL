// Records real Studio sessions (live Edge runs on the local shop) for README GIFs / stills.
// Usage: node record.mjs [baseUrl] [outDir]   (Studio must be running: `step-rl studio`)
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { launch, Recorder } from "./cdp.mjs";

const [base = "http://127.0.0.1:8765", out = "outputs/showcase/frames"] = process.argv.slice(2);
const stills = join(out, "stills");
mkdirSync(stills, { recursive: true });

const page = await launch({ width: 1440, height: 900, port: 9336 });
const still = (name) => page.shot(join(stills, `${name}.png`)).then((f) => console.log("still", f));
const status = `document.getElementById("status-pill").className`;
const terminal = `/success|failed|cancelled|error/.test(${status})`;

async function home(theme = "light") {
  await page.goto(`${base}/?theme=${theme}`, 1600);
  await page.eval(`localStorage.setItem("steprl-theme", ${JSON.stringify(theme)})`);
}

async function typeInto(text, rec, every = 2) {
  await page.eval(`(() => { const t = document.getElementById("instruction"); t.value = ""; t.dispatchEvent(new Event("input")); })()`);
  for (let i = every; i <= text.length + every - 1; i += every) {
    const chunk = text.slice(0, Math.min(i, text.length));
    await page.eval(`(() => { const t = document.getElementById("instruction"); t.value = ${JSON.stringify(chunk)};
      t.dispatchEvent(new Event("input")); })()`);
    if (rec) await rec.frame();
  }
}

async function setApproval(on) {
  await page.eval(`(() => { const s = document.getElementById("sw-approval"); if (s.checked !== ${on}) s.click(); })()`);
}

// ── Scene 1: cart → order transaction with a human approval gate (hero GIF) ──
{
  await home("light");
  await still("01-home");
  const rec = new Recorder(page, join(out, "order"));
  await rec.frame(900);
  await page.click(`.scenario[data-sid="cart-to-order"]`);
  await rec.frame(700);
  await setApproval(true);
  await rec.frame(800);
  await page.click("#btn-send");
  await rec.until(`/awaiting_approval/.test(${status})`, 140, 120000);
  await page.sleep(400);
  await rec.frame(1600);
  await still("03-approval");
  await page.click("#btn-sheet-approve");
  await rec.until(terminal, 140, 120000);
  await page.sleep(600);
  await rec.frame(3000);
  await still("04-order-done");
  console.log("order frames", rec.save());
}

// ── Scene 2: free-form constrained instruction typed by the user ──
{
  await page.click("#btn-new-run");
  await page.sleep(500);
  const rec = new Recorder(page, join(out, "budget"));
  await setApproval(false);
  await rec.frame(500);
  await typeInto("预算650元，买无线充电器和蓝牙耳机各一件，并结算", rec);
  await rec.frame(700);
  await still("02-composer");
  await page.click("#btn-send");
  await rec.until(terminal, 140, 120000);
  await page.sleep(600);
  await rec.frame(2600);
  await still("05-budget-done");
  console.log("budget frames", rec.save());
}

// ── Scene 3: layout v3 (no ids, stepper controls) in dark mode ──
{
  await home("dark");
  const rec = new Recorder(page, join(out, "layout"));
  await rec.frame(700);
  await page.click(`.scenario[data-sid="layout-v3"]`);
  await rec.frame(600);
  await page.click("#btn-send");
  await rec.until(terminal, 140, 120000);
  await page.sleep(600);
  await rec.frame(2600);
  await still("06-dark-layout-v3");
  console.log("layout frames", rec.save());
}

// ── Scene 4: product tour — skills, evidence, audit ──
{
  await home("light");
  const rec = new Recorder(page, join(out, "tour"));
  for (const tab of ["skills", "evidence", "audit"]) {
    await page.click(`.nav-item[data-tab="${tab}"]`);
    await page.sleep(900);
    await rec.frame(1800);
    await still(`07-${tab}`);
    if (tab === "evidence") {
      const body = `(document.querySelector("#view-evidence .scroll-body") || document.querySelector("#view-evidence"))`;
      for (let y = 0; y <= 900; y += 150) {
        await page.eval(`${body}.scrollTo({ top: ${y} })`);
        await rec.frame();
      }
      await rec.frame(1200);
      await still("07-evidence-ledger");
    }
  }
  await page.click(`.nav-item[data-tab="system"]`);
  await page.sleep(800);
  await still("08-system");
  console.log("tour frames", rec.save());
}

{
  await home("dark");
  await page.click(`.nav-item[data-tab="evidence"]`);
  await page.sleep(900);
  await still("09-dark-evidence");
  await page.click(`.nav-item[data-tab="skills"]`);
  await page.sleep(800);
  await still("10-dark-skills");
  await page.eval(`localStorage.setItem("steprl-theme", "light")`);
}

await page.close();
