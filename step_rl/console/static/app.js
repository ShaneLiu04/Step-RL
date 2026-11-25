"use strict";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const TOKEN = params.get("token") || "";
const HEADERS = TOKEN ? { "X-Console-Token": TOKEN } : {};

const STATUS = {
  created: "准备中",
  starting: "启动浏览器",
  running: "执行中",
  paused: "已暂停",
  awaiting_approval: "等待确认",
  success: "已完成",
  failed: "未达成",
  error: "出错",
  cancelled: "已取消",
};
const TERMINAL = new Set(["success", "failed", "error", "cancelled"]);
const ACTION_ICON = { click: "i-cursor", type: "i-keyboard", goto: "i-link", scroll: "i-layers", wait: "i-clock", finish: "i-check" };
const ACTION_LABEL = { click: "点击", type: "输入", goto: "跳转", scroll: "滚动", wait: "等待", finish: "完成" };

const state = {
  scenarios: [],
  scenario: null,
  sessionId: null,
  ws: null,
  renderedSteps: 0,
  cartKey: "",
  elapsedBase: 0,
  elapsedAt: 0,
  live: false,
  loaded: {},
};

// ── helpers ───────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const icon = (name, cls = "ic") => `<svg class="${cls}"><use href="#${name}"/></svg>`;
const yuan = (n) => `¥${Number(n || 0).toLocaleString("zh-CN")}`;

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...HEADERS, ...(opts.headers || {}) } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
}

let toastTimer = null;
function toast(msg, ic = "i-check") {
  const el = $("toast");
  el.innerHTML = `${icon(ic, "ic ic-sm")}<span>${esc(msg)}</span>`;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("btn-theme").innerHTML = icon(theme === "dark" ? "i-sun" : "i-moon");
  localStorage.setItem("steprl-theme", theme);
}
applyTheme(params.get("theme") || localStorage.getItem("steprl-theme") || "light");
$("btn-theme").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

// ── navigation ────────────────────────────────────────────────────────────
const LOADERS = { skills: loadSkills, evidence: loadEvidence, audit: loadAudit, system: loadSystem };
function showView(tab) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab}`));
  if (LOADERS[tab]) LOADERS[tab]().catch((e) => toast(e.message, "i-x"));
}
document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.tab)));

// ── scenarios & composer ──────────────────────────────────────────────────
async function loadScenarios() {
  state.scenarios = await api("/api/scenarios");
  $("scenario-grid").innerHTML = state.scenarios
    .map(
      (s) => `<button class="scenario" data-sid="${esc(s.id)}">
        <span class="sc-icon">${icon(s.icon)}</span>
        <span class="sc-title">${esc(s.title)}</span>
        <span class="sc-sub">${esc(s.subtitle)}</span>
        <span class="sc-foot"><span>${esc(s.capability)}</span><span class="mono">${esc(s.evidence)}</span></span>
      </button>`
    )
    .join("");
  document.querySelectorAll(".scenario").forEach((card) => {
    card.addEventListener("click", () => selectScenario(card.dataset.sid));
    card.addEventListener("dblclick", () => { selectScenario(card.dataset.sid); startRun(); });
  });
}

function selectScenario(id) {
  const sc = state.scenarios.find((s) => s.id === id) || null;
  state.scenario = sc;
  document.querySelectorAll(".scenario").forEach((c) => c.classList.toggle("selected", c.dataset.sid === id));
  if (sc) $("instruction").value = sc.instruction;
  syncChip();
  autosize();
}

function syncChip() {
  const sc = state.scenario;
  const text = $("instruction").value.trim();
  const matched = sc && text === sc.instruction;
  if (!matched) state.scenario = null;
  const chip = $("chip-scenario");
  chip.classList.toggle("active", !!matched);
  chip.innerHTML = matched
    ? `${icon("i-target", "ic ic-xs")}场景 · ${esc(sc.title)}${sc.layout !== "v1" ? ` · 布局 ${esc(sc.layout)}` : ""}`
    : `${icon("i-globe", "ic ic-xs")}自定义任务`;
  if (!matched) document.querySelectorAll(".scenario").forEach((c) => c.classList.remove("selected"));
}

function autosize() {
  const ta = $("instruction");
  ta.style.height = "auto";
  ta.style.height = `${Math.min(120, ta.scrollHeight)}px`;
}
$("instruction").addEventListener("input", () => { syncChip(); autosize(); });
$("instruction").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); startRun(); }
});
$("composer").addEventListener("submit", (e) => { e.preventDefault(); startRun(); });

// ── live run ──────────────────────────────────────────────────────────────
async function startRun() {
  const instruction = $("instruction").value.trim();
  if (!instruction) { toast("请先描述任务或选择场景", "i-x"); return; }
  $("btn-send").disabled = true;
  try {
    const snap = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ instruction, scenario: state.scenario?.id || null, require_approval: $("sw-approval").checked }),
    });
    openSession(snap);
    refreshRecent();
  } catch (e) {
    toast(e.message, "i-x");
  } finally {
    $("btn-send").disabled = false;
  }
}

function resetLive() {
  state.renderedSteps = 0;
  state.cartKey = "";
  $("timeline").innerHTML = "";
  $("result-card").classList.add("hidden");
  $("screen").removeAttribute("src");
  $("screen").classList.add("hidden");
  $("screen-empty").classList.remove("hidden");
}

function openSession(snap) {
  if (state.ws) { state.ws.close(); state.ws = null; }
  state.sessionId = snap.id;
  resetLive();
  $("run-idle").classList.add("hidden");
  $("run-live").classList.remove("hidden");
  $("composer").classList.add("hidden");
  showView("run");
  render(snap);
  if (!TERMINAL.has(snap.status)) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
    const ws = new WebSocket(`${proto}://${location.host}/ws/${snap.id}${q}`);
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.id === state.sessionId) render(data);
    };
    ws.onclose = () => { if (state.ws === ws) state.ws = null; };
    state.ws = ws;
  }
}

function backToIdle() {
  if (state.ws) { state.ws.close(); state.ws = null; }
  state.sessionId = null;
  $("run-live").classList.add("hidden");
  $("run-idle").classList.remove("hidden");
  $("composer").classList.remove("hidden");
  $("approval-sheet").classList.add("hidden");
  document.querySelectorAll(".recent-item").forEach((b) => b.classList.remove("active"));
}

function render(s) {
  const terminal = TERMINAL.has(s.status);
  state.live = !terminal;
  $("nav-live").classList.toggle("hidden", terminal);
  const pill = $("status-pill");
  pill.className = `status-pill ${s.status}`;
  pill.innerHTML = `${terminal ? "" : '<span class="spinner" style="width:11px;height:11px;border-width:1.6px"></span>'}${STATUS[s.status] || s.status}`;
  state.elapsedBase = s.elapsed || 0;
  state.elapsedAt = performance.now();
  if (terminal) $("elapsed").textContent = `${(s.elapsed || 0).toFixed(1)}s`;
  $("run-instruction").textContent = s.instruction;
  const sc = state.scenarios.find((x) => x.id === s.scenario);
  $("run-meta").innerHTML = [
    sc ? `<span class="badge info">${icon("i-target", "ic ic-xs")}${esc(sc.title)}</span>` : `<span class="badge">自定义任务</span>`,
    `<span class="badge">布局 ${esc(s.layout || "v1")}</span>`,
    s.require_approval ? `<span class="badge warn">${icon("i-shield", "ic ic-xs")}下单需确认</span>` : "",
    `<span class="badge mono">${esc(s.id)}</span>`,
  ].join("");

  $("url-text").textContent = `shop.local${s.page || "/"}`;
  $("live-badge").classList.toggle("off", terminal);
  $("live-badge").lastChild.textContent = terminal ? "已结束" : "LIVE";
  if (s.screenshot) {
    $("screen").src = `data:image/png;base64,${s.screenshot}`;
    $("screen").classList.remove("hidden");
    $("screen-empty").classList.add("hidden");
  }

  renderCart(s.state || {});
  renderOrder(s.state || {});
  renderSteps(s.steps || [], s);

  $("btn-pause").classList.toggle("hidden", terminal || s.paused);
  $("btn-resume").classList.toggle("hidden", terminal || !s.paused);
  $("btn-cancel").classList.toggle("hidden", terminal);
  $("btn-new-run").classList.toggle("hidden", !terminal);

  const gate = s.status === "awaiting_approval";
  $("approval-sheet").classList.toggle("hidden", !gate);
  if (gate) renderSheet(s.state || {});

  if (terminal) renderResult(s);
  if (terminal && state.ws) { refreshRecent(); }
}

setInterval(() => {
  if (!state.live || !state.sessionId) return;
  const t = state.elapsedBase + (performance.now() - state.elapsedAt) / 1000;
  $("elapsed").textContent = `${t.toFixed(1)}s`;
}, 100);

function renderCart(st) {
  const rows = st.cart || [];
  const key = JSON.stringify(rows);
  const changed = key !== state.cartKey;
  state.cartKey = key;
  $("cart-rows").innerHTML = rows.length
    ? rows.map((r) => `<div class="cart-row ${changed ? "flash" : ""}"><span class="qty">×${r.qty}</span><span class="name">${esc(r.name)}</span><span class="sub">${yuan(r.subtotal)}</span></div>`).join("")
    : '<div class="muted">空</div>';
  $("cart-total").textContent = yuan(st.cart_total);
}

function renderOrder(st) {
  const o = st.order;
  if (!o) {
    const promo = st.promo;
    $("order-box").innerHTML = promo
      ? `<div class="order-line"><span>已领取优惠</span><b>${esc(promo.label || promo.code || "")}</b></div><div class="muted">尚未下单</div>`
      : '<div class="muted">尚未下单</div>';
    return;
  }
  const promo = o.promo || {};
  $("order-box").innerHTML = `
    <div class="order-line"><span>订单号</span><b>${esc(o.id || "")}</b></div>
    <div class="order-line"><span>商品总额</span><b>${yuan(o.total)}</b></div>
    <div class="order-line"><span>优惠</span><b>${promo.applied ? `−${yuan(promo.discount)} · ${esc(promo.label || promo.code || "")}` : "—"}</b></div>
    <div class="order-line" style="align-items:baseline"><span>实付</span><span class="order-paid">${yuan(o.paid ?? o.total)}</span></div>
    <div><span class="badge ok">${icon("i-check", "ic ic-xs")}服务端已确认</span></div>`;
}

function renderSteps(steps, s) {
  const list = $("timeline");
  for (let i = state.renderedSteps; i < steps.length; i++) {
    const st = steps[i];
    const kind = st.ok ? st.action : "err";
    const li = document.createElement("li");
    li.className = "tl";
    li.innerHTML = `
      <span class="tl-icon ${esc(kind)}">${icon(st.ok ? ACTION_ICON[st.action] || "i-bolt" : "i-x", "ic ic-sm")}</span>
      <div class="tl-main">
        <div class="tl-title">${ACTION_LABEL[st.action] || esc(st.action)} ${st.target ? `<span class="tgt">· ${esc(st.target)}</span>` : ""}</div>
        <div class="tl-sub">${esc(st.error || st.thought || st.detail || (st.source === "skill" ? "编译技能动作" : ""))}${st.detail && !st.error && st.thought ? ` · ${esc(st.detail)}` : ""}</div>
      </div>
      <span class="tl-ms">${st.ms}ms</span>`;
    list.appendChild(li);
  }
  state.renderedSteps = steps.length;
  $("step-count").textContent = `${steps.length} 步`;
  const gateRow = list.querySelector(".tl.gate");
  if (s.status === "awaiting_approval" && !gateRow) {
    const li = document.createElement("li");
    li.className = "tl gate";
    li.innerHTML = `<span class="tl-icon">${icon("i-shield", "ic ic-sm")}</span><div class="tl-main"><div class="tl-title">人工确认门禁</div><div class="tl-sub">等待批准「提交订单」</div></div><span class="tl-ms">—</span>`;
    list.appendChild(li);
  } else if (gateRow && s.status !== "awaiting_approval") {
    gateRow.querySelector(".tl-sub").textContent = s.approved ? "已由人工批准" : "门禁已结束";
    list.appendChild(gateRow);
  }
  list.scrollTop = list.scrollHeight;
}

function renderSheet(st) {
  const rows = (st.cart || []).map((r) => `<div class="cart-row"><span class="qty">×${r.qty}</span><span class="name">${esc(r.name)}</span><span class="sub">${yuan(r.subtotal)}</span></div>`).join("");
  const promo = st.promo ? `<div class="order-line"><span>优惠</span><b>${esc(st.promo.label || st.promo.code || "")}</b></div>` : "";
  $("sheet-summary").innerHTML = `${rows || '<div class="muted">购物车为空</div>'}<div class="cart-total"><span>合计</span><b>${yuan(st.cart_total)}</b></div>${promo}`;
}

function renderResult(s) {
  const r = s.result || {};
  const ok = s.status === "success";
  const obs = s.observation || {};
  const hit = obs.calls ? Math.round((100 * (obs.hits || 0)) / obs.calls) : null;
  const title = ok ? "任务完成 · 服务端验证通过" : STATUS[s.status] || "未完成";
  const sub = ok
    ? `${r.skill_steps || 0} 个技能动作，全程未调用 LLM`
    : esc(s.error || r.detail || (r.fallback_required ? "超出已覆盖能力，需要端侧 LLM 兜底" : "验证器未判定成功"));
  $("result-card").innerHTML = `
    <div class="result-head">
      <span class="result-icon ${ok ? "" : "fail"}">${icon(ok ? "i-check" : "i-x")}</span>
      <div><div class="result-title">${title}</div><div class="result-sub">${sub}</div></div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="tile-v">${r.actions ?? (s.steps || []).length}</div><div class="tile-l">真实动作</div></div>
      <div class="tile"><div class="tile-v good">${r.prompt_tokens ?? 0}</div><div class="tile-l">LLM tokens</div></div>
      <div class="tile"><div class="tile-v">${(s.elapsed || 0).toFixed(1)}s</div><div class="tile-l">端到端耗时</div></div>
      <div class="tile"><div class="tile-v">${r.policy_steps ?? 0}</div><div class="tile-l">策略步</div></div>
      <div class="tile"><div class="tile-v">${hit === null ? "—" : `${hit}%`}</div><div class="tile-l">观测缓存命中</div></div>
      <div class="tile"><div class="tile-v">${obs.roundtrips ?? "—"}</div><div class="tile-l">观测往返</div></div>
    </div>`;
  $("result-card").classList.remove("hidden");
}

async function act(name) {
  if (!state.sessionId) return;
  try {
    const snap = await api(`/api/sessions/${state.sessionId}/${name}`, { method: "POST" });
    render(snap);
    if (name === "approve") toast("已批准提交订单");
    if (name === "cancel") toast("任务已取消", "i-x");
  } catch (e) {
    toast(e.message, "i-x");
  }
}
$("btn-pause").addEventListener("click", () => act("pause"));
$("btn-resume").addEventListener("click", () => act("resume"));
$("btn-cancel").addEventListener("click", () => act("cancel"));
$("btn-sheet-approve").addEventListener("click", () => act("approve"));
$("btn-sheet-cancel").addEventListener("click", () => act("cancel"));
$("btn-new-run").addEventListener("click", backToIdle);

// ── recent sessions ───────────────────────────────────────────────────────
async function refreshRecent() {
  const rows = await api("/api/sessions").catch(() => []);
  $("recent").innerHTML = rows.length
    ? rows
        .slice(0, 12)
        .map(
          (r) => `<button class="recent-item ${r.id === state.sessionId ? "active" : ""}" data-id="${esc(r.id)}">
            <div class="recent-title">${esc(r.instruction)}</div>
            <div class="recent-sub"><span class="dot ${TERMINAL.has(r.status) ? "" : "live"}" style="${r.status === "success" ? "background:var(--green)" : TERMINAL.has(r.status) ? "background:var(--red)" : ""}"></span>${STATUS[r.status] || r.status} · ${r.steps} 步</div>
          </button>`
        )
        .join("")
    : '<div class="recent-empty">暂无运行</div>';
  document.querySelectorAll(".recent-item").forEach((b) =>
    b.addEventListener("click", async () => openSession(await api(`/api/sessions/${b.dataset.id}`)))
  );
}

// ── skills ────────────────────────────────────────────────────────────────
let skillData = null;
let skillKind = "";
const KIND = { compiled: ["编译", "info"], transaction: ["事务", "warn"], induced: ["归纳", "ok"] };
async function loadSkills() {
  skillData = await api("/api/skills");
  renderSkills();
}
function renderSkills() {
  const items = skillData.compiled.filter((s) => !skillKind || s.kind === skillKind);
  $("skill-grid").innerHTML = items
    .map((s) => {
      const [label, cls] = KIND[s.kind] || [s.kind, ""];
      const chain = s.steps.map((x) => `<span class="step-chip">${esc(x)}</span>`).join('<span class="step-arrow">›</span>');
      return `<div class="card skill">
        <div class="skill-top"><span class="skill-title">${esc(s.title)}</span><span class="badge ${cls}">${label}</span></div>
        <div class="skill-sum">${esc(s.summary)}</div>
        <div class="step-chips">${chain}</div>
        <div class="skill-ev">${esc(s.evidence)} · <span>${esc(s.name)}</span></div>
      </div>`;
    })
    .join("");
  const induced = skillData.induced || [];
  $("induced-box").innerHTML = induced.length
    ? `<table class="table"><thead><tr><th>操作</th><th>技能</th><th>步数</th><th>成功率</th><th>状态</th></tr></thead><tbody>${induced
        .map((i) => `<tr><td class="mono">${esc(i.operation)}</td><td>${esc(i.name)}</td><td>${i.steps}</td><td>${i.success_rate === null ? "—" : `${Math.round(i.success_rate * 100)}% (${i.successes}/${i.attempts})`}</td><td>${i.demoted ? '<span class="badge danger">已淘汰</span>' : '<span class="badge ok">可用</span>'}</td></tr>`)
        .join("")}</tbody></table>`
    : `<div class="empty">${icon("i-spark", "ic ic-sm")}本进程尚未归纳新技能。端侧 LLM 兜底成功一次后，轨迹会自动参数化并注册到这里（AR019 / AR034）。</div>`;
  const mem = skillData.memory || { records: 0, pages: {} };
  const max = Math.max(1, ...Object.values(mem.pages));
  $("memory-box").innerHTML = `<div class="card-head" style="margin:0">${icon("i-stack", "ic ic-sm")}状态 → 动作模板 <span class="muted">${mem.records} 条 · 仅来自训练任务</span></div>
    <div class="mem-bars">${Object.entries(mem.pages)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<div class="mem-bar"><span class="mono">${esc(k)}</span><div class="bar-track"><div class="bar-fill" style="width:${(100 * v) / max}%"></div></div><span class="mono">${v}</span></div>`)
      .join("")}</div>`;
}
document.querySelectorAll("#skill-seg .seg-item").forEach((b) =>
  b.addEventListener("click", () => {
    skillKind = b.dataset.kind;
    document.querySelectorAll("#skill-seg .seg-item").forEach((x) => x.classList.toggle("active", x === b));
    if (skillData) renderSkills();
  })
);

// ── evidence ──────────────────────────────────────────────────────────────
async function loadEvidence() {
  const d = await api("/api/evidence");
  $("kpi-grid").innerHTML = d.headline
    .map((k) => `<div class="card kpi"><div class="kpi-l">${esc(k.label)}</div><div class="kpi-v">${esc(k.value)}</div><div class="kpi-d">${esc(k.detail)}</div><div class="kpi-s">${esc(k.source)}</div></div>`)
    .join("");
  $("ablations").innerHTML = d.ablations
    .map(
      (a) => `<div class="abl"><div class="abl-l">${esc(a.label)}<small>${esc(a.source)}</small></div><div class="abl-bars">
        <div class="abl-bar"><div class="bar-track"><div class="bar-fill" style="width:${a.value}%"></div></div><span>${a.value}%</span></div>
        <div class="abl-bar"><div class="bar-track"><div class="bar-fill base" style="width:${Math.max(a.baseline, 1.5)}%"></div></div><span>${a.baseline}% ${esc(a.baseline_label)}</span></div>
      </div></div>`
    )
    .join("");
  const at = d.attempts;
  const C = 2 * Math.PI * 52;
  const kept = (at.kept / at.total) * C;
  $("attempts").innerHTML = `
    <div class="ring"><svg viewBox="0 0 128 128"><defs><linearGradient id="rg" x1="0" x2="1"><stop offset="0" stop-color="#2ef2c2"/><stop offset="0.5" stop-color="#38bdf8"/><stop offset="1" stop-color="#8b7cff"/></linearGradient></defs>
      <circle cx="64" cy="64" r="52" fill="none" stroke="rgba(120,120,128,.15)" stroke-width="13"/>
      <circle cx="64" cy="64" r="52" fill="none" stroke="url(#rg)" stroke-width="13" stroke-linecap="round" stroke-dasharray="${kept} ${C}"/>
      <circle cx="64" cy="64" r="52" fill="none" stroke="#ff9f0a" stroke-width="13" stroke-dasharray="${C / at.total - 3} ${C}" stroke-dashoffset="${-kept - 2}"/></svg>
      <div class="ring-center"><b>${at.kept}/${at.total}</b><span>进入最优组合</span></div></div>
    <div class="att-legend">
      <div><i style="background:var(--grad)"></i>${at.kept} 次尝试进入最终架构</div>
      <div><i style="background:#ff9f0a"></i>${at.archived} 次归档为负结果 (AR002)</div>
      <div class="muted small">负结果同样有价值：它们排除了错误路线</div>
    </div>`;
  $("milestones").innerHTML = d.milestones
    .map(
      (m) => `<div class="ms"><span class="ms-layer">${esc(m.layer)}</span>
        <div class="ms-fail"><b>${esc(m.failure)}</b><small>${esc(m.ars)}</small></div>
        <div class="ms-delta"><span class="from">${esc(m.before)}</span>${icon("i-link", "ic ic-xs")}<span class="to">${esc(m.after)}</span></div>
        <div class="ms-value">${esc(m.value)}</div></div>`
    )
    .join("");
  const maxS = Math.max(1, ...d.scenarios.map((s) => s.seconds));
  $("scenario-dots").innerHTML = d.scenarios
    .map((s) => {
      const t = s.seconds / maxS;
      const color = `color-mix(in srgb, #8b7cff ${Math.round(t * 100)}%, #2ef2c2)`;
      return `<div class="sdot ${s.perturb ? "perturb" : ""} ${s.success ? "" : "fail"}" style="background-color:${color}" title="${esc(s.instruction)} · ${s.layout} · ${s.seconds}s · ${s.steps} 步"></div>`;
    })
    .join("");
}

// ── audit ─────────────────────────────────────────────────────────────────
async function loadAudit() {
  const rows = await api("/api/audit");
  $("audit-grid").innerHTML = rows.length
    ? rows
        .map(
          (r) => `<div class="card audit">
            ${r.has_final
              ? `<div class="audit-thumb"><img data-final="${esc(r.id)}" alt="最终画面" /></div>`
              : `<div class="audit-thumb empty">${icon("i-clock", "ic")}<span>未产生最终画面</span></div>`}
            <div class="audit-body">
              <div class="audit-title">${esc(r.instruction || "—")}</div>
              <div class="audit-meta">
                ${r.success === true ? '<span class="badge ok">成功</span>' : r.success === false ? '<span class="badge danger">未达成</span>' : '<span class="badge">未完成</span>'}
                ${r.approval ? '<span class="badge warn">人工确认</span>' : ""}
                <span>${r.actions ?? 0} 动作 · ${r.events} 事件</span>
              </div>
              <div class="audit-meta mono">${esc(r.id)} · ${esc((r.ts || "").replace("T", " "))}</div>
            </div>
          </div>`
        )
        .join("")
    : `<div class="empty">${icon("i-clock", "ic ic-sm")}还没有运行记录。</div>`;
  document.querySelectorAll("img[data-final]").forEach(async (img) => {
    const res = await fetch(`/api/audit/${img.dataset.final}/final.png`, { headers: HEADERS });
    if (res.ok) img.src = URL.createObjectURL(await res.blob());
  });
}
$("btn-refresh-audit").addEventListener("click", () => loadAudit().catch((e) => toast(e.message, "i-x")));

// ── system ────────────────────────────────────────────────────────────────
async function loadSystem() {
  const m = await api("/api/meta");
  const apis = [
    ["get", "/api/scenarios", "评测场景"],
    ["post", "/api/sessions", "创建真实运行"],
    ["ws", "/ws/{id}", "实时快照流"],
    ["post", "/api/sessions/{id}/pause|resume|approve|cancel", "人在回路控制"],
    ["get", "/api/skills", "技能库与统计"],
    ["get", "/api/evidence", "证据数据"],
    ["get", "/api/audit", "审计索引"],
  ];
  $("sys-grid").innerHTML = `
    <div class="card"><div class="card-head">${icon("i-cpu", "ic ic-sm")}运行时</div><dl class="kv">
      <dt>服务</dt><dd>${esc(m.service)} v${esc(m.version)}</dd>
      <dt>浏览器</dt><dd class="mono">${esc(m.browser)} · headless</dd>
      <dt>执行引擎</dt><dd>${esc(m.runtime)}</dd>
      <dt>并发上限</dt><dd>${m.limits.active} 个实时会话</dd>
      <dt>指令长度</dt><dd>≤ ${m.limits.instruction} 字</dd></dl></div>
    <div class="card"><div class="card-head">${icon("i-shield", "ic ic-sm")}安全边界</div><dl class="kv">
      <dt>访问令牌</dt><dd>${m.token_required ? '<span class="badge ok">已启用</span>' : '<span class="badge warn">本地模式</span>'} <span class="muted small">CONSOLE_TOKEN · 常量时间比较</span></dd>
      <dt>动作白名单</dt><dd class="mono">click · type · goto · scroll · wait · finish</dd>
      <dt>导航范围</dt><dd>仅限本地商城主机</dd>
      <dt>高风险动作</dt><dd>提交订单可设人工确认门禁</dd>
      <dt>成功判定</dt><dd>服务端状态 / 订单页证据</dd></dl></div>
    <div class="card"><div class="card-head">${icon("i-cart", "ic ic-sm")}商品目录</div><table class="table"><thead><tr><th>ID</th><th>商品</th><th>价格</th><th>库存</th></tr></thead><tbody>${m.products
      .map((p) => `<tr><td class="mono">${esc(p.pid)}</td><td>${esc(p.name)}</td><td class="mono">${yuan(p.price)}</td><td class="mono">${p.stock}</td></tr>`)
      .join("")}</tbody></table>
      <div class="step-chips" style="margin-top:10px">${m.promos.map((p) => `<span class="badge info">${esc(p.label)}</span>`).join("")}</div></div>
    <div class="card"><div class="card-head">${icon("i-link", "ic ic-sm")}API</div><div class="api-list">${apis
      .map(([meth, path, desc]) => `<div><span class="method ${meth}">${meth.toUpperCase()}</span><span class="mono">${esc(path)}</span><span class="muted">${esc(desc)}</span></div>`)
      .join("")}</div></div>`;
}

// ── boot ──────────────────────────────────────────────────────────────────
(async function boot() {
  try {
    const meta = await api("/api/meta");
    $("brand-sub").textContent = `v${meta.version} · Edge Agent`;
    await loadScenarios();
    await refreshRecent();
  } catch (e) {
    toast(e.message, "i-x");
  }
})();
