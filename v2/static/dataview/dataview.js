// Data view (private dashboard and production /v3): runs and data sets, status, why?, keep marks, deletion, plots.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const STATUS_ORDER = ["current", "outdated", "incomplete", "unknown", "pending"];
let RUNS = [], selectedRun = null, pollTimer = null, DELETABLE = null;   // DELETABLE: statuses the profile may delete (null: any)
let KIND = location.hash === "#mc" ? "mc" : "data";      // the tab: data runs or simulated runs (900000-999999)

function gb(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " GB";
  if (b >= 1e6) return (b / 1e6).toFixed(1) + " MB";
  return (b / 1e3).toFixed(0) + " kB";
}
function day(t) { return t ? String(t).slice(0, 16).replace("T", " ") : ""; }
function stClass(d) { return d.keep ? "st-keep" : "st-" + d.status; }
function stLabel(d) {
  const s = d.keep ? "keep" : d.status;
  return d.status === "current" && d.current_for.length ? `${s} (${d.current_for.join(", ")})` : s;
}

async function api(path, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const r = await fetch((window.BASE || "") + path, opt);
  const j = await r.json().catch(() => ({error: r.statusText}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function renderTotals(t, lin) {
  const by = t.size_by_status || {};
  const part = (k) => by[k] ? `<span class="t chip ${"st-" + k}">${k} <b>${gb(by[k])}</b></span>` : "";
  $("totals").innerHTML = `<span class="t">folder <b>${gb(t.size)}</b> · ${t.n_runs} runs · ${t.n_datasets} data sets</span>`
    + ["current", "outdated", "incomplete", "unknown", "pending", "keep"].map(part).join("");
  $("lineageState").textContent = lin.running ? "Computing the current hashes in the background (status 'pending' until done)…"
    : (lin.error ? "Status computation failed: " + lin.error : (lin.done_at ? "Status computed " + lin.done_at : ""));
  if (lin.running && !pollTimer) pollTimer = setInterval(loadRuns, 10000);
  if (!lin.running && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function fillFilter(id, values) {
  const sel = $(id), cur = sel.value, first = sel.options[0].outerHTML;
  sel.innerHTML = first + [...values].filter(Boolean).sort().map((v) => `<option${v === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
}

function runMatches(r) {
  const i0 = r.info || {};
  if ($("srFilter").value && i0.science_run !== $("srFilter").value) return false;
  if ($("classFilter").value && i0.run_class !== $("classFilter").value) return false;
  if ($("sourceFilter").value && i0.source !== $("sourceFilter").value) return false;
  const q = $("search").value.trim().toLowerCase();
  const f = $("statusFilter").value;
  if (f) {
    const ok = r.datasets.some((d) => f === "keep" ? d.keep : (d.status === f && !d.keep));
    if (!ok) return false;
  }
  if (!q) return true;
  const i = r.info || {};
  const hay = [String(r.run).padStart(6, "0"), i.mode, i.source, i.run_class, i.science_run, (i.tags || []).join(" "),
               r.datasets.map((d) => d.dtype).join(" ")].join(" ").toLowerCase();
  return hay.includes(q);
}

// The chain in its order: one column per data type in the run list (types not in it follow alphabetically).
const CHAIN = ["raw_records", "raw_records_ext", "raw_records_sipm", "pulse_counts", "records_led", "led_calibration",
  "peaks", "peaks_sipm", "peak_basics", "peak_positions", "events", "event_basics", "event_positions", "corrected_areas", "event_info"];
const SHORT = {raw_records: "raw", raw_records_ext: "raw ext", raw_records_sipm: "raw sipm", pulse_counts: "pulses",
  records_led: "led rec", led_calibration: "led cal", peaks: "peaks", peaks_sipm: "peaks sipm", peak_basics: "pk basics",
  peak_positions: "pk pos", events: "events", event_basics: "ev basics", event_positions: "ev pos",
  corrected_areas: "corr", event_info: "ev info"};
let CAN_SUBMIT = false, SUBMIT_OPTS = null;

function bestOf(ds) {
  return ds.find((d) => d.status === "current") || ds.find((d) => d.keep)
    || [...ds].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status))[0];
}

function typeColumns(runs) {
  const seen = new Set(runs.flatMap((r) => r.datasets.map((d) => d.dtype)));
  return [...CHAIN.filter((t) => seen.has(t)), ...[...seen].filter((t) => !CHAIN.includes(t)).sort()];
}

function jobText(r) {
  const p = (r.info || {}).processing || "";
  return r.job ? `<span class="warn">${esc(r.job)}</span>` : (p ? `<span class="hint">${esc(p)}</span>` : "");
}

function renderRuns() {
  const runs = RUNS.filter(runMatches);
  const cols = typeColumns(runs);
  $("runsHead").innerHTML = "<tr>" + (CAN_SUBMIT ? `<th><input type="checkbox" id="runSelAll" title="select all shown"></th>` : "")
    + "<th>run</th><th>mode / source</th><th>start</th><th>job</th>"
    + cols.map((t) => `<th class="tcol" title="${esc(t)}">${esc(SHORT[t] || t)}</th>`).join("")
    + "<th>size</th><th>older</th></tr>";
  const checked = new Set([...document.querySelectorAll(".runSel:checked")].map((c) => Number(c.value)));
  const tb = $("runsTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of runs) {
    const tr = document.createElement("tr");
    if (r.run === selectedRun) tr.className = "selected";
    const i = r.info || {};
    const byType = {};
    for (const d of r.datasets) (byType[d.dtype] = byType[d.dtype] || []).push(d);
    let nOld = 0, sizeOld = 0;
    const cells = cols.map((t) => {
      const ds = byType[t];
      if (!ds) return `<td class="blkcell"></td>`;
      const best = bestOf(ds);
      for (const d of ds) if (d !== best) { nOld += 1; sizeOld += d.size; }
      const tip = t + "\n" + ds.map((d) => (d === best ? "▸ " : "  ") + d.hash + ": " + stLabel(d)
        + ((d.why_labels || []).length ? "\n     " + d.why_labels.join("\n     ") : "")).join("\n");
      return `<td class="blkcell"><span class="blk ${stClass(best)}" title="${esc(tip)}"></span></td>`;
    }).join("");
    tr.innerHTML = (CAN_SUBMIT ? `<td><input type="checkbox" class="runSel" value="${r.run}" ${checked.has(r.run) ? "checked" : ""}></td>` : "")
      + `<td>${String(r.run).padStart(6, "0")}</td><td class="ms" title="${esc((i.mode || "") + " · " + (i.source || ""))}">${esc(i.mode || "")}<br><span class="hint">${esc(i.source || "")}</span></td>`
      + `<td class="nowrap" title="${esc(day(i.start))}">${esc(day(i.start).slice(5))}</td><td>${jobText(r)}</td>${cells}<td class="nowrap">${gb(r.size)}</td>`
      + `<td class="nowrap">${nOld ? `<span class="${r.outdated_size ? "bad" : "hint"}" title="${nOld} older versions, ${gb(sizeOld)}">+${nOld}</span>` : ""}</td>`;
    tr.onclick = (e) => { if (!e.target.classList.contains("runSel")) selectRun(r.run); };
    tb.appendChild(tr);
  }
  const all = $("runSelAll");
  if (all) all.onchange = (e) => { document.querySelectorAll(".runSel").forEach((c) => (c.checked = e.target.checked)); updateRunSel(); };
  document.querySelectorAll(".runSel").forEach((c) => (c.onchange = updateRunSel));
  updateRunSel();
}

function updateRunSel() {
  const n = document.querySelectorAll(".runSel:checked").length;
  $("processBtn").disabled = !CAN_SUBMIT || !n;
  $("processBtn").textContent = CAN_SUBMIT ? (n ? `Process ${n} run${n > 1 ? "s" : ""}…` : "Process selected runs…") : "Process (later)";
}

// ------------------------------------------------------------------ processing (production: the host app's submission)
async function openSubmit(runIds) {
  if (!runIds.length) return;
  SUBMIT_OPTS = SUBMIT_OPTS || await api("/api/submit-options");
  const o = SUBMIT_OPTS;
  $("subRuns").textContent = runIds.map((r) => String(r).padStart(6, "0")).join(", ");
  $("subTargets").innerHTML = (o.targets || []).map((t) => `<label><input type="checkbox" class="subT" value="${esc(t)}" checked> ${esc(t)}</label>`).join(" ");
  $("subVersion").innerHTML = (o.corrections_versions || []).map((v) => `<option${v === o.default_version ? " selected" : ""}>${esc(v)}</option>`).join("");
  $("subInfo").textContent = `submit mode: ${o.submit_mode || "?"} · at most ${o.max_jobs || "?"} jobs, the rest waits on the waiting list`;
  $("subResult").innerHTML = "";
  $("subOk").disabled = false;
  const dlg = $("submitDlg");
  $("subCancel").onclick = () => dlg.close();
  $("subOk").onclick = async () => {
    $("subOk").disabled = true;
    const targets = [...document.querySelectorAll(".subT:checked")].map((c) => c.value);
    try {
      const res = await api("/api/submit", {run_ids: runIds, targets, corrections_version: $("subVersion").value});
      $("subResult").innerHTML = `<p>submitted ${res.submitted || 0} · waiting list ${res.queued || 0} · skipped ${res.skipped || 0} · failed ${res.failed || 0}</p>`
        + `<ul>${(res.results || []).map((x) => `<li>${String(x.run_id).padStart(6, "0")}: ${esc(x.status || "")}${x.reason ? " — " + esc(x.reason) : ""}</li>`).join("")}</ul>`;
      loadRuns();
    } catch (e) { $("subResult").textContent = "Error: " + e.message; $("subOk").disabled = false; }
  };
  dlg.showModal();
}

// ------------------------------------------------------------------ the run document
function kv(obj) {
  return `<table class="kv">${Object.entries(obj || {}).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" && v !== null ? JSON.stringify(v) : v)}</td></tr>`).join("")}</table>`;
}

function num(v) {
  return typeof v === "number" && !Number.isInteger(v) ? Number(v.toPrecision(5)) : v;
}

function scTable(snap) {
  // one row per quantity: value at the start and at the end of the run
  if (!snap) return "<p class='hint'>no slow-control snapshot</p>";
  const st = (snap.start || {}).values || {}, en = (snap.end || {}).values || {};
  const names = [...new Set([...Object.keys(st), ...Object.keys(en)])];
  const cell = (x) => !x ? "<td class='hint'>—</td>"
    : `<td>${esc(num(x.value))} ${esc(x.unit || "")}${x.quality !== "ok" ? ` <span class="warn">${esc(x.quality)}</span>` : ""}</td>`;
  return `<table class="kv"><tr><th></th><th>start <span class="hint">${esc((snap.start || {}).time || "")}</span></th>`
    + `<th>end <span class="hint">${esc((snap.end || {}).time || "")}</span></th></tr>`
    + names.map((n) => `<tr><th>${esc(n)}</th>${cell(st[n])}${cell(en[n])}</tr>`).join("") + "</table>";
}

async function loadRunDoc(run) {
  const box = $("runDoc");
  if (!$("runDocBox").open || run === null) return;
  box.innerHTML = "loading…";
  try {
    const d = await api(`/api/run/${run}/doc`);
    if (selectedRun !== run) return;
    const comments = (d.comments || []).map((c) => `<li>${esc(c.date || "")} ${esc(c.user || "")}: ${esc(c.comment || "")}</li>`).join("");
    const hist = (d.processing_history || []).slice().reverse().map((h) => `<tr><td>${esc(h.time)}</td><td>${esc(h.user)}</td><td>${esc(h.action)}</td>`
      + `<td>${esc(h.status)}</td><td>${esc((h.targets || []).join(", "))}</td><td>${esc(h.corrections_version || "")}</td><td>${esc(h.reason || h.job_name || "")}</td></tr>`).join("");
    const data = (d.data || []).map((e) => `<tr><td>${esc(e.type)}</td><td>${esc(e.host)}</td><td>${esc(e.location)}</td>`
      + `<td>${esc(e.corrections_version || "")}</td><td><code>${esc(e.lineage_hash || "")}</code></td><td>${e.on_disk_here ? "✓" : ""}</td></tr>`).join("");
    const head = {number: d.number, mode: d.mode, start: d.start, end: d.end, user: d.user,
      tags: (d.tags || []).map((t) => (t && t.name) || t).join(", "), ...(d.xams_bookkeeping || {})};
    box.innerHTML = `<div class="doc-grid"><div><h4>Run</h4>${kv(head)}<h4>Comments</h4><ul>${comments || "<li class='hint'>none</li>"}</ul>`
      + `<h4>Processing status</h4>${kv(d.processing_status)}</div><div><h4>Slow control (sc_snapshot)</h4>${scTable(d.sc_snapshot)}</div></div>`
      + `<h4>Processing history</h4><table class="kv"><tr><th>time</th><th>user</th><th>action</th><th>status</th><th>targets</th><th>corrections</th><th>job / reason</th></tr>${hist}</table>`
      + `<h4>data[] <span class="hint">(✓ = in a folder of this page)</span></h4><table class="kv"><tr><th>type</th><th>host</th><th>location</th><th>corrections</th><th>hash</th><th></th></tr>${data}</table>`
      + `<details><summary>full JSON</summary><pre class="json">${esc(JSON.stringify(d, null, 1))}</pre></details>`;
  } catch (e) { box.textContent = e.message; }
}

async function loadRuns() {
  try {
    const j = await api("/api/runs?kind=" + KIND);
    RUNS = j.runs;
    DELETABLE = j.delete_statuses;
    CAN_SUBMIT = !!j.can_submit;
    for (const [id, k] of [["srFilter", "science_run"], ["classFilter", "run_class"], ["sourceFilter", "source"]])
      fillFilter(id, new Set(RUNS.map((r) => (r.info || {})[k])));
    renderTotals(j.totals, j.lineage);
    if (j.scanning) { $("lineageState").textContent = "Scanning the folders (the first time takes a few minutes)…"; if (!pollTimer) pollTimer = setInterval(loadRuns, 10000); }
    renderRuns();
    const sel = RUNS.find((r) => r.run === selectedRun);
    if (!sel) { selectedRun = null; $("dsTable").querySelector("tbody").innerHTML = ""; $("runInfo").textContent = ""; $("plots").innerHTML = ""; }
    renderDetail(sel);
  } catch (e) { $("totals").textContent = "Error: " + e.message; }
}

// one data set: the changes, old -> new, per provider that makes it
function shortVal(v) {
  if (v === null || v === undefined) return "—";
  let s = typeof v === "string" ? v : JSON.stringify(v);
  const m = s.match(/filename=([^&]+)/);
  if (m) s = m[1];
  return s.length > 70 ? s.slice(0, 69) + "…" : s;
}

async function showWhy(d, tr) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("why-row")) { next.remove(); return; }
  const row = document.createElement("tr");
  row.className = "why-row";
  row.innerHTML = `<td colspan="10"><div class="why-box">loading…</div></td>`;
  tr.after(row);
  const box = row.querySelector(".why-box");
  try {
    const j = await api(`/api/dataset/${encodeURIComponent(d.id)}/why`);
    if (!j.why) { box.textContent = j.pending ? "not computed yet (shown when the status computation is done)" : "not outdated"; return; }
    box.innerHTML = j.why.providers.map((p) => {
      const how = [p.own ? "its own plugin changed" : "", p.through.length ? "through " + p.through.join(", ") : ""].filter(Boolean).join("; ");
      const chg = p.changes.map((c) => {
        const head = c.kind === "new" ? `new in the chain (${esc(c.plugin)} ${esc(c.version[1])})`
          : c.kind === "gone" ? `no longer in the chain (${esc(c.plugin)})`
          : esc(c.plugin) + (c.version ? `: version <span class="old">${esc(c.version[0])}</span> → <span class="new">${esc(c.version[1])}</span>` : "");
        const opts = Object.entries(c.options || {}).map(([k, [a, b]]) =>
          `<div class="opt" title="${esc(JSON.stringify(a))} → ${esc(JSON.stringify(b))}">${esc(k)}: <span class="old">${esc(shortVal(a))}</span> → <span class="new">${esc(shortVal(b))}</span></div>`).join("");
        return `<div class="chg"><b>${esc(c.dtype)}</b> — ${head}${opts}</div>`;
      }).join("") || "<div class='hint'>no difference in the lineage (only the hash differs)</div>";
      return `<div><b>${esc(d.dtype)}</b> outdated for <b>${esc(p.provider)}</b>: ${esc(how)}</div>${chg}`;
    }).join("<hr>");
  } catch (e) { box.textContent = "Error: " + e.message; }
}

function selectRun(run) {
  selectedRun = run;
  renderRuns();
  renderDetail(RUNS.find((r) => r.run === run));
  $("plots").innerHTML = ""; $("plotInfo").textContent = "";
  $("runDoc").innerHTML = "";
  loadRunDoc(run);
}

function renderDetail(r) {
  if (!r) { $("detailTitle").textContent = "Select a run"; return; }
  const i = r.info || {};
  $("detailTitle").textContent = `Run ${String(r.run).padStart(6, "0")} — ${gb(r.size)}`;
  $("reprocBtn").style.display = CAN_SUBMIT ? "" : "none";
  $("reprocBtn").onclick = () => openSubmit([r.run]);
  $("runInfo").innerHTML = [i.mode && `mode ${esc(i.mode)}`, i.source && `source ${esc(i.source)}`,
    i.start && `start ${day(i.start)}`, i.science_run && esc(i.science_run), i.comment && `“${esc(i.comment)}”`,
    i.error && `<span class="warn">run database: ${esc(i.error)}</span>`].filter(Boolean).join(" · ");
  const checked = new Set([...document.querySelectorAll(".dsSel:checked")].map((c) => c.value));
  const tb = $("dsTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const d of r.datasets) {
    const tr = document.createElement("tr");
    const plottable = !d.temp && (d.dtype.startsWith("event") || d.dtype === "peak_basics");
    const noDel = d.keep ? "kept" : (d.dtype === "live" ? "live data are never deleted"
      : (DELETABLE && !DELETABLE.includes(d.status) ? `only ${DELETABLE.join(" / ")} data sets can be deleted here` : ""));
    tr.innerHTML = `<td><input type="checkbox" class="dsSel" value="${esc(d.id)}" ${checked.has(d.id) ? "checked" : ""} ${noDel ? `disabled title="${esc(noDel)}"` : ""}></td>`
      + `<td>${esc(d.dtype)}</td><td><code>${esc(d.hash)}</code></td>`
      + `<td><span class="chip ${stClass(d)}">${esc(stLabel(d))}</span>${d.status === "outdated" ? ` <button class="linkbtn whyBtn">why?</button>` : ""}</td>`
      + `<td>${gb(d.size)}</td><td>${d.n_files}</td><td>${day(new Date(d.mtime * 1000).toISOString())}</td>`
      + `<td class="hint">${esc(d.location || "")}${d.raw ? " (raw)" : ""}</td>`
      + `<td><button class="small keepBtn" title="${esc(d.keep_note || "")}">${d.keep ? "unkeep" : "keep"}</button></td>`
      + `<td>${plottable ? `<button class="small plotBtn">plot</button>` : ""}</td>`;
    tr.querySelector(".keepBtn").onclick = () => toggleKeep(d);
    const wb = tr.querySelector(".whyBtn");
    if (wb) wb.onclick = () => showWhy(d, tr);
    const pb = tr.querySelector(".plotBtn");
    if (pb) pb.onclick = () => plotDataset(d);
    tb.appendChild(tr);
  }
  document.querySelectorAll(".dsSel").forEach((c) => (c.onchange = updateSel));
  updateSel();
}

function updateSel() {
  const sel = [...document.querySelectorAll(".dsSel:checked")];
  $("delSelBtn").disabled = !sel.length;
  $("selInfo").textContent = sel.length ? `${sel.length} selected` : "";
}

async function toggleKeep(d) {
  let note = "";
  if (!d.keep) {
    note = prompt(`Keep ${d.id}: why (optional, e.g. the note that uses it)?`, "");
    if (note === null) return;
  }
  await api("/api/keep", {name: d.id, keep: !d.keep, note});
  loadRuns();
}

// ------------------------------------------------------------------ deletion: preview, confirm
function confirmDialog(title, preview) {
  return new Promise((resolve) => {
    $("dlgTitle").textContent = title;
    const rows = preview.delete.map((x) => `<tr><td>${esc(x.name)}${x.note ? `<br><span class="warn">${esc(x.note)}</span>` : ""}</td><td>${gb(x.size)}</td></tr>`).join("");
    const ref = preview.refused.map((x) => `<li>${esc(x.name)}: ${esc(x.reason)}</li>`).join("");
    $("dlgBody").innerHTML = (preview.delete.length
      ? `<p>Delete <b>${preview.delete.length}</b> data sets, <b>${gb(preview.size)}</b>. This cannot be undone.</p><table>${rows}</table>`
      : "<p>Nothing to delete.</p>") + (ref ? `<p>Not deleted:</p><ul>${ref}</ul>` : "");
    $("dlgOk").disabled = !preview.delete.length;
    const dlg = $("confirmDlg");
    $("dlgOk").onclick = () => { dlg.close(); resolve(true); };
    $("dlgCancel").onclick = () => { dlg.close(); resolve(false); };
    dlg.showModal();
  });
}

async function deleteNames(names) {
  const pv = await api("/api/delete", {names, confirm: false});
  if (!(await confirmDialog("Delete selected data sets", pv))) return;
  const res = await api("/api/delete", {names: pv.delete.map((x) => x.name), confirm: true});
  if (res.errors.length) alert("Errors:\n" + res.errors.map((e) => e.name + ": " + e.error).join("\n"));
  loadRuns(); loadDeletions();
}

async function deleteOutdated() {
  const body = {older_than_days: Number($("olderDays").value || 0), incomplete: $("inclIncomplete").checked, kind: KIND};
  const pv = await api("/api/delete-outdated", {...body, confirm: false});
  if (!(await confirmDialog("Delete all outdated data sets (not kept)", pv))) return;
  const res = await api("/api/delete", {names: pv.delete.map((x) => x.name), confirm: true});
  if (res.errors.length) alert("Errors:\n" + res.errors.map((e) => e.name + ": " + e.error).join("\n"));
  loadRuns(); loadDeletions();
}

async function loadDeletions() {
  const j = await api("/api/deletions");
  $("delTable").querySelector("tbody").innerHTML = j.rows.map((r) =>
    `<tr><td>${esc(r.time)}</td><td>${esc(r.user)}</td><td>${esc(r.name)}</td><td>${gb(r.size || 0)}</td></tr>`).join("")
    || `<tr><td colspan="4" class="hint">none yet</td></tr>`;
}

// ------------------------------------------------------------------ plots of one data set (read from its folder)
const LAYOUT = {paper_bgcolor: "#111b2e", plot_bgcolor: "#0f1729", font: {color: "#dce7ff", size: 11},
  margin: {l: 55, r: 15, t: 30, b: 45}, height: 300};
const AX = (title, log) => ({title, type: log ? "log" : "linear", gridcolor: "#2a3a58", zerolinecolor: "#2a3a58"});

function pairs(a, b, logA, logB) {
  const x = [], y = [];
  for (let i = 0; i < a.length; i++) {
    const u = a[i], v = b[i];
    if (u === null || v === null) continue;
    if ((logA && u <= 0) || (logB && v <= 0)) continue;
    x.push(u); y.push(v);
  }
  return [x, y];
}

function addPlot(title, traces, xa, ya) {
  const div = document.createElement("div");
  div.className = "plot-block";
  $("plots").appendChild(div);
  Plotly.newPlot(div, traces, {...LAYOUT, title: {text: title, font: {size: 12}}, xaxis: xa, yaxis: ya}, {displaylogo: false, responsive: true});
}

function hist2d(x, y, logx, logy) {
  const tx = logx ? x.map(Math.log10) : x, ty = logy ? y.map(Math.log10) : y;
  return [{type: "histogram2d", x: tx, y: ty, nbinsx: 90, nbinsy: 70, colorscale: "Viridis",
           z: undefined, histfunc: "count", colorbar: {thickness: 10}}];
}

async function plotDataset(d) {
  $("plots").innerHTML = ""; $("plotInfo").textContent = "Loading " + d.name + " …";
  try {
    const j = await api(`/api/dataset/${encodeURIComponent(d.id)}/plot`);
    const c = j.columns;
    $("plotInfo").textContent = `${d.id}: ${j.n} rows (read directly from the folder; log axes as log10)`;
    if (j.kind === "peak") {
      let [a, f] = pairs(c.area || [], c.area_fraction_top || [], true, false);
      addPlot("peak area vs area fraction top", hist2d(a, f, true, false), AX("log10 area [PE]"), AX("area fraction top"));
      [a, f] = pairs(c.area || [], c.range_50p_area || [], true, true);
      addPlot("peak area vs 50% width", hist2d(a, f, true, true), AX("log10 area [PE]"), AX("log10 width [ns]"));
      return;
    }
    const s1 = c.cs1 && c.cs1.some((v) => v) ? c.cs1 : c.s1_area, s2 = c.cs2 && c.cs2.some((v) => v) ? c.cs2 : c.s2_area;
    if (s1 && s2) {
      const [x, y] = pairs(s1, s2, true, true);
      addPlot("S2 vs S1", hist2d(x, y, true, true), AX("log10 S1 [PE]"), AX("log10 S2 [PE]"));
      addPlot("S1 spectrum", [{type: "histogram", x: x.map(Math.log10), nbinsx: 120, marker: {color: "#4db6ff"}}], AX("log10 S1 [PE]"), AX("events"));
    }
    if (c.drift_time) {
      const dt = c.drift_time.filter((v) => v !== null && v > 0).map((v) => v / 1000);
      addPlot("drift time", [{type: "histogram", x: dt, nbinsx: 120, marker: {color: "#f1c40f"}}], AX("drift time [µs]"), AX("events"));
    }
    if (c.x && c.y) {
      const [x, y] = pairs(c.x, c.y, false, false);
      addPlot("x-y", hist2d(x, y, false, false), AX("x [cm]"), {...AX("y [cm]"), scaleanchor: "x"});
    }
    if (!$("plots").children.length) $("plotInfo").textContent = d.name + ": no plottable columns";
  } catch (e) { $("plotInfo").textContent = "Error: " + e.message; }
}

// ------------------------------------------------------------------ wiring
function setKind(k) {
  KIND = k;
  document.querySelectorAll(".nav-link[data-kind]").forEach((a) => a.classList.toggle("active", a.dataset.kind === k));
  loadRuns();
}
document.querySelectorAll(".nav-link[data-kind]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); history.replaceState(null, "", "#" + a.dataset.kind); setKind(a.dataset.kind); }));
document.querySelectorAll(".nav-link[data-kind]").forEach((a) => a.classList.toggle("active", a.dataset.kind === KIND));
$("search").oninput = renderRuns;
for (const id of ["srFilter", "classFilter", "sourceFilter"]) $(id).onchange = renderRuns;
$("statusFilter").onchange = renderRuns;
$("refreshBtn").onclick = async () => { await api("/api/refresh", {}); loadRuns(); };
$("delOutdatedBtn").onclick = () => deleteOutdated().catch((e) => alert(e.message));
$("delSelBtn").onclick = () => deleteNames([...document.querySelectorAll(".dsSel:checked")].map((c) => c.value)).catch((e) => alert(e.message));
$("processBtn").onclick = () => openSubmit([...document.querySelectorAll(".runSel:checked")].map((c) => Number(c.value)));
$("runDocBox").ontoggle = () => loadRunDoc(selectedRun);
$("selAll").onchange = (e) => { document.querySelectorAll(".dsSel:not(:disabled)").forEach((c) => (c.checked = e.target.checked)); updateSel(); };
loadRuns();
loadDeletions();
