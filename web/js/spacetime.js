// Space-time dashboard (right pane, "Space-Time" tab): guided analysis + emerging hot spot results.
// Chain: [Project to EPSG:2278] -> [Feature To Point] -> Create Space Time Cube -> Emerging Hot Spot Analysis.
// Every step is an ordinary registered tool run with its own provenance manifest.
import { api } from "./api.js";
import {
  drawable, layerById, loadMeta, on, openTable, refreshLayers, refreshTools, set, setView, state, zoomToLayer,
} from "./state.js";
import { $, fmtNum, h, svgIcon, toast } from "./ui.js";

// ArcGIS-style emerging hot spot palette (reds = hot, blues = cold).
export const PATTERN_CLASSES = [
  { value: 1, label: "New Hot Spot", color: "#f4a582" },
  { value: 2, label: "Consecutive Hot Spot", color: "#e7795b" },
  { value: 3, label: "Intensifying Hot Spot", color: "#b2182b" },
  { value: 4, label: "Persistent Hot Spot", color: "#d6604d" },
  { value: 5, label: "Diminishing Hot Spot", color: "#f7c3a9" },
  { value: 6, label: "Sporadic Hot Spot", color: "#fbe1d3" },
  { value: 7, label: "Oscillating Hot Spot", color: "#c994c7" },
  { value: 8, label: "Historical Hot Spot", color: "#8c5a4b" },
  { value: -1, label: "New Cold Spot", color: "#92c5de" },
  { value: -2, label: "Consecutive Cold Spot", color: "#6baed6" },
  { value: -3, label: "Intensifying Cold Spot", color: "#2166ac" },
  { value: -4, label: "Persistent Cold Spot", color: "#4393c3" },
  { value: -5, label: "Diminishing Cold Spot", color: "#b7d7ea" },
  { value: -6, label: "Sporadic Cold Spot", color: "#deebf7" },
  { value: -7, label: "Oscillating Cold Spot", color: "#9e9ac8" },
  { value: -8, label: "Historical Cold Spot", color: "#4b6a80" },
  { value: 0, label: "No Pattern Detected", color: "#d5dce4" },
];
const BIN_CLASSES = [
  { value: 3, label: "Hot spot · 99 % confidence", color: "#b2182b" },
  { value: 2, label: "Hot spot · 95 %", color: "#ef8a62" },
  { value: 1, label: "Hot spot · 90 %", color: "#fddbc7" },
  { value: 0, label: "Not significant", color: "#e4e9ef" },
  { value: -1, label: "Cold spot · 90 %", color: "#d1e5f0" },
  { value: -2, label: "Cold spot · 95 %", color: "#67a9cf" },
  { value: -3, label: "Cold spot · 99 %", color: "#2166ac" },
];
const UNITS = ["days", "weeks", "months", "years"];
const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

let wiz = null; // wizard form values
let running = null; // {steps:[{label, status, detail}]}
let showWizard = false;
let playTimer = null;
let locSeries = null; // {location, rows}

export function initSpaceTime() {
  on(["gpTab"], () => { if (state.gpTab !== "spacetime") stopPlay(); });
  on("selection", onSelection);
  on("layers", () => { if (state.gpTab === "spacetime" && !running) render(); });
}

// ======================================================================== render
export function renderSpaceTime() {
  render();
}

function render() {
  const root = $("#gp");
  if (state.gpTab !== "spacetime") return;
  const st = state.spacetime;
  root.replaceChildren(h("div.st",
    h("div.st-head",
      h("div.st-title", svgIcon("hotspot"), h("div", h("b", "Space-time analysis"), h("div.small.muted", "Emerging hot spots · Space Time Pattern Mining"))),
      st && !showWizard ? h("button.btn.sm.push", { onclick: () => { showWizard = true; render(); } }, svgIcon("plus"), "New analysis") : null),
    running ? progressCard() : null,
    !st || showWizard ? wizardCard() : null,
    st && !showWizard ? resultsView(st) : null,
    existingResultsPicker()));
}

// ------------------------------------------------------------------ wizard
function candidateLayers() {
  return state.layers.filter((l) => drawable(l) && ["Point", "Line", "Polygon"].includes(l.geometry_family)
    && !/Space Time Cube|Cube Trends|Emerging Hot Spots|Hot Spot Bins/.test(l.label));
}

// Prefer well-filled inspection / event dates; a mostly empty date field is a poor default.
function rankTimeField(f, total) {
  const n = f.name.toUpperCase();
  let s = f.type === "date" ? 3 : 0;
  if (/INSPECT|INSP_DT|INSPECTION|EVENT|OCCUR/.test(n)) s += 12;
  if (/_DT$|DATE|^DT_/.test(n)) s += 4;
  if (/CREATE|LASTUPD|EDIT|ISSUE/.test(n)) s -= 4;
  if (total) s -= 20 * ((f.null_count || 0) / total);
  return s;
}

function wizardCard() {
  const layers = candidateLayers();
  if (!wiz || (state.spacetimeInput && wiz.input !== state.spacetimeInput)) {
    const pick = state.spacetimeInput || layers.find((l) => /pacp/i.test(l.layer_id))?.layer_id || layers.find((l) => l.geometry_family === "Point")?.layer_id || layers[0]?.layer_id || "";
    wiz = { input: pick, timeField: "", interval: 3, unit: "months", size: "", shape: "fishnet", weight: "", nbDist: "", nbStep: 1 };
    state.spacetimeInput = null;
  }
  const meta = state.meta[wiz.input];
  if (wiz.input && !meta) loadMeta(wiz.input).then(render).catch(() => {});
  const fields = (meta?.profile?.fields || []).filter((f) => !f.internal);
  const total = meta?.profile?.feature_count || 0;
  const timeFields = fields.filter((f) => f.type === "date" || f.type === "string").sort((a, b) => rankTimeField(b, total) - rankTimeField(a, total));
  const numFields = fields.filter((f) => f.type === "integer" || f.type === "double");
  if (meta && !timeFields.some((f) => f.name === wiz.timeField)) wiz.timeField = timeFields[0]?.name || "";
  if (wiz.weight && !numFields.some((f) => f.name === wiz.weight)) wiz.weight = "";
  const lyr = layerById(wiz.input);
  const steps = planSteps(lyr);

  const sel = (value, opts, onchange, attrs = {}) => h("select", { onchange: (e) => { onchange(e.target.value); render(); }, ...attrs },
    opts.map(([v, label]) => h("option", { value: v, selected: String(v) === String(value) }, label)));
  const num = (value, onchange, attrs = {}) => h("input", { type: "number", value: String(value ?? ""), oninput: (e) => onchange(e.target.value), ...attrs });

  if (!layers.length) {
    return h("div.st-card", h("h4", "Run an analysis"),
      h("p.small.muted", "Add a layer with dated events first — e.g. PACP Pipe Inspections (25 basins) from Add data › City layer library."),
      h("button.btn.primary", { onclick: () => document.querySelector('[data-action="add-data"]').click() }, svgIcon("library"), "Open City layer library"));
  }
  return h("div.st-card",
    h("h4", "Run an analysis"),
    h("div.form-row", h("label", "Events layer"),
      sel(wiz.input, layers.map((l) => [l.layer_id, `${l.label} · ${l.feature_count.toLocaleString()} ${l.geometry_family.toLowerCase()}s`]), (v) => { wiz.input = v; wiz.timeField = ""; })),
    h("div.form-row", h("label", "Date of each event"),
      meta ? (timeFields.length ? sel(wiz.timeField, timeFields.map((f) => [f.name, `${f.name} (${f.type})`]), (v) => { wiz.timeField = v; })
        : h("div.callout.bad", svgIcon("warn"), h("div", "This layer has no date or text field.")))
        : h("div.small.muted", "Loading fields…")),
    h("div.form-grid",
      h("div.form-row", h("label", "Time step"), num(wiz.interval, (v) => { wiz.interval = v; }, { min: "1", step: "1" })),
      h("div.form-row", h("label", "Unit"), sel(wiz.unit, UNITS.map((u) => [u, u]), (v) => { wiz.unit = v; }))),
    h("div.form-grid",
      h("div.form-row", h("label", "Bin size (feet)"), num(wiz.size, (v) => { wiz.size = v; }, { min: "1", placeholder: "Auto (extent / 100)" })),
      h("div.form-row", h("label", "Grid"), sel(wiz.shape, [["fishnet", "Square (fishnet)"], ["hexagon", "Hexagon"]], (v) => { wiz.shape = v; }))),
    h("div.form-row", h("label", "Measure"),
      sel(wiz.weight, [["", "Number of events (COUNT)"], ...numFields.map((f) => [f.name, `Sum of ${f.name}`])], (v) => { wiz.weight = v; })),
    h("details.st-adv", h("summary", "Hot spot neighborhood"),
      h("div.form-grid",
        h("div.form-row", h("label", "Distance (feet)"), num(wiz.nbDist, (v) => { wiz.nbDist = v; }, { min: "1", placeholder: "Default" })),
        h("div.form-row", h("label", "Time steps back"), num(wiz.nbStep, (v) => { wiz.nbStep = v; }, { min: "0", step: "1" })))),
    h("ol.st-plan", steps.map((s) => h("li", svgIcon(s.icon), h("span", s.label)))),
    h("div.row",
      state.spacetime ? h("button.btn", { onclick: () => { showWizard = false; render(); } }, "Cancel") : null,
      h("button.btn.primary.push", { disabled: !!running || !meta || !wiz.timeField, onclick: runChain }, svgIcon("play"), "Run analysis")),
    h("div.small.muted", "Unknown dates (blank, 0000/00/00) are excluded and counted, never guessed. Each step is saved as a new layer with a provenance manifest."));
}

function planSteps(l) {
  const out = [];
  if (!l) return out;
  if (!l.crs?.is_projected) out.push({ icon: "project", label: "Project to EPSG:2278 (Texas South Central, US ft)" });
  if (l.geometry_family !== "Point") out.push({ icon: "topoint", label: l.geometry_family === "Line" ? "Feature To Point — midpoint of each pipe" : "Feature To Point — inside each polygon" });
  out.push({ icon: "cube", label: `Create Space Time Cube — ${wiz.interval} ${wiz.unit} steps` });
  out.push({ icon: "hotspot", label: "Emerging Hot Spot Analysis" });
  return out;
}

// ------------------------------------------------------------------ chain execution
async function runTool(tool, params, step) {
  const r = await api.runTool(tool, params);
  for (;;) {
    const j = await api.run(r.run_id);
    step.progress = j.progress;
    if (TERMINAL.has(j.status)) {
      if (j.status !== "succeeded") throw new Error(j.error || j.status);
      return j.result;
    }
    drawProgress();
    await new Promise((res) => setTimeout(res, 600));
  }
}

async function runChain() {
  const l = layerById(wiz.input);
  const plan = planSteps(l);
  running = { steps: plan.map((p) => ({ ...p, status: "waiting" })) };
  showWizard = false;
  render();
  const hide = [];
  let cur = l.layer_id;
  let i = 0;
  const next = async (tool, params) => {
    const s = running.steps[i++];
    s.status = "running";
    drawProgress();
    try {
      const m = await runTool(tool, params, s);
      s.status = "done";
      s.detail = (m.outputs || []).map((o) => `${o.label} (${o.feature_count.toLocaleString()})`).join(" · ");
      drawProgress();
      return m;
    } catch (e) {
      s.status = "failed";
      s.detail = e.message;
      throw e;
    }
  };
  set({ jobsRunning: state.jobsRunning + 1 });
  try {
    if (!l.crs?.is_projected) {
      cur = (await next("management.project", { input_layer: cur, output_crs: "EPSG:2278" })).result.layer_id;
      hide.push(cur);
    }
    if (l.geometry_family !== "Point") {
      cur = (await next("management.feature_to_point", { input_layer: cur, point_location: "inside" })).result.layer_id;
      hide.push(cur);
    }
    const cubeParams = { input_layer: cur, time_field: wiz.timeField, time_step_interval: Number(wiz.interval) || 1, time_step_unit: wiz.unit, aggregation_shape: wiz.shape, distance_units: "feet" };
    if (wiz.size) cubeParams.distance_interval = Number(wiz.size);
    if (wiz.weight) Object.assign(cubeParams, { summary_field: wiz.weight, summary_statistic: "sum" });
    const cube = await next("stpm.create_space_time_cube", cubeParams);
    hide.push(cube.result.layer_id, cube.result.trend_layer_id);
    const ehParams = { input_cube: cube.result.layer_id, analysis_field: cube.result.summary_field || "COUNT", distance_units: "feet", neighborhood_time_step: Number(wiz.nbStep) || 0 };
    if (wiz.nbDist) ehParams.neighborhood_distance = Number(wiz.nbDist);
    const eh = await next("stpm.emerging_hot_spot_analysis", ehParams);
    // Intermediate layers stay in Contents but hidden; pre-set their views so the map never loads them.
    for (const id of [...hide, eh.result.bins_layer_id]) state.views[id] = { visible: false, color: "#8492a6", opacity: 0.9 };
    await Promise.all([refreshLayers(), refreshTools()]);
    running = null;
    await activate(eh.result.layer_id);
    toast("Emerging hot spot analysis complete.", "success");
  } catch (e) {
    await refreshLayers().catch(() => {});
    toast(`Space-time analysis stopped: ${e.message}`, "error");
    running.failed = true;
    render();
  } finally {
    set({ jobsRunning: Math.max(0, state.jobsRunning - 1) });
  }
}

function progressCard() {
  const r = running;
  return h("div.st-card.st-progress",
    h("h4", r.failed ? "Analysis stopped" : "Running analysis…"),
    h("ol.st-steps", r.steps.map((s) => h(`li.${s.status}`,
      h("span.st-dot", s.status === "running" ? h("span.spinner") : s.status === "done" ? svgIcon("check") : s.status === "failed" ? svgIcon("xc") : svgIcon(s.icon)),
      h("div", h("div", s.label), s.detail ? h("div.small.muted", s.detail) : s.status === "running" ? h("div.st-bar", h("i", { style: { width: `${Math.round((s.progress || 0.05) * 100)}%` } })) : null)))),
    r.failed ? h("div.row", h("button.btn.sm", { onclick: () => { running = null; showWizard = true; render(); } }, "Back to settings")) : null);
}
function drawProgress() {
  const el = document.querySelector(".st-progress");
  if (el && running) el.replaceWith(progressCard());
}

// ------------------------------------------------------------------ activate a result
async function activate(locLayerId) {
  try {
    const locMeta = await loadMeta(locLayerId, true);
    const ehRun = await api.run(locMeta.parent_run_id);
    const eh = ehRun.result;
    const binsId = eh.result?.bins_layer_id;
    const cubeId = eh.inputs?.[0]?.layer_id;
    const cubeMeta = cubeId ? await loadMeta(cubeId).catch(() => null) : null;
    const cubeRun = cubeMeta?.parent_run_id ? (await api.run(cubeMeta.parent_run_id)).result : null;
    const binsMeta = binsId ? await loadMeta(binsId).catch(() => null) : null;
    const hsField = binsMeta?.profile?.fields.find((f) => /^EMERGING_.*_HS_BIN$/.test(f.name))?.name;
    stopPlay();
    locSeries = null;
    // One analysis on the map at a time: hide other space-time outputs (they stay in Contents).
    const keep = new Set([locLayerId, binsId]);
    for (const l of state.layers) {
      if (!keep.has(l.layer_id) && l.tier === "gold" && /Emerging Hot Spots|Hot Spot Bins|Space Time Cube|Cube Trends/.test(l.label) && state.views[l.layer_id]?.visible) {
        setView(l.layer_id, { visible: false });
      }
    }
    set({
      spacetime: {
        loc: locLayerId, bins: binsId, cube: cubeId, hsField, eh, cubeRun,
        variable: eh.parameters?.analysis_field || "COUNT", mode: "patterns", step: (eh.counts?.time_steps || 1) - 1, focus: null,
      },
    });
    applyMapViews();
    zoomToLayer(locLayerId);
    render();
  } catch (e) {
    toast(`Cannot open this result: ${e.message}`, "error");
  }
}

function applyMapViews() {
  const st = state.spacetime;
  if (!st) return;
  const patterns = st.mode === "patterns";
  const counts = st.eh.counts?.categories || {};
  const present = PATTERN_CLASSES.filter((c) => counts[c.label]).map((c) => String(c.value));
  setView(st.loc, {
    visible: patterns,
    renderer: {
      field: "CATEGORY", caption: "Emerging hot spot pattern",
      classes: PATTERN_CLASSES.map((c) => ({ ...c, color: st.focus == null || st.focus === c.value ? c.color : "#eef1f4" })),
      legendOnly: present,
    },
    where: null,
  });
  if (st.bins && st.hsField) {
    setView(st.bins, {
      visible: !patterns,
      renderer: { field: st.hsField, caption: `Hot / cold spots · ${stepLabel(st.step)}`, classes: BIN_CLASSES },
      where: `TIME_STEP = ${st.step}`,
    });
  }
  if (st.cube && state.views[st.cube]?.visible) setView(st.cube, { visible: false });
}

// ------------------------------------------------------------------ results view
function series() {
  const st = state.spacetime;
  return { cube: st.cubeRun?.counts?.series || null, eh: st.eh.counts?.series || null };
}
function stepLabel(i) {
  const s = series().cube;
  if (!s) return `step ${i + 1}`;
  return `${fmtDate(s.start[i])} – ${fmtDate(s.end[i])}`;
}
function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(`${d}T00:00:00`);
  return dt.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function resultsView(st) {
  const c = st.cubeRun?.counts || {};
  const e = st.eh.counts || {};
  const cats = e.categories || {};
  const nLoc = e.locations || 0;
  const hotLocs = Object.entries(cats).filter(([k]) => k.includes("Hot Spot")).reduce((a, [, n]) => a + n, 0);
  const coldLocs = Object.entries(cats).filter(([k]) => k.includes("Cold Spot")).reduce((a, [, n]) => a + n, 0);
  const emerging = ["New Hot Spot", "Consecutive Hot Spot", "Intensifying Hot Spot"].reduce((a, k) => a + (cats[k] || 0), 0);
  const tr = c.overall_trend;
  const trendTxt = tr ? (tr.direction === "increasing" ? "↑ Increasing" : tr.direction === "decreasing" ? "↓ Decreasing" : "No significant trend") : "—";
  const s = series();

  return h("div.st-results",
    h("div.st-sub", layerById(st.loc)?.label || "Result",
      h("span.small.muted", ` · ${c.first_time ? `${fmtDate(c.first_time.slice(0, 10))} – ${fmtDate(c.last_time.slice(0, 10))}` : ""}`)),
    h("div.kpis",
      kpi(fmtNum(c.aggregated_points ?? "—"), "Events analysed", c.excluded_unknown_time ? `${fmtNum(c.excluded_unknown_time)} without a date excluded` : "all events dated"),
      kpi(fmtNum(nLoc), "Locations", `${fmtNum(c.bin_size ? Math.round(c.bin_size) : "—")} ${c.bin_size_units || ""} bins`),
      kpi(String(e.time_steps ?? "—"), "Time steps", st.eh.parameters ? `${st.cubeRun?.parameters?.time_step_interval ?? ""} ${st.cubeRun?.parameters?.time_step_unit ?? ""}` : ""),
      kpi(trendTxt, "Overall trend", tr ? `Mann-Kendall z ${tr.z.toFixed(2)} · p ${tr.p.toFixed(3)}` : "", tr?.direction === "increasing" ? "hot" : tr?.direction === "decreasing" ? "cold" : ""),
      kpi(fmtNum(hotLocs), "Hot spot locations", `${fmtNum(emerging)} new / consecutive / intensifying`, hotLocs ? "hot" : ""),
      kpi(fmtNum(coldLocs), "Cold spot locations", `${nLoc ? Math.round((100 * (nLoc - hotLocs - coldLocs)) / nLoc) : 0} % no pattern`, coldLocs ? "cold" : "")),

    h("div.st-card",
      h("div.st-cardhead", h("h4", "Patterns"), h("span.small.muted", "Click a pattern to highlight it on the map")),
      patternBars(cats, nLoc)),

    h("div.st-card",
      h("div.st-cardhead", h("h4", "Through time"),
        h("div.seg",
          h("button", { "aria-pressed": String(st.mode === "patterns"), onclick: () => setMode("patterns") }, "Patterns map"),
          h("button", { "aria-pressed": String(st.mode === "time"), onclick: () => setMode("time") }, "Hot spots by step"))),
      s.cube ? timeChart(s) : h("div.small.muted", "Time series not available for this result."),
      st.mode === "time" ? timeSlider(st) : h("div.small.muted.st-hint", "Switch to “Hot spots by step” to play the hot / cold spots through each time step.")),

    h("div.st-card",
      h("div.st-cardhead", h("h4", "Selected location")),
      locationPanel(st)),

    h("div.row.st-actions",
      h("button.btn.sm", { onclick: () => openTable(st.loc) }, svgIcon("table"), "Locations table"),
      st.bins ? h("button.btn.sm", { onclick: () => openTable(st.bins) }, svgIcon("table"), "Bins table") : null,
      h("button.btn.sm", { onclick: () => zoomToLayer(st.loc) }, svgIcon("extent"), "Zoom"),
      h("a.btn.sm", { href: `/api/tool-runs/${st.eh.run_id}/result`, target: "_blank", rel: "noreferrer" }, svgIcon("file"), "Manifest")),
    h("div.small.muted.st-foot", `Neighborhood ${fmtNum(e.neighborhood_distance)} ${e.neighborhood_distance_units || ""}, ${e.neighborhood_time_step ?? 1} step(s) back · Gi* with FDR correction · status: functional, not yet validated against ArcGIS Pro.`));
}

function kpi(value, label, sub, tone = "") {
  return h(`div.kpi${tone ? `.${tone}` : ""}`, h("div.kv", value), h("div.kl", label), sub ? h("div.ks", sub) : null);
}

function patternBars(cats, total) {
  const st = state.spacetime;
  const rows = PATTERN_CLASSES.filter((c) => cats[c.label]);
  if (!rows.length) return h("div.small.muted", "No locations.");
  const max = Math.max(...rows.map((c) => cats[c.label]));
  return h("div.pbars", rows.map((c) => {
    const n = cats[c.label];
    const active = st.focus === c.value;
    return h(`button.pbar${active ? ".active" : ""}${st.focus != null && !active ? ".dim" : ""}`,
      { title: `${n} of ${total} locations`, onclick: () => { st.focus = active ? null : c.value; if (st.mode !== "patterns") st.mode = "patterns"; applyMapViews(); render(); } },
      h("i.sw", { style: { background: c.color } }),
      h("span.pl", c.label),
      h("span.pt", h("i", { style: { width: `${Math.max(2, (100 * n) / max)}%`, background: c.color } })),
      h("span.pn", n.toLocaleString()));
  }));
}

function timeChart(s) {
  const st = state.spacetime;
  const vals = (st.variable !== "COUNT" && s.cube[st.variable]) || s.cube.count;
  const hot = s.eh?.hot_bins || [];
  const cold = s.eh?.cold_bins || [];
  const n = vals.length;
  const W = 340, H = 130, pad = { l: 34, r: 8, t: 10, b: 22 };
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const vmax = Math.max(1, ...vals);
  const hmax = Math.max(1, ...hot, ...cold);
  const bw = iw / n;
  const y = (v) => pad.t + ih - (ih * v) / vmax;
  const yh = (v) => pad.t + ih - (ih * v) / hmax;
  const sel = st.mode === "time" ? st.step : -1;
  const bars = vals.map((v, i) => `<rect x="${(pad.l + i * bw + bw * 0.12).toFixed(1)}" y="${y(v).toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" height="${(pad.t + ih - y(v)).toFixed(1)}" class="${i === sel ? "b sel" : "b"}" data-i="${i}"><title>${stepLabel(i)}: ${fmtNum(v)}${hot.length ? ` · ${hot[i]} hot / ${cold[i]} cold bins` : ""}</title></rect>`).join("");
  const line = (arr, cls) => (arr.length ? `<polyline class="${cls}" points="${arr.map((v, i) => `${(pad.l + i * bw + bw / 2).toFixed(1)},${yh(v).toFixed(1)}`).join(" ")}"/>` : "");
  const ticks = [0, Math.round(vmax / 2), vmax].map((v) => `<text x="${pad.l - 5}" y="${(y(v) + 3).toFixed(1)}" class="ax" text-anchor="end">${fmtNum(Math.round(v))}</text><line x1="${pad.l}" x2="${W - pad.r}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="gl"/>`).join("");
  const lbl = (i, anchor) => `<text x="${(pad.l + i * bw + bw / 2).toFixed(1)}" y="${H - 6}" class="ax" text-anchor="${anchor}">${(s.cube.start[i] || "").slice(0, 7)}</text>`;
  const svg = `<svg viewBox="0 0 ${W} ${H}" class="tchart" role="img" aria-label="Events per time step">${ticks}${bars}${line(hot, "hl")}${line(cold, "cl")}${lbl(0, "start")}${lbl(Math.floor(n / 2), "middle")}${lbl(n - 1, "end")}</svg>`;
  const el = h("div.tchart-wrap", { html: svg });
  el.addEventListener("click", (ev) => {
    const i = ev.target?.dataset?.i;
    if (i == null) return;
    st.step = Number(i);
    if (st.mode !== "time") st.mode = "time";
    applyMapViews();
    render();
  });
  return h("div", el,
    h("div.tlegend", h("span", h("i.sw.bar"), st.variable === "COUNT" ? "Events per step" : `${st.variable} per step`),
      hot.length ? h("span", h("i.sw.hl"), "Hot bins") : null, cold.length ? h("span", h("i.sw.cl"), "Cold bins") : null));
}

function timeSlider(st) {
  const n = st.eh.counts?.time_steps || 1;
  const s = series();
  return h("div.tslider",
    h("button.icon-btn", { title: playTimer ? "Pause" : "Play through time", "aria-label": "Play", onclick: togglePlay }, svgIcon(playTimer ? "pause" : "play")),
    h("input", { type: "range", min: "0", max: String(n - 1), value: String(st.step), "aria-label": "Time step", oninput: (e) => { st.step = Number(e.target.value); applyMapViews(); render(); } }),
    h("div.tsl", h("b", `Step ${st.step + 1} / ${n}`), h("span.small.muted", stepLabel(st.step)),
      s.eh ? h("span.small", h("span.hot", `${s.eh.hot_bins[st.step]} hot`), " · ", h("span.cold", `${s.eh.cold_bins[st.step]} cold`)) : null));
}

function setMode(mode) {
  const st = state.spacetime;
  if (st.mode === mode) return;
  st.mode = mode;
  if (mode === "patterns") stopPlay();
  applyMapViews();
  render();
}
function togglePlay() {
  const st = state.spacetime;
  if (playTimer) { stopPlay(); render(); return; }
  const n = st.eh.counts?.time_steps || 1;
  if (st.step >= n - 1) st.step = 0;
  playTimer = setInterval(() => {
    if (!state.spacetime || state.spacetime.mode !== "time") return stopPlay();
    st.step = (st.step + 1) % n;
    applyMapViews();
    render();
    if (st.step === n - 1) { stopPlay(); render(); }
  }, 1100);
  render();
}
function stopPlay() {
  if (playTimer) clearInterval(playTimer);
  playTimer = null;
}

// ------------------------------------------------------------------ selected location
async function onSelection() {
  const st = state.spacetime;
  if (!st) return;
  const layer = [st.loc, st.bins].find((id) => id && state.selection[id]?.length === 1);
  if (!layer) return;
  const fid = state.selection[layer][0];
  try {
    const row = (await api.table(layer, { where: `_hpw_fid = ${fid}`, limit: 1 })).rows[0];
    const loc = row?.LOCATION_ID;
    if (loc == null || locSeries?.location === loc) return;
    const [bins, locRow] = await Promise.all([
      st.bins ? api.table(st.bins, { where: `LOCATION_ID = ${loc}`, limit: 1000, sort: [{ field: "TIME_STEP" }] }) : null,
      api.table(st.loc, { where: `LOCATION_ID = ${loc}`, limit: 1 }),
    ]);
    locSeries = { location: loc, rows: bins?.rows || [], info: locRow.rows[0] };
    if (state.gpTab === "spacetime") render();
  } catch { /* selection on another layer */ }
}

function locationPanel(st) {
  if (!locSeries) return h("div.small.muted", "Click a location on the map to see its history.");
  const info = locSeries.info || {};
  const cls = PATTERN_CLASSES.find((c) => c.value === info.CATEGORY);
  const v = st.variable.toUpperCase();
  const vals = locSeries.rows.map((r) => Number(r[st.variable]) || 0);
  const bins = locSeries.rows.map((r) => Number(r[st.hsField]) || 0);
  const W = 340, H = 76, n = Math.max(1, vals.length), bw = (W - 8) / n, vmax = Math.max(1, ...vals);
  const color = (b) => BIN_CLASSES.find((c) => c.value === b)?.color || "#e4e9ef";
  const bars = vals.map((val, i) => {
    const bh = Math.max(2, ((H - 16) * val) / vmax);
    return `<rect x="${(4 + i * bw + bw * 0.1).toFixed(1)}" y="${(H - 12 - bh).toFixed(1)}" width="${(bw * 0.8).toFixed(1)}" height="${bh.toFixed(1)}" fill="${color(bins[i])}" stroke="rgba(15,42,67,.25)" stroke-width=".5"><title>${stepLabel(i)}: ${fmtNum(val)} · ${BIN_CLASSES.find((c) => c.value === bins[i])?.label || ""}</title></rect>`;
  }).join("");
  const fmtZ = (z, p) => (z == null ? "—" : `z ${Number(z).toFixed(2)} (p ${Number(p).toFixed(3)})`);
  return h("div.locpanel",
    h("div.locpat", h("i.sw", { style: { background: cls?.color || "#ccc" } }), h("b", info.PATTERN || "—"), h("span.muted.small", ` · location ${locSeries.location}`)),
    h("div.tchart-wrap", { html: `<svg viewBox="0 0 ${W} ${H}" class="tchart" role="img" aria-label="Location history">${bars}<line x1="4" x2="${W - 4}" y1="${H - 12}" y2="${H - 12}" class="gl"/></svg>` }),
    h("dl.kv.small",
      h("dt", `${v} total`), h("dd", fmtNum(info[`${v}_TOTAL`])),
      h("dt", "Hot / cold steps"), h("dd", `${info.NUM_HOT ?? 0} hot · ${info.NUM_COLD ?? 0} cold of ${info.NUM_TIME_STEPS ?? n}`),
      h("dt", "Clustering trend"), h("dd", fmtZ(info[`EMERGING_${v}_TREND_ZSCORE`], info[`EMERGING_${v}_TREND_PVALUE`])),
      h("dt", "Value trend"), h("dd", fmtZ(info[`${v}_TREND_ZSCORE`], info[`${v}_TREND_PVALUE`]))));
}

// ------------------------------------------------------------------ existing results
function existingResultsPicker() {
  const results = state.layers.filter((l) => l.tier === "gold" && /Emerging Hot Spots/.test(l.label));
  if (!results.length) return null;
  return h("div.st-card.st-existing",
    h("div.form-row", h("label", "Open a previous result"),
      h("select", { onchange: (e) => e.target.value && activate(e.target.value) },
        h("option", { value: "" }, `— ${results.length} saved result${results.length > 1 ? "s" : ""} —`),
        results.map((l) => h("option", { value: l.layer_id, selected: state.spacetime?.loc === l.layer_id }, l.label)))));
}
