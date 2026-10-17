const ICONS = {"dashboard": "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z", "activity": "M2 12h5l3-8 4 16 3-8h5", "pulse": "M3 12h4l2-5 4 10 3-5h5M5 4a9 9 0 0 1 14 0", "chart": "M4 3v17h17M8 15l4-5 4 2 5-7", "lab": "M9 3h6M10 3v7l-6 9a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3M8 15h8", "map": "M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2zM9 3v16M15 5v16", "calendar": "M4 5h16v16H4zM8 3v4M16 3v4M4 10h16", "clock": "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2", "queue": "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01", "hospital": "M9 3h6v6h6v6h-6v6H9v-6H3V9h6z", "plus": "M12 5v14M5 12h14", "minus": "M5 12h14", "locate": "M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "sort": "M8 4v16M4 16l4 4 4-4M15 5h6M15 10h4M15 15h2", "prev": "M15 5l-7 7 7 7", "next": "M9 5l7 7-7 7", "play": "M8 4l12 8-12 8z", "pause": "M8 4v16M16 4v16"};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]||ICONS.activity}"/></svg>`;
document.querySelectorAll("[data-icon]").forEach(el=>el.innerHTML=icon(el.dataset.icon));
document.querySelectorAll(".tabs button").forEach(el=>el.title=el.textContent.trim());

const COLORS = ["#aa94f8", "#e8bc77", "#75bca3", "#82b5d2", "#d39dbb"];
const $ = id => document.getElementById(id);
const cache = new Map();  // hour string -> payload
let hours = [], idx = 0, timer = null;

const fmtHour = s => new Date(s.replace(" ", "T") + "Z").toLocaleString("en-US",
  { weekday: "short", month: "short", day: "numeric", hour: "numeric", timeZone: "UTC" });
const pct = x => (x * 100).toFixed(0) + "%";
const fx = (v, d = 2) => (v === null || v === undefined ? "–" : v.toFixed(d));
const get = async path => { const r = await fetch(path); if (!r.ok) throw new Error(path); return r.json(); };

const pendingBatches = new Map();
async function ensure(i) {
  const h = hours[i];
  if (!h || cache.has(h)) return;
  if (pendingBatches.has(h)) return pendingBatches.get(h);
  const end = hours[Math.min(i + 23, hours.length - 1)];
  const request = get(`/replay?start=${encodeURIComponent(h)}&end=${encodeURIComponent(end)}`).then(data=>{for(const p of data)cache.set(p.at,p)}).finally(()=>pendingBatches.delete(h));
  pendingBatches.set(h,request); return request;
}

function card(b) {
  const band = b.band === "insufficient_data" ? "none" : b.band;
  const outcome = b.realized_stress === null ? "outcome: not enough high-acuity calls"
    : b.realized_stress ? "outcome: stressed hour" : "outcome: normal hour";
  return `<div class="panel card ${band}">
    <h3>${b.borough.replace("RICHMOND / ", "")}<span class="band">${b.band.replace("_", " ")}</span></h3>
    <div class="risk">${pct(b.p_stress)}</div>
    <div class="kv">
      <span>bottleneck</span><b>${b.bottleneck}</b>
      <span>waiting, high acuity</span><b>${b.pending_high}</b>
      <span>waiting, low acuity (held)</span><b>${b.pending_low} (${b.held_pending_low})</b>
      <span>oldest wait</span><b>${Math.round(b.oldest_pending_age_s / 60)} min</b>
      <span>dispatch / travel dev</span><b>${b.dispatch_dev ?? "–"} / ${b.travel_dev ?? "–"}</b>
    </div>
    <div class="note">${b.briefing}
      <span class="${b.briefing_verified ? "verified" : "rejected"}">${b.briefing_verified ? "✓ verified" : "✗ rejected"}</span></div>
    <div class="outcome">${outcome}</div>
  </div>`;
}

function drawChart(canvasId = "chart", legendId = "legend") {
  const c = $(canvasId); if (!c.clientWidth) return;
  const ctx = c.getContext("2d"), dpr = window.devicePixelRatio || 1;
  c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr; ctx.scale(dpr, dpr);
  const W = c.clientWidth, H = c.clientHeight, pad = 28;
  ctx.clearRect(0, 0, W, H);
  const win = hours.slice(Math.max(0, idx - 47), idx + 1).map(h => cache.get(h)).filter(Boolean);
  if (!win.length) return;
  const names = win[win.length - 1].boroughs.map(b => b.borough);
  ctx.strokeStyle = "#2a3542"; ctx.fillStyle = "#8b98a5"; ctx.font = "11px system-ui";
  for (const y of [0, .5, 1]) {
    const py = H - pad - y * (H - 2 * pad);
    ctx.beginPath(); ctx.moveTo(pad, py); ctx.lineTo(W - 8, py); ctx.stroke(); ctx.fillText(pct(y), 0, py + 4);
  }
  const x = i => pad + (i / Math.max(win.length - 1, 1)) * (W - pad - 8);
  ctx.fillText(new Date(win[0].at.replace(" ","T")).toLocaleString("en-US",{month:"short",day:"numeric",hour:"numeric"}),pad,H-5);
  ctx.textAlign="right"; ctx.fillText("Selected hour",W-8,H-5); ctx.textAlign="left";
  names.forEach((n, k) => {
    ctx.strokeStyle = ctx.fillStyle = COLORS[k % COLORS.length]; ctx.lineWidth = 2; ctx.beginPath();
    win.forEach((p, i) => {
      const b = p.boroughs.find(b => b.borough === n); if (!b) return;
      const py = H - pad - b.p_stress * (H - 2 * pad);
      i ? ctx.lineTo(x(i), py) : ctx.moveTo(x(i), py);
    });
    ctx.stroke();
    win.forEach((p, i) => {
      const b = p.boroughs.find(b => b.borough === n);
      if (b && b.realized_stress === 1) {
        ctx.beginPath(); ctx.arc(x(i), H - pad - b.p_stress * (H - 2 * pad), 3.5, 0, 7); ctx.fill();
      }
    });
  });
  $(legendId).innerHTML = names.map((n, k) =>
    `<span><i style="background:${COLORS[k % COLORS.length]}"></i>${n.replace("RICHMOND / ", "")}</span>`).join("");
}

const planCache = new Map();
async function getPlan(h) {
  let p = planCache.get(h);
  if (!p) { p = await get(`/plan?at=${encodeURIComponent(h)}`); planCache.set(h, p); }
  return p;
}
async function renderPlan() {
  const h = hours[idx];
  let p;
  try { p = await getPlan(h); }
  catch { if (hours[idx] === h) $("plan").textContent = "Plan unavailable: re-run scripts/run_pipeline.py with this version to add the fleet estimate."; return; }
  if (hours[idx] !== h) return;  // the slider moved on
  const nm = b => b.replace("RICHMOND / ", "");
  const rows = p.boroughs.map(r => `<tr><td>${nm(r.borough)}</td><td>${r.queue_high + r.queue_low}</td><td>${r.expected_calls.toFixed(0)}</td>
    <td>${r.idle} / ${r.fleet.toFixed(0)}</td><td>${r.capacity_before.toFixed(0)} → ${r.capacity_after.toFixed(0)}</td>
    <td>${r.unmet_before.toFixed(0)} → ${r.unmet_after.toFixed(0)}</td>
    <td>${r.sends ? "sends " + r.sends : r.receives ? "receives " + r.receives : "–"}</td></tr>`).join("");
  $("plan").innerHTML = `<ul>${p.actions.map(a => `<li>${a}</li>`).join("")}</ul>
    <table><tr><th>borough</th><th>waiting</th><th>expected calls</th><th>free / fleet (est.)</th><th>capacity</th><th>calls unserved</th><th>plan</th></tr>${rows}</table>
    <p class="foot">${p.units_moved} unit${p.units_moved === 1 ? "" : "s"} moved · plan value ${p.value_before.toFixed(0)} → ${p.value_after.toFixed(0)}
      (severity-weighted calls served minus transit cost, unitless).</p>`;
}
async function drawSupPlan() {
  const h = hours[idx];
  try {
    const plan = await getPlan(h);
    if (hours[idx] !== h) return;
    const acts = (plan.actions || []).filter(a => !/no (units|moves|relocation)/i.test(a));
    $("sup-plan").classList.remove("hidden");
    $("sup-plan-list").innerHTML = acts.length ? acts.map(a => `<li>${a}</li>`).join("") : "<li>No unit moves recommended this hour.</li>";
  } catch { $("sup-plan").classList.add("hidden"); }
}

let showRevision = 0;
async function show(i) {
  if (!hours.length) return;
  const revision = ++showRevision;
  idx = Math.max(0, Math.min(i, hours.length - 1));
  $("slider").value = idx;
  const target = idx;
  await ensure(target);
  for (let j = Math.max(0, target - 47); j < target; j += 24) await ensure(j);
  if (revision !== showRevision) return;
  const p = cache.get(hours[idx]);
  $("clock").textContent = fmtHour(hours[idx]);
  if (p) $("cards").innerHTML = [...p.boroughs].sort((a, b) => b.p_stress - a.p_stress).map(card).join("");
  renderPlan(); drawSupPlan();
  drawChart(); drawSup(); drawMap();
}

function renderEval(e) {
  const rows = Object.entries(e.evaluation).map(([name, r]) =>
    `<tr><td>${name.replaceAll("_", " ")}</td><td>${fx(r.pr_auc, 3)}</td><td>${fx(r.alert_precision)}</td>
     <td>${fx(r.alert_recall)}</td><td>${fx(r.onset_recall)}</td><td>${fx(r.false_alerts_per_day, 1)}</td></tr>`).join("");
  const c = e.cascade, base = Object.values(e.evaluation)[0].base_rate;
  $("eval").innerHTML = `<table><tr><th>model</th><th>PR-AUC</th><th>alert precision</th><th>alert recall</th>
    <th>onset recall</th><th>false alerts / day</th></tr>${rows}</table>
    <p class="foot">Test window ${e.windows.test[0].slice(0, 10)} → ${e.windows.test[1].slice(0, 10)}, base rate ${pct(base)}.
    Severity cascade: adding the low-acuity backlog changes PR-AUC by ${c.delta >= 0 ? "+" : ""}${c.delta.toFixed(3)}
    (95% CI ${c.delta_ci95.map(v => v.toFixed(3)).join(" to ")}).</p>`;
}

function renderBench(b) {
  $("bench").innerHTML = `<table>
    <tr><td>machine</td><td>${b.machine}</td></tr>
    <tr><td>replay throughput</td><td>${b.replay_events_per_s.toLocaleString()} events/s</td></tr>
    <tr><td>single-request scoring p50 / p99</td><td>${b.score_p50_ms} / ${b.score_p99_ms} ms</td></tr>
    <tr><td>batch scoring</td><td>${b.batch_rows_per_s.toLocaleString()} rows/s</td></tr></table>`;
}

async function init() {
  const h = await get("/health");
  $("platform").textContent = `scored live on ${h.computed_on} · ${h.model_version}`;
  if (h.computed_on === "s390x") $("platform").classList.add("s390x");
  if (h.data_source === "SYNTHETIC") {
    $("source").textContent = "SYNTHETIC DATA"; $("data-notice").classList.remove("hidden"); $("data-notice").textContent = "Synthetic replay data · queue and risk values are simulated. Map boundaries and ZIP reference locations are real."; $("source").classList.add("synthetic");
  } else $("source").remove();
  const e = await get("/evaluation");
  renderEval(e);
  get("/benchmark").then(renderBench).catch(() => $("bench").textContent = "run the benchmark on this machine");
  const start = new Date(e.windows.test[0].replace(" ", "T") + "Z"), end = new Date(e.windows.test[1].replace(" ", "T") + "Z");
  const pad = n => String(n).padStart(2, "0");
  for (let t = start; t <= end; t = new Date(t.getTime() + 3600e3))
    hours.push(`${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())} ${pad(t.getUTCHours())}:00:00`);
  $("slider").max = hours.length - 1;
  await show(Math.min(47,hours.length-1));
  get("/moments").then(mo => {
    const jump = h => { const i = hours.indexOf(h.replace("T", " ")); if (i >= 0) show(i); };
    $("moments").innerHTML = `<span>Jump to an onset (${mo.n_caught}/${mo.n_onsets} caught):</span>` +
      mo.caught.slice(0, 5).map((r, k) => `<button class="mom" data-h="${r.replay_from}" data-k="${k}">${fmtHour(r.hour)} · ${r.borough.replace("RICHMOND / ", "")}</button>`).join("") +
      (mo.missed.length ? `<button class="mom miss" data-h="${mo.missed[0].replay_from}">a miss: ${fmtHour(mo.missed[0].hour)}</button>` : "");
    document.querySelectorAll(".mom").forEach(b => b.onclick = () => jump(b.dataset.h));
  }).catch(() => {});
}

$("slider").oninput = e => show(+e.target.value);
$("play").onclick = () => {
  if (timer) { clearInterval(timer); timer = null; $("play").innerHTML = icon("play") + "Play"; return; }
  $("play").innerHTML = icon("pause") + "Pause";
  timer = setInterval(() => idx < hours.length - 1 ? show(idx + 1) : $("play").click(), +$("speed").value);
};
$("speed").onchange = () => { if (timer) { $("play").click(); $("play").click(); } };

// ---------------- policy lab ----------------
let lab = null, series = null, li = 0, labTimer = null;
const ARM_LABEL = {baseline: "Baseline", handover_shock: "Handover shock", shock_baseline: "Shock · no reserves",
  shock_reactive: "Shock · reactive reserves", shock_ai: "Shock · AI-warned reserves",
  shock_rebalance: "Shock · units rebalanced", shock_rebalance_ai: "Shock · rebalanced + warning risk"};
const METRIC_LABEL = {units_relocated: "Units relocated (per run)",
  low_p90_wait_min: "Low-acuity P90 wait (min)", low_mean_wait_min: "Low-acuity mean wait (min)",
  worst_borough_low_p90_wait_min: "Worst borough, low-acuity P90 (min)", high_p90_wait_min:"High-acuity P90 wait (min)", high_mean_wait_min: "High-acuity mean wait (min)",
  p90_wait_min: "All-call P90 wait (min)", high_share_within_10min: "High-acuity on scene ≤ 10 min",
  worst_borough_high_p90_wait_min: "Worst borough, high-acuity P90 (min)"};

function expTable(rows) {
  return `<table><tr><th>metric</th><th>${ARM_LABEL[rows[0].a]}</th><th>${ARM_LABEL[rows[0].b]}</th><th>diff (95% CI)</th><th></th></tr>` +
    rows.map(c => {
      const sig = c.ci95[0] > 0 || c.ci95[1] < 0;
      const f = v => (c.metric.includes("share") ? (v * 100).toFixed(1) + "%" : v.toFixed(2));
      const d = v => (c.metric.includes("share") ? (v * 100).toFixed(1) : v.toFixed(2));
      return `<tr><td>${METRIC_LABEL[c.metric] || c.metric}</td><td>${f(c.mean_a)}</td><td>${f(c.mean_b)}</td>
        <td>${c.diff >= 0 ? "+" : ""}${d(c.diff)} (${d(c.ci95[0])} to ${d(c.ci95[1])})</td>
        <td class="${sig ? "yes" : "no"}">${sig ? "detectable" : "no clear difference"}</td></tr>`;
    }).join("") + "</table>";
}

function world(name, i) {
  const s = series[name], rows = [];
  for (const [b, v] of Object.entries(s.boroughs)) {
    const work = Math.max(0, v.busy[i] - v.at_hospital[i]);
    const dots = "d-idle,".repeat(v.idle[i]) + "d-work,".repeat(work) + "d-hosp,".repeat(v.at_hospital[i]);
    const q = "q-high,".repeat(Math.min(v.q_high[i], 60)) + "q-low,".repeat(Math.min(v.q_low[i], 60));
    rows.push(`<div class="brow"><div class="bname"><b>${b.replace("RICHMOND / ", "")}</b>
      ${v.q_high[i]} high · ${v.q_low[i]} low waiting${v.reserve_active[i] ? '<span class="res">+reserves</span>' : ""}</div>
      <div><div class="dots">${dots.split(",").filter(Boolean).map(c => `<span class="dot ${c}"></span>`).join("")}</div>
      <div class="qrow">${q.split(",").filter(Boolean).map(c => `<span class="q ${c}"></span>`).join("")}</div></div></div>`);
  }
  return rows.join("");
}

function citywide(name) {
  const bs = Object.values(series[name].boroughs);
  return series[name].t.map((_, i) => bs.reduce((a, v) => a + v.q_low[i], 0));
}

function drawLab() {
  const c = $("lab-chart"); if (!c.clientWidth) return;
  const ctx = c.getContext("2d"), dpr = window.devicePixelRatio || 1;
  c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr; ctx.scale(dpr, dpr);
  const W = c.clientWidth, H = c.clientHeight, pad = 28, a = $("arm-a").value, b = $("arm-b").value;
  ctx.clearRect(0, 0, W, H);
  const T = series[a].t, ya = citywide(a), yb = citywide(b), max = Math.max(4, ...ya, ...yb);
  const x = m => pad + (m / T[T.length - 1]) * (W - pad - 8), y = v => H - pad - (v / max) * (H - 2 * pad);
  const sh = lab.shock;
  if (sh) { ctx.fillStyle = "rgba(232,163,61,.12)"; ctx.fillRect(x(sh.start_h * 60), pad, x(sh.end_h * 60) - x(sh.start_h * 60), H - 2 * pad); }
  ctx.strokeStyle = "#2a3542"; ctx.fillStyle = "#8b98a5"; ctx.font = "11px system-ui";
  for (const v of [0, Math.round(max / 2), max]) { ctx.beginPath(); ctx.moveTo(pad, y(v)); ctx.lineTo(W - 8, y(v)); ctx.stroke(); ctx.fillText(v, 0, y(v) + 4); }
  for (let d = 0; d * 1440 <= T[T.length - 1]; d++) ctx.fillText(["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][(new Date(series[a].t0.replace(" ", "T")).getDay() + 6 + d) % 7], x(d * 1440) + 2, H - 8);
  [[a, ya, "#e8a33d"], [b, yb, "#4ea1ff"]].forEach(([name, ys, col]) => {
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.beginPath();
    ys.forEach((v, i) => i ? ctx.lineTo(x(T[i]), y(v)) : ctx.moveTo(x(T[i]), y(v))); ctx.stroke();
    ctx.fillStyle = col;
    for (const act of series[name].activations) { const px = x(act.at_min); ctx.beginPath(); ctx.moveTo(px, H - pad); ctx.lineTo(px - 4, H - pad + 7); ctx.lineTo(px + 4, H - pad + 7); ctx.fill(); }
  });
  ctx.strokeStyle = "#e6edf3"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x(T[li]), pad); ctx.lineTo(x(T[li]), H - pad); ctx.stroke();
}

function showLab(i) {
  li = Math.max(0, Math.min(i, series[$("arm-a").value].t.length - 1));
  $("lab-slider").value = li;
  const t0 = new Date(series[$("arm-a").value].t0.replace(" ", "T"));
  $("lab-clock").textContent = new Date(t0.getTime() + series[$("arm-a").value].t[li] * 60e3)
    .toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  for (const side of ["a", "b"]) {
    const name = $("arm-" + side).value, sm = series[name].summary;
    $("world-" + side).innerHTML = world(name, li);
    $("sum-" + side).textContent = `high-acuity P90 wait ${sm.high_p90_wait_min.toFixed(1)} min · reserves ${sm.reserve_unit_h} unit-h`;
    $("leg-" + side).textContent = ARM_LABEL[name] || name;
  }
  drawLab();
}

async function initLab() {
  if (lab) return;
  try { [lab, series] = await Promise.all([get("/lab"), get("/lab/series")]); }
  catch { $("lab-note").textContent = "No simulation yet: run scripts/run_policy_lab.py on this machine."; return; }
  const sc = lab.scenario;
  $("lab-note").textContent = `SIMULATION · calls replayed from ${lab.data_source === "SYNTHETIC" ? "SYNTHETIC data" : "FDNY data"}, week of ${lab.eval_week}; ` +
    `fleet, handover and cross-borough travel are scenario assumptions. ${lab.seeds} seeds per arm, run on ${lab.computed_on}. Shown: seed 0.`;
  for (const side of ["a", "b"]) {
    $("arm-" + side).innerHTML = Object.keys(series).map(k => `<option value="${k}">${ARM_LABEL[k] || k}</option>`).join("");
    $("arm-" + side).onchange = () => showLab(li);
  }
  $("arm-a").value = "shock_reactive"; $("arm-b").value = "shock_ai";
  $("exp1").innerHTML = expTable(lab.experiment1);
  $("exp2").innerHTML = expTable(lab.experiment2.filter(c => c.a === "shock_reactive")) +
    expTable(lab.experiment2.filter(c => c.a === "shock_baseline"));
  if (lab.experiment3) {
    $("exp3-panel").classList.remove("hidden");
    $("exp3").innerHTML = expTable(lab.experiment3.filter(c => c.a === "shock_baseline")) +
      expTable(lab.experiment3.filter(c => c.a === "shock_rebalance")) +
      `<p class="foot">Units relocated per run: ${Object.entries(lab.relocation_use).map(([k, v]) => `${ARM_LABEL[k] || k} ${v.units_relocated.toFixed(0)}`).join(", ")}.
      Relocation times from the ${lab.rebalance.transfer} matrix (scenario assumption), plan re-solved every ${lab.rebalance.rebalance_min} min.</p>`;
  }
  $("scenario").innerHTML = `Units per borough (calibrated to pre-test median dispatch wait): ${Object.entries(sc.units).map(([b, n]) => `${b.replace("RICHMOND / ", "")} ${n}`).join(", ")}. ` +
    `On scene ${sc.scene_min} min, transport share ${sc.transport_share}, transport ${sc.transport_min} min, handover ${sc.handover_min} min, ` +
    `handover slots ${Object.values(sc.handover_slots).join("/")}. Shock: ${lab.shock.borough} handover ×${lab.shock.factor}, hours ${lab.shock.start_h}–${lab.shock.end_h} of the week. ` +
    `Reserves: ${sc.reserve_units} units × ${sc.reserve_hours} h per activation, budget ${sc.reserve_budget_unit_h} unit-h; reactive trigger ≥ ${sc.reactive_queue} high-acuity waiting. ` +
    `Warning model: ${lab.warning_model.label}, trained on weeks ${lab.train_weeks.join(", ")}.`;
  $("lab-slider").max = series[$("arm-a").value].t.length - 1;
  showLab(Math.round(((lab.shock.start_h - 2) * 60) / series[$("arm-a").value].step_min));
}

$("lab-slider").oninput = e => showLab(+e.target.value);
$("lab-play").onclick = () => {
  if (labTimer) { clearInterval(labTimer); labTimer = null; $("lab-play").innerHTML = icon("play") + "Play"; return; }
  $("lab-play").innerHTML = icon("pause") + "Pause";
  labTimer = setInterval(() => li < +$("lab-slider").max ? showLab(li + 1) : $("lab-play").click(), 120);
};
// Dashboard: one selection shared by the map, ranked queue and decision detail.
const WORD = {alert:'Alert',watch:'Watch',normal:'Normal',insufficient_data:'No label'};
const BAND_COLOR = {alert:'#f18484',watch:'#e8bc77',normal:'#75bca3',insufficient_data:'#666879'};
const pressureLabel = value => value === "normal" ? "No elevated pressure" : /pressure|handover/i.test(value) ? value : `${value} pressure`;
const boroughName = n => n.replace('RICHMOND / ', '').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
const safe = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let mapFocus = null, spatial = null, boundaries = null;
let layers = {density:true,hospitals:false,bases:false};
let mapBox = [0,0,800,560];
let evidenceOpen = false;
function tile(b,k) {
  const selected = b.borough === mapFocus;
  return `<button class="priority-row${selected?' selected':''}" style="--band:${BAND_COLOR[b.band]||BAND_COLOR.insufficient_data}" data-borough="${safe(b.borough)}" aria-pressed="${selected}"><span class="rank">${String(k+1).padStart(2,'0')}</span><span><span class="priority-name"><i></i>${boroughName(b.borough)}</span><span class="priority-meta">${b.pending_high+b.pending_low} waiting · ${safe(pressureLabel(b.bottleneck))}</span></span><span class="priority-score">${b.band==='insufficient_data'?'—':pct(b.p_stress)}<small>${WORD[b.band]||'No label'}</small></span></button>`;
}
function drawDetail(b) {
  if (!b) { $("borough-detail").innerHTML=`<div class="detail-eyebrow">BOROUGH BRIEF</div><h3 class="detail-title">${boroughName(mapFocus)}</h3><p class="empty-state">No replay records are available for this borough at the selected hour.</p>`; return; }
  const why=(b.top_factors||[]).map(f=>`${f.feature.replaceAll('_',' ')} ${f.direction==='up'?'↑':'↓'}`).join(' · ');
  const later=b.realized_stress==null?'Outcome unavailable for this hour.':b.realized_stress?'Realized outcome: the queue ran late.':'Realized outcome: within the normal range.';
  $('borough-detail').innerHTML=`<div class="detail-eyebrow">BOROUGH BRIEF<span>${b.briefing_verified?'✓ Verified note':'Unverified note'}</span></div><h3 class="detail-title">${boroughName(b.borough)}<span class="band-pill" style="--band:${BAND_COLOR[b.band]}">${WORD[b.band]}</span></h3><div class="detail-metrics"><div><b>${b.pending_high}</b><span>High-acuity waiting</span></div><div><b>${b.pending_low}</b><span>Low-acuity waiting</span></div><div><b>${Math.round(b.oldest_pending_age_s/60)}<small> min</small></b><span>Oldest pending</span></div></div><div class="action-note"><small>↗ RECOMMENDED ACTION</small><p>${safe((b.action||'Monitor the queue and review at the next hour.').replace('Recommend: ',''))}</p></div><details id="borough-evidence"${evidenceOpen?' open':''}><summary>Evidence & replay outcome</summary><p>${b.p_onset!=null&&b.band!=='insufficient_data'?`Chance it turns late from a normal hour (onset model): ${pct(b.p_onset)}.<br>`:''}${safe(b.briefing)}<br>${safe(why||'No signals above baseline.')}<br>${b.held_pending_low} low-acuity calls held without a unit${b.at_hospital!=null?`; ${b.at_hospital} units at hospital`:''}.</p><div class="outcome">${later}</div></details>`;
  $('borough-evidence').ontoggle=e=>evidenceOpen=e.target.open;
}
function drawSup() {
  const p=cache.get(hours[idx]);
  if (!p) return;
  const bs=[...p.boroughs].sort((a,b)=>(a.band==='insufficient_data')-(b.band==='insufficient_data')||b.p_stress-a.p_stress);
  if (!mapFocus) mapFocus=bs[0]?.borough;
  $('sup-when').textContent=fmtHour(hours[idx]);
  $('tiles').innerHTML=bs.map(tile).join('');
  $('tiles').querySelectorAll('[data-borough]').forEach(el=>el.onclick=()=>selectBorough(el.dataset.borough));
  const sum=key=>bs.reduce((s,b)=>s+(b[key]||0),0);
  const alerts=bs.filter(b=>b.band==='alert').length, watch=bs.filter(b=>b.band==='watch').length;
  $('stat-risk').innerHTML=`${alerts+watch}<small>/ ${bs.length}</small>`;
  $('stat-risk-note').innerHTML=`<span class="alert-text">${alerts} alert</span><span aria-hidden="true"> · </span><span class="watch-text">${watch} watch</span>`;
  $('stat-high').textContent=sum('pending_high').toLocaleString();
  $('stat-low').textContent=sum('pending_low').toLocaleString();
  $('stat-held').textContent=`${sum('held_pending_low')} held without a unit`;
  $('stat-oldest').innerHTML=`${Math.round(Math.max(...bs.map(b=>b.oldest_pending_age_s||0))/60)}<small>min</small>`;
  $('sup-slider').max=hours.length-1; $('sup-slider').value=idx;
  $('sup-prev').disabled=idx===0; $('sup-next').disabled=idx>=hours.length-1;
  $('replay-range').textContent=`${hours[0].slice(0,10)} — ${hours.at(-1).slice(0,10)} · NYC local time`;
  drawDetail(bs.find(b=>b.borough===mapFocus));
  drawChart('sup-chart','sup-legend');
}
function selectBorough(name) {
  const focusId=document.activeElement?.closest("#tiles, #sup-map, #map")?.id;
  mapFocus=name; evidenceOpen=false; drawSup();drawMap();
  if(focusId){const selected=[...$(focusId).querySelectorAll("[data-borough]")].find(el=>el.dataset.borough===name);selected?.focus({preventScroll:true})}
  document.querySelectorAll('#cards .card').forEach(el=>el.classList.toggle('selected',el.dataset.borough===name));
}
$('sup-prev').onclick=()=>show(idx-1);
$('sup-next').onclick=()=>show(idx+1);
$('sup-slider').oninput=e=>show(+e.target.value);
$('sup-play').onclick=()=>$('play').click();
function syncPlay(){ $('sup-play').innerHTML=timer?`${icon('pause')}Pause replay`:`${icon('play')}Play replay`; $('sup-play').setAttribute('aria-pressed',String(!!timer)); }
new MutationObserver(syncPlay).observe($('play'),{childList:true});
$('sup-jump').onchange=e=>{const i=hours.indexOf(e.target.value);if(i>=0)show(i)};
$('open-warning').onclick=()=>$('tab-warn').click();
get('/moments').then(m=>{
  for(const r of(m.caught||[]).slice(0,8)){
    const option=document.createElement('option');option.value=r.replay_from;option.textContent=`${fmtHour(r.hour)} · ${boroughName(r.borough)}${r.warned_hour_before?' · warned an hour early':''}`;$('sup-jump').append(option);
  }
}).catch(()=>{$('sup-jump').options[0].textContent='No saved moments';$('sup-jump').disabled=true});
// Geographic coordinates are fitted with longitude corrected at NYC's latitude.
function proj(lat,lon){return[400+(lon+73.975)*835,280+(40.705-lat)*1100]}
const labelPoints={'MANHATTAN':[40.785,-73.985],'BRONX':[40.87,-73.868],'BROOKLYN':[40.642,-73.963],'QUEENS':[40.735,-73.81],'RICHMOND / STATEN ISLAND':[40.579,-74.145]};
const geoName=n=>n==='Staten Island'?'RICHMOND / STATEN ISLAND':n.toUpperCase();
function geoPath(g){
  const polys=g.type==='MultiPolygon'?g.coordinates:[g.coordinates];
  return polys.map(poly=>poly.map(ring=>ring.map(([lon,lat],i)=>{const[x,y]=proj(lat,lon);return`${i?'L':'M'}${x.toFixed(1)},${y.toFixed(1)}`}).join('')+'Z').join('')).join('');
}
function mapContent(){
  const payload=cache.get(hours[idx]),bs=payload?.boroughs||[],lookup=Object.fromEntries(bs.map(b=>[b.borough,b]));
  const grid=`<defs><pattern id="geo-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" class="map-grid" fill="none"/></pattern></defs><rect x="-1500" y="-1500" width="4000" height="4000" fill="url(#geo-grid)"/>`;
  const land=boundaries?boundaries.features.map(f=>{
    const n=geoName(f.properties.boroname),b=lookup[n],col=BAND_COLOR[b?.band]||BAND_COLOR.insufficient_data;
    return `<g class="geo-borough${n===mapFocus?' selected':''}" data-borough="${safe(n)}" role="button" tabindex="0" aria-label="${safe(f.properties.boroname)}, ${WORD[b?.band]||'no label'}, ${b?.band==='insufficient_data'?'risk unavailable':b?pct(b.p_stress)+' next-hour risk':payload?'no replay records':'loading risk'}" aria-pressed="${n===mapFocus}"><path d="${f._path}" style="fill:${col};fill-opacity:${n===mapFocus?.21:.1}" fill-rule="evenodd"/><title>${safe(f.properties.boroname)} · ${WORD[b?.band]||'no label'}</title></g>`;
  }).join(''):'';
  const maxN=spatial?Math.max(...spatial.zones.map(z=>z.n_calls)):1;
  const density=spatial&&layers.density?spatial.zones.map(z=>{
    const[x,y]=proj(z.lat,z.lon),col=BAND_COLOR[lookup[z.borough]?.band]||BAND_COLOR.insufficient_data;
    return `<circle class="density-dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(1.3+6.3*Math.sqrt(z.n_calls/maxN)).toFixed(1)}" fill="${col}" stroke="${col}" fill-opacity="${!mapFocus||mapFocus===z.borough?.48:.21}" stroke-opacity=".45"><title>ZIP ${z.zipcode}: ${z.n_calls.toLocaleString()} recorded calls</title></circle>`;
  }).join(''):'';
  const hospitals=spatial&&layers.hospitals?spatial.hospitals.map(h=>{const[x,y]=proj(h.lat,h.lon);return `<g><circle cx="${x}" cy="${y}" r="5" fill="#192b32" stroke="#8ec6d7" stroke-width=".6"/><path d="M${x-2.5},${y}h5M${x},${y-2.5}v5" stroke="#b6dfef" stroke-width="1.2"/><title>${safe(h.facility_name)}</title></g>`}).join(''):'';
  const bases=spatial&&layers.bases?spatial.bases.map(b=>{const[x,y]=proj(b.lat,b.lon);return `<path d="M${x},${y-4}l4,7h-8Z" fill="#e8bc77" stroke="#14161c" stroke-width=".8"><title>SCENARIO: assumed base, dispatch area ${b.dispatch_area}</title></path>`}).join(''):'';
  const labels=Object.entries(labelPoints).map(([n,[lat,lon]])=>{const[x,y]=proj(lat,lon),b=lookup[n];return `<g class="geo-label" transform="translate(${x},${y})" text-anchor="middle"><text>${boroughName(n)}<tspan x="0" dy="16" fill="${BAND_COLOR[b?.band]||'#8e919e'}">${b?.band==='insufficient_data'?'No label':b?pct(b.p_stress)+' risk':payload?'No replay data':'—'}</tspan></text></g>`}).join('');
  const waters=`<text class="water-label" transform="translate(352,220) rotate(-66)">HUDSON RIVER</text><text class="water-label" transform="translate(402,285) rotate(-57)">EAST RIVER</text><text class="water-label" x="390" y="484">LOWER NEW YORK BAY</text><text class="water-label" x="180" y="225" style="font-style:normal;font-size:9px;letter-spacing:2.5px;fill:#3c454d">NEW JERSEY</text>`;
  return grid+land+waters+density+hospitals+bases+labels;
}
// Early warning map: ZIP areas (NYC MODZCTA, /geo) coloured by borough risk, real travel to scene, or real calls per 1,000 residents.
let zctas=null,mapMode='risk',brk={};
const SEQ=['#34323f','#4f4670','#7262a8','#9a86e0','#d2c6ff'];  // dark = low, bright = high
const quantiles=(vals,qs)=>{const s=vals.filter(v=>v!=null).sort((a,b)=>a-b);return qs.map(q=>s[Math.floor(q*(s.length-1))])};
const seqCol=(v,br)=>v==null?BAND_COLOR.insufficient_data:SEQ[br.filter(b=>v>=b).length];
function zipContent(){
  const payload=cache.get(hours[idx]),lookup=Object.fromEntries((payload?.boroughs||[]).map(b=>[b.borough,b]));
  const win=spatial?.data_window_months||3;
  const zips=zctas.map(f=>{
    const p=f.properties,b=lookup[p.borough];
    const col=mapMode==='travel'?seqCol(p.travel_s,brk.travel):mapMode==='rate'?seqCol(p.calls_per_1k,brk.rate):BAND_COLOR[b?.band]||BAND_COLOR.insufficient_data;
    const tip=`ZIP ${p.zips.slice(0,3).join(', ')}${p.zips.length>3?'…':''} · ${boroughName(p.borough||'')}\n${p.n_calls.toLocaleString()} EMS calls in ${win} months · ${p.pop.toLocaleString()} residents\n${p.calls_per_1k??'–'} calls per 1,000 residents\nmedian travel to scene ${p.travel_s==null?'–':(p.travel_s/60).toFixed(1)+' min'}${b?`\nborough this hour: ${WORD[b.band]||b.band} · ${pct(b.p_stress)}`:''}`;
    return `<g class="geo-zip${p.borough===mapFocus?' selected':''}" data-borough="${safe(p.borough)}"><path d="${f._path}" style="fill:${col};fill-opacity:${mapMode==='risk'?(!mapFocus||p.borough===mapFocus?.42:.18):.85}" fill-rule="evenodd"/><title>${safe(tip)}</title></g>`;
  }).join('');
  const outlines=boundaries?boundaries.features.map(f=>`<path class="geo-outline" d="${f._path}" fill="none" fill-rule="evenodd"/>`).join(''):'';
  const hospitals=spatial&&layers.hospitals?spatial.hospitals.map(h=>{const[x,y]=proj(h.lat,h.lon);return `<g><circle cx="${x}" cy="${y}" r="5" fill="#192b32" stroke="#8ec6d7" stroke-width=".6"/><path d="M${x-2.5},${y}h5M${x},${y-2.5}v5" stroke="#b6dfef" stroke-width="1.2"/><title>${safe(h.facility_name)}</title></g>`}).join(''):'';
  const bases=spatial&&layers.bases?spatial.bases.map(b=>{const[x,y]=proj(b.lat,b.lon);return `<path d="M${x},${y-4}l4,7h-8Z" fill="#e8bc77" stroke="#14161c" stroke-width=".8"><title>SCENARIO: assumed base, dispatch area ${b.dispatch_area}, ${(b.fleet_share*100).toFixed(1)}% of the fleet</title></path>`}).join(''):'';
  return zips+outlines+hospitals+bases;
}
function mapLegend(){
  if(!zctas)return;
  const win=spatial?.data_window_months||3;
  const scale=(br,fmt)=>`<span>&lt; ${fmt(br[0])}</span>${SEQ.map(c=>`<span><i style="background:${c}"></i></span>`).join('')}<span>&gt; ${fmt(br[3])}</span>`;
  $('map-legend').innerHTML=(mapMode==='travel'?`<span>Median travel to scene, by ZIP, last ${win} months (real):</span>${scale(brk.travel,v=>(v/60).toFixed(1)+' min')}`
    :mapMode==='rate'?`<span>EMS calls per 1,000 residents, last ${win} months (real):</span>${scale(brk.rate,v=>v.toFixed(0))}`
    :['alert','watch','normal','insufficient_data'].map(k=>`<span><i style="background:${BAND_COLOR[k]}"></i>${WORD[k].toLowerCase()}</span>`).join(''))
    +(layers.hospitals?`<span style="color:#9fd3ff">+ hospital (NYS DOH, real)</span>`:'')+(layers.bases?`<span style="color:#e8bc77">▲ assumed ambulance base (SCENARIO)</span>`:'');
}
for(const b of $('map-mode').querySelectorAll('button'))b.onclick=()=>{
  mapMode=b.dataset.m;
  for(const o of $('map-mode').querySelectorAll('button')){o.classList.toggle('on',o===b);o.setAttribute('aria-pressed',String(o===b))}
  drawMap();
};
// Travel between boroughs: the spatial model's matrix that the policy lab uses for cross-borough moves (SCENARIO input).
function drawTravel(){
  if(!spatial)return;
  const tm=spatial.travel_matrix;
  if(!tm){$('tm').innerHTML="<p class='foot'>Travel matrix not built (spatial/build_matrix.py).</p>";$('tm-scale').innerHTML='';return}
  const h=$('tm-hour').value===''?(hours[idx]?+hours[idx].slice(11,13):12):+$('tm-hour').value;
  const br=quantiles(Object.values(tm.minutes_by_hour).flat(),[.2,.4,.6,.8]),bs=tm.boroughs;
  $('tm').innerHTML=`<table class="heat"><tr><th>from ↓ to →</th>${bs.map(b=>`<th>${boroughName(b)}</th>`).join('')}</tr>`+
    bs.map(a=>`<tr><th>${boroughName(a)}</th>${bs.map(b=>{const v=(tm.minutes_by_hour[`${a}|${b}`]||[])[h];
      return v==null?'<td>–</td>':`<td style="background:${seqCol(v,br)}${br.filter(x=>v>=x).length>=3?';color:#191a20':''}" title="${boroughName(a)} → ${boroughName(b)} at ${h}:00: ${v.toFixed(1)} min">${v.toFixed(0)}</td>`}).join('')}</tr>`).join('')+'</table>';
  $('tm-scale').innerHTML=`<span>shorter</span>${SEQ.map(c=>`<span><i style="background:${c}"></i></span>`).join('')}<span>longer · minutes at ${h}:00</span>`;
  $('tm-note').textContent=`${tm.note||''} SCENARIO input: used by the policy lab for cross-borough moves, not observed unit trips.`;
}
for(let h=0;h<24;h++)$('tm-hour').insertAdjacentHTML('beforeend',`<option value="${h}">${h}:00</option>`);
$('tm-hour').onchange=drawTravel;

function drawMap(){
  drawTravel();
  if(!boundaries)return;
  for(const id of ['sup-map','map']){
    const svg=$(id);svg.innerHTML=id==='map'&&zctas?zipContent():mapContent();
    svg.querySelectorAll('[data-borough]').forEach(el=>{
      el.onclick=()=>{if(!didPan)selectBorough(el.dataset.borough)};
      el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectBorough(el.dataset.borough)}};
    });
  }
  $('sup-map').setAttribute('viewBox',mapBox.join(' '));
  mapLegend();
}
for(const name of Object.keys(layers))$(`layer-${name}`).onclick=()=>{layers[name]=!layers[name];$(`layer-${name}`).classList.toggle('on',layers[name]);$(`layer-${name}`).setAttribute('aria-pressed',String(layers[name]));drawMap()};
function zoomMap(factor){
  const w=Math.max(260,Math.min(1120,mapBox[2]*factor)),h=w*.7;
  mapBox=[mapBox[0]+(mapBox[2]-w)/2,mapBox[1]+(mapBox[3]-h)/2,w,h];drawMap();
  $('map-zoom-in').disabled=w<=260;$('map-zoom-out').disabled=w>=1120;
}
$('map-zoom-in').onclick=()=>zoomMap(.8);$('map-zoom-out').onclick=()=>zoomMap(1.25);
$('map-reset').onclick=()=>{mapBox=[0,0,800,560];drawMap();$('map-zoom-in').disabled=false;$('map-zoom-out').disabled=false};
let dragStart=null,didPan=false;
$('sup-map').addEventListener('pointerdown',e=>{if(e.button!==0)return;didPan=false;dragStart={x:e.clientX,y:e.clientY,box:[...mapBox]}});
$('sup-map').addEventListener('pointermove',e=>{
  if(!dragStart)return;
  const dx=e.clientX-dragStart.x,dy=e.clientY-dragStart.y;
  if(Math.hypot(dx,dy)<5&&!didPan)return;
  didPan=true;$('sup-map').setPointerCapture(e.pointerId);
  const scale=Math.min($('sup-map').clientWidth/dragStart.box[2],$('sup-map').clientHeight/dragStart.box[3]);
  mapBox=[dragStart.box[0]-dx/scale,dragStart.box[1]-dy/scale,...dragStart.box.slice(2)];$('sup-map').setAttribute('viewBox',mapBox.join(' '));
});
for(const name of ['pointerup','pointercancel','lostpointercapture'])$('sup-map').addEventListener(name,()=>{dragStart=null});
Promise.allSettled([get('/spatial'),get('/assets/boroughs.geojson')]).then(([sp,geo])=>{
  if(sp.status==='fulfilled')spatial=sp.value;
  else{for(const name of Object.keys(layers)){$(`layer-${name}`).disabled=true;$(`layer-${name}`).title='Spatial reference data unavailable'}$('sup-map-stage').querySelector('.map-hint').textContent='Call-density reference unavailable'}
  if(geo.status==='fulfilled'){boundaries=geo.value;boundaries.features.forEach(f=>f._path=geoPath(f.geometry));drawMap()}
  else{$('sup-map').innerHTML='<text x="400" y="280" text-anchor="middle" fill="#f18484">Geographic layer unavailable. Reload to retry.</text>'}
  // ZIP areas for the early warning map; without /geo it keeps the ZIP centroid dots
  get('/geo').then(g=>{
    zctas=g.zctas.features;zctas.forEach(f=>f._path=geoPath(f.geometry));
    const zp=zctas.map(f=>f.properties);
    brk={travel:quantiles(zp.map(p=>p.travel_s),[.2,.4,.6,.8]),rate:quantiles(zp.map(p=>p.calls_per_1k),[.2,.4,.6,.8])};
    $('map-mode').classList.remove('hidden');
    const v=spatial?.provenance?.travel_model_validation;
    $('map-prov').textContent='ZIP areas: NYC DOHMH MODZCTA; borough lines: NYC DCP (both NYC Open Data, real). Incidents are located to ZIP code only; no unit positions exist in public data and none are drawn.'+
      (v?` Spatial travel model checked on held-out ZIP codes (${v.method}): ${v.zips_evaluated} ZIPs, median error ${Math.round(v.median_abs_error_s_by_zip)} s, correlation ${v.correlation_pred_vs_obs_by_zip.toFixed(2)}.`:'');
    if(new URLSearchParams(location.search).get('map')==='travel')$('map-mode').querySelector('[data-m="travel"]').click();
    else drawMap();
  }).catch(()=>{});
});

// ---- overview: interactive hour-of-day chart ----
const YEARC = { "2023": "#b9d3f2", "2024": "#7fadea", "2025": "#4a8adf", "2026": "#1b4f9c" };
let ov = null, ovHidden = new Set(), ovHoverX = null;
function drawOverview() {
  if (!ov || !$("ov-chart").clientWidth) return;
  const c = $("ov-chart"), ctx = c.getContext("2d"), dpr = window.devicePixelRatio || 1;
  c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr; ctx.scale(dpr, dpr);
  const W = c.clientWidth, H = c.clientHeight, L = 44, R = 12, T = 10, B = 26;
  ctx.clearRect(0, 0, W, H);
  const data = ov[$("ov-metric").value][$("ov-borough").value] || {};
  const years = Object.keys(data).sort().filter(y => !ovHidden.has(y));
  const vmax = Math.max(1, ...years.flatMap(y => data[y].map(v => v ?? 0))) * 1.08;
  const x = h => L + (W - L - R) * h / 23, y = v => T + (H - T - B) * (1 - v / vmax);
  ctx.strokeStyle = "#2a3542"; ctx.fillStyle = "#8b98a5"; ctx.font = "11px IBM Plex Sans, system-ui"; ctx.textAlign = "right";
  for (let k = 0; k <= 4; k++) { const v = vmax * k / 4, yy = y(v); ctx.beginPath(); ctx.moveTo(L, yy); ctx.lineTo(W - R, yy); ctx.stroke(); ctx.fillText(v.toFixed(v < 10 ? 1 : 0), L - 6, yy + 4); }
  ctx.textAlign = "center";
  for (const h of [0, 6, 12, 18, 23]) ctx.fillText(h + ":00", x(h), H - 8);
  for (const yr of years) {
    ctx.strokeStyle = YEARC[yr] || "#ccc"; ctx.lineWidth = yr === "2026" ? 2.4 : 1.6; ctx.beginPath();
    data[yr].forEach((v, h) => { if (v == null) return; h === 0 ? ctx.moveTo(x(h), y(v)) : ctx.lineTo(x(h), y(v)); });
    ctx.stroke();
  }
  if (ovHoverX != null) {
    const h = Math.round(Math.max(0, Math.min(1, (ovHoverX - L) / (W - L - R))) * 23);
    ctx.strokeStyle = "#5c6773"; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(x(h), T); ctx.lineTo(x(h), H - B); ctx.stroke(); ctx.setLineDash([]);
    for (const yr of years) { const v = data[yr][h]; if (v == null) continue; ctx.fillStyle = YEARC[yr]; ctx.beginPath(); ctx.arc(x(h), y(v), 4, 0, 7); ctx.fill(); }
    $("ov-hover").textContent = `${h}:00 → ` + years.map(yr => `${yr}: ${(data[yr][h] ?? 0).toFixed(1)}`).join("   ");
  }
  $("ov-years").innerHTML = Object.keys(data).sort().map(yr => `<button class="chart-year" data-y="${yr}" aria-pressed="${!ovHidden.has(yr)}"><i style="background:${YEARC[yr]}"></i>${yr}</button>`).join("");
  for (const el of $("ov-years").querySelectorAll("[data-y]")) el.onclick = () => { const yr = el.dataset.y; ovHidden.has(yr) ? ovHidden.delete(yr) : ovHidden.add(yr); drawOverview(); };
}
$("ov-chart").onmousemove = e => { ovHoverX = e.offsetX; drawOverview(); };
$("ov-chart").onmouseleave = () => { ovHoverX = null; $("ov-hover").textContent = "hover the chart for values"; drawOverview(); };
$("ov-borough").onchange = drawOverview; $("ov-metric").onchange = drawOverview;

async function initOverview() {
  if ($("local").dataset.done) { drawOverview(); return; }
  const o = await get("/overview");
  ov = o;
  $("ov-borough").innerHTML = Object.keys(o.calls_by_hour).sort().map(b => `<option value="${b}">${b.replace("RICHMOND / ", "")}</option>`).join("");
  drawOverview();
  const conc = Object.entries(o.boroughs_stressed_at_once_pct).map(([k, v]) => `<tr><td>${k} borough${k > 1 ? "s" : ""} at once</td><td>${v}%</td></tr>`).join("");
  const slack = Object.entries(o.pct_hours_another_borough_holds_zero).map(([b, v]) => `<tr><td>${b.replace("RICHMOND / ", "")}</td><td>${v ?? "–"}%</td></tr>`).join("");
  $("local").innerHTML = `<p class="foot">${o.stressed_hours.toLocaleString()} hours with at least one stressed borough</p>
    <table><tr><th>how many boroughs stressed</th><th>share of those hours</th></tr>${conc}</table>
    <p class="foot" style="margin-top:10px">When this borough is stressed, another borough is holding zero low-acuity calls in…</p>
    <table>${slack}</table>`;
  $("local").dataset.done = 1;
}

const TABS = [["tab-sup", "view-sup"], ["tab-over", "view-over"], ["tab-warn", "view-warn"], ["tab-lab", "view-lab"]];
const HASH = { "tab-sup": "supervisor", "tab-over": "overview", "tab-warn": "warning", "tab-lab": "lab" };
for (const [tab, view] of TABS)
  $(tab).onclick = () => {
    history.replaceState(null, "", location.search + "#" + HASH[tab]);  // deep link, e.g. /#lab
    for (const [t2, v2] of TABS) { $(t2).classList.toggle("on", t2 === tab); $(v2).classList.toggle("hidden", v2 !== view); if(t2===tab)$(t2).setAttribute("aria-current","page");else $(t2).removeAttribute("aria-current"); }
    $("page-name").textContent = {"view-sup":"Dashboard","view-warn":"Early warning","view-over":"Historical analysis","view-lab":"Policy lab"}[view];
    if (view !== "view-lab" && labTimer) $("lab-play").click();
    if (view === "view-lab" || view === "view-over") { if (timer) $("play").click(); }
    if (view === "view-lab") initLab().then(() => series && showLab(li));
    else if (view === "view-over") initOverview().catch(e => { $("local").textContent = "overview unavailable: " + e.message; });
    else if (view === "view-sup") drawSup();
    else { drawChart(); drawMap(); }
  };
window.onresize = () => { drawChart(); drawChart("sup-chart","sup-legend"); if (series) drawLab(); drawOverview(); };
// keyboard: ←/→ step an hour, space plays (replay tabs) or plays the lab
document.addEventListener("keydown", e => {
  if (e.target.closest("input, select, textarea, button, [role=button]") || e.metaKey || e.ctrlKey || e.altKey) return;
  const labOn = !$("view-lab").classList.contains("hidden");
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault(); const d = e.key === "ArrowRight" ? 1 : -1;
    if (labOn) { if (series) showLab(li + d); } else if (hours.length) show(idx + d);
  } else if (e.key === " ") { e.preventDefault(); (labOn ? $("lab-play") : $("play")).click(); }
});
init().then(async () => {
  // deep links: /?at=2026-07-04T23:00#warning opens that hour on that tab; &map=travel picks the map colouring
  const q = new URLSearchParams(location.search);
  if (q.get("at")) { const i = hours.indexOf(q.get("at").replace("T", " ").slice(0, 13) + ":00:00"); if (i >= 0) await show(i); }
  const want = Object.entries(HASH).find(([, h]) => "#" + h === location.hash);
  if (want) $(want[0]).click();
}).catch(err => { $("platform").textContent = "Scoring service unavailable"; $("data-notice").classList.remove("hidden"); $("data-notice").classList.add("error-state"); $("data-notice").textContent = "Replay could not be loaded. Check that the scoring service and model artifacts are available, then reload."; $("sup-when").textContent="Replay unavailable"; $("tiles").innerHTML="<p class=empty-state>Borough risk data unavailable.</p>"; document.querySelectorAll(".transport button").forEach(b=>b.disabled=true); console.error(err); });
