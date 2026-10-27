// Private dashboard: runs and data sets of the user's strax folder, status, keep marks, deletion, plots.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const STATUS_ORDER = ["current", "outdated", "incomplete", "unknown", "pending"];
let RUNS = [], selectedRun = null, pollTimer = null;
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
  const r = await fetch(path, opt);
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

function runMatches(r) {
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

function renderRuns() {
  const tb = $("runsTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of RUNS.filter(runMatches)) {
    const tr = document.createElement("tr");
    if (r.run === selectedRun) tr.className = "selected";
    const i = r.info || {};
    const byType = {};
    for (const d of r.datasets) (byType[d.dtype] = byType[d.dtype] || []).push(d);
    const chips = Object.entries(byType).map(([t, ds]) => {
      // one chip per data type, coloured by its best version; number of versions if more than one
      const best = ds.find((d) => d.keep) || ds.find((d) => d.status === "current")
        || ds.sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status))[0];
      const extra = ds.length > 1 ? ` ×${ds.length}` : "";
      const tip = ds.map((d) => d.hash + ": " + stLabel(d) + ((d.why_labels || []).length ? "\n   " + d.why_labels.join("\n   ") : "")).join("\n");
      return `<span class="chip ${stClass(best)}" title="${esc(tip)}">${esc(t)}${extra}</span>`;
    }).join("");
    tr.innerHTML = `<td>${String(r.run).padStart(6, "0")}</td><td>${esc(i.mode || "")}<br><span class="hint">${esc(i.source || "")}</span></td>`
      + `<td>${day(i.start)}</td><td><div class="chips">${chips}</div></td><td>${gb(r.size)}</td>`
      + `<td>${r.outdated_size ? `<span class="bad">${gb(r.outdated_size)}</span>` : ""}</td>`;
    tr.onclick = () => selectRun(r.run);
    tb.appendChild(tr);
  }
}

async function loadRuns() {
  try {
    const j = await api("/api/runs?kind=" + KIND);
    RUNS = j.runs;
    renderTotals(j.totals, j.lineage);
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
  row.innerHTML = `<td colspan="9"><div class="why-box">loading…</div></td>`;
  tr.after(row);
  const box = row.querySelector(".why-box");
  try {
    const j = await api(`/api/dataset/${encodeURIComponent(d.name)}/why`);
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
}

function renderDetail(r) {
  if (!r) { $("detailTitle").textContent = "Select a run"; return; }
  const i = r.info || {};
  $("detailTitle").textContent = `Run ${String(r.run).padStart(6, "0")} — ${gb(r.size)}`;
  $("runInfo").innerHTML = [i.mode && `mode ${esc(i.mode)}`, i.source && `source ${esc(i.source)}`,
    i.start && `start ${day(i.start)}`, i.science_run && esc(i.science_run), i.comment && `“${esc(i.comment)}”`,
    i.error && `<span class="warn">run database: ${esc(i.error)}</span>`].filter(Boolean).join(" · ");
  const checked = new Set([...document.querySelectorAll(".dsSel:checked")].map((c) => c.value));
  const tb = $("dsTable").querySelector("tbody");
  tb.innerHTML = "";
  for (const d of r.datasets) {
    const tr = document.createElement("tr");
    const plottable = !d.temp && (d.dtype.startsWith("event") || d.dtype === "peak_basics");
    tr.innerHTML = `<td><input type="checkbox" class="dsSel" value="${esc(d.name)}" ${checked.has(d.name) ? "checked" : ""} ${d.keep ? "disabled title='kept'" : ""}></td>`
      + `<td>${esc(d.dtype)}</td><td><code>${esc(d.hash)}</code></td>`
      + `<td><span class="chip ${stClass(d)}">${esc(stLabel(d))}</span>${d.status === "outdated" ? ` <button class="linkbtn whyBtn">why?</button>` : ""}</td>`
      + `<td>${gb(d.size)}</td><td>${d.n_files}</td><td>${day(new Date(d.mtime * 1000).toISOString())}</td>`
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
    note = prompt(`Keep ${d.name}: why (optional, e.g. the note that uses it)?`, "");
    if (note === null) return;
  }
  await api("/api/keep", {name: d.name, keep: !d.keep, note});
  loadRuns();
}

// ------------------------------------------------------------------ deletion: preview, confirm
function confirmDialog(title, preview) {
  return new Promise((resolve) => {
    $("dlgTitle").textContent = title;
    const rows = preview.delete.map((x) => `<tr><td>${esc(x.name)}</td><td>${gb(x.size)}</td></tr>`).join("");
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
    const j = await api(`/api/dataset/${encodeURIComponent(d.name)}/plot`);
    const c = j.columns;
    $("plotInfo").textContent = `${d.name}: ${j.n} rows (read directly from the folder; log axes as log10)`;
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
$("statusFilter").onchange = renderRuns;
$("refreshBtn").onclick = async () => { await api("/api/refresh", {}); loadRuns(); };
$("delOutdatedBtn").onclick = () => deleteOutdated().catch((e) => alert(e.message));
$("delSelBtn").onclick = () => deleteNames([...document.querySelectorAll(".dsSel:checked")].map((c) => c.value)).catch((e) => alert(e.message));
$("selAll").onchange = (e) => { document.querySelectorAll(".dsSel:not(:disabled)").forEach((c) => (c.checked = e.target.checked)); updateSel(); };
loadRuns();
loadDeletions();
