// Geoprocessing pane: tool gallery, forms generated from registry metadata, job status, history.
import { api } from "./api.js";
import { reloadAll } from "./map.js";
import { renderSpaceTime } from "./spacetime.js";
import { reloadTable } from "./table.js";
import {
  layerById, loadMeta, on, openTable, openTool, refreshLayers, refreshSelection, refreshTools, set, state, zoomToLayer, zoomToSelection,
} from "./state.js";
import { $, fmtNum, h, svgIcon, toast, toolIcon } from "./ui.js";

const UNITS = { meters: "Meters", kilometers: "Kilometers", feet: "Feet (international)", us_survey_feet: "US survey feet", yards: "Yards", miles: "Miles" };
let current = null; // {tool, values, job, errors, poll}

export function initGeoprocessing() {
  on(["tools", "activeToolId", "gpTab"], render);
  on("runsVersion", () => state.gpTab === "history" && render());
  on("selection", () => { if (current && state.gpTab === "tools" && state.activeToolId) renderForm(); });
  document.querySelectorAll("[data-ptab]").forEach((b) => b.addEventListener("click", () => set({ gpTab: b.dataset.ptab })));
  render();
}

function render() {
  document.querySelectorAll("[data-ptab]").forEach((b) => b.classList.toggle("active", b.dataset.ptab === state.gpTab));
  if (state.gpTab === "history") return renderHistory();
  if (state.gpTab === "spacetime") return renderSpaceTime();
  const tool = state.tools.find((t) => t.id === state.activeToolId);
  if (!tool) { current = null; return renderGallery(); }
  if (!current || current.tool.id !== tool.id || state.toolPreset) {
    if (current?.poll) clearInterval(current.poll);
    current = { tool, values: defaults(tool, state.toolPreset), job: null, errors: [], verify: {} };
    state.toolPreset = null;
  } else {
    current.tool = tool; // refreshed compatibility
  }
  renderForm();
}

// ------------------------------------------------------------------ gallery
function renderGallery() {
  const root = $("#gp");
  const search = h("input", { type: "search", placeholder: "Find a tool…", "aria-label": "Find a tool", value: renderGallery.q || "" });
  const list = h("div");
  const draw = () => {
    const q = (renderGallery.q = search.value).toLowerCase();
    const groups = {};
    for (const t of state.tools) {
      if (q && !`${t.name} ${t.summary} ${t.category} ${t.toolbox}`.toLowerCase().includes(q)) continue;
      (groups[`${t.toolbox} · ${t.category}`] ??= []).push(t);
    }
    list.replaceChildren(
      ...Object.entries(groups).sort().map(([g, ts]) =>
        h("div.gp-section", h("h3", g), ts.map((t) =>
          h("button.tool-card", { onclick: () => openTool(t.id) },
            h("span.ic", svgIcon(toolIcon(t.id))),
            h("span", h("div.tt", t.name), h("div.ts", t.summary), h("div.tb", eligibleText(t))))))),
      Object.keys(groups).length ? null : h("div.gp-note", "No tools match."),
    );
  };
  search.addEventListener("input", draw);
  draw();
  root.replaceChildren(
    h("div.gp-search", h("span", { "data-icon": "search" }, svgIcon("search")), search),
    list,
    h("div.gp-note", "Each tool is implemented once and offered to every compatible layer. Layers that cannot be used are listed in the tool with the reason."),
  );
}

function eligibleText(t) {
  const p = t.params.find((x) => x.type === "layer");
  if (!p?.compatibility) return "";
  const n = p.compatibility.filter((c) => c.compatible).length;
  return `${n} of ${p.compatibility.length} layers eligible`;
}

// ------------------------------------------------------------------ form
function defaults(tool, preset) {
  const v = { use_selection: true };
  for (const p of tool.params) v[p.name] = p.default ?? (p.type === "fields" ? [] : p.type === "boolean" ? false : "");
  if (preset) for (const [k, x] of Object.entries(preset)) if (x !== null && x !== undefined) v[k] = x;
  return v;
}
const visibleParams = (tool, values) => tool.params.filter((p) => !p.visible_when || Object.entries(p.visible_when).every(([k, allowed]) => allowed.includes(values[k])));

function renderForm() {
  const { tool, values } = current;
  const root = $("#gp");
  for (const p of tool.params) {
    const lid = values[p.name];
    if (p.type === "layer" && lid && !state.meta[lid]) loadMeta(lid).then(() => current?.tool === tool && renderForm()).catch(() => {});
  }

  const vis = visibleParams(tool, values);
  const form = h("form.tool-form", { onsubmit: (e) => { e.preventDefault(); run(); } },
    vis.map((p) => paramEl(p)),
    tool.output_type === "layer"
      ? h("div.param.inline", h("label", { for: "use-sel" }, "Use selected features only", h("span.muted.small", selHint())),
        h("input#use-sel", { type: "checkbox", checked: !!values.use_selection, onchange: (e) => { values.use_selection = e.target.checked; } }))
      : null,
    current.errors.length ? h("ul.form-errors", current.errors.map((e) => h("li", e))) : null,
  );
  const running = current.job && ["queued", "running"].includes(current.job.status);
  root.replaceChildren(
    h("div.tool-head",
      h("button.back", { onclick: () => set({ activeToolId: null }) }, svgIcon("chevleft"), "All tools"),
      h("div.tool-title", h("span.ic", svgIcon(toolIcon(tool.id))),
        h("div", h("h2", tool.name), h("div.crumb", `${tool.toolbox} › ${tool.category}  `, h(`span.status-pill.${tool.status}`, tool.status.replace(/_/g, " "))))),
      h("p.tool-summary", tool.summary)),
    form,
    h("div.run-bar",
      running ? h("button.btn", { onclick: () => api.cancel(current.job.run_id) }, svgIcon("stop"), "Cancel") : null,
      h("button.btn.primary", { disabled: running, onclick: run }, svgIcon("play"), running ? "Running…" : "Run")),
    current.job ? jobCard(current.job) : null,
    h("details.refbox",
      h("summary", "Reference & known differences"),
      h("p.small", "Functional reference: ", h("a", { href: tool.reference_url, target: "_blank", rel: "noreferrer" }, "ArcGIS Pro documentation"),
        ` (retrieved ${tool.reference_retrieved}). Independent implementation — no ArcGIS code or license is used.`),
      h("ul", tool.known_differences.map((d) => h("li", d)))),
  );
}

function selHint() {
  const ids = current.tool.params.filter((p) => p.type === "layer").map((p) => current.values[p.name]).filter(Boolean);
  const n = ids.reduce((a, id) => a + (state.selection[id]?.length || 0), 0);
  return n ? ` (${n} selected)` : " (nothing selected — all features used)";
}

function setVal(name, v, rerender = true) {
  current.values[name] = v;
  current.errors = [];
  if (rerender) renderForm();
}

function paramEl(p) {
  const { tool, values } = current;
  const id = `p-${p.name}`;
  const v = values[p.name];
  const parentMeta = p.parent ? state.meta[values[p.parent]] : null;
  const fields = (parentMeta?.profile?.fields || []).filter((f) => !f.internal && (!p.field_types || p.field_types.includes(f.type)));
  let input;
  const extra = [];
  switch (p.type) {
    case "layer": {
      const comp = p.compatibility || [];
      const ok = comp.filter((c) => c.compatible), bad = comp.filter((c) => !c.compatible);
      input = h("select", { id, onchange: (e) => setVal(p.name, e.target.value) },
        h("option", { value: "" }, "Choose a layer…"),
        ok.map((c) => h("option", { value: c.layer_id }, c.label)),
        bad.length ? h("optgroup", { label: "Not eligible" }, bad.map((c) => h("option", { value: c.layer_id, disabled: true }, `${c.label} — ${c.reason}`))) : null);
      input.value = v || "";
      const nsel = state.selection[v]?.length || 0;
      if (nsel) extra.push(h("div.hint.sel", `${nsel} selected feature(s) in this layer.`));
      if (bad.length) extra.push(h("details.inelig", h("summary", `${bad.length} layer(s) not eligible — why?`), h("ul", bad.map((c) => h("li", h("b", c.label), ": ", c.reason)))));
      break;
    }
    case "number":
      input = h("input", { id, type: "number", step: "any", value: v === "" || v == null ? "" : String(v), min: p.min ?? undefined,
        oninput: (e) => setVal(p.name, e.target.value === "" ? "" : Number(e.target.value), false) });
      break;
    case "enum":
    case "linear_unit": {
      const vals = p.values || Object.keys(UNITS);
      const label = (x) => p.value_labels?.[x] || UNITS[x] || x.replace(/_/g, " ");
      const disabled = (x) => tool.id === "analysis.buffer" && p.name === "method" && x === "geodesic";
      if (vals.length <= 3 && !p.value_labels) {
        input = h("div.seg", { role: "group", "aria-label": p.label }, vals.map((x) =>
          h("button", { type: "button", "aria-pressed": String(v === x), disabled: disabled(x), onclick: () => setVal(p.name, x) }, label(x))));
      } else {
        input = h("select", { id, onchange: (e) => setVal(p.name, e.target.value) }, vals.map((x) => h("option", { value: x, disabled: disabled(x) }, label(x))));
        input.value = v;
      }
      break;
    }
    case "boolean":
      return h("div.param.inline", h("label", { for: id }, p.label), h("input", { id, type: "checkbox", checked: !!v, onchange: (e) => setVal(p.name, e.target.checked, false) }));
    case "field":
      input = h("select", { id, disabled: !parentMeta, onchange: (e) => setVal(p.name, e.target.value) },
        h("option", { value: "" }, parentMeta ? "— none —" : "Choose the input layer first"),
        fields.map((f) => h("option", { value: f.name }, `${f.name}  (${f.type})`)));
      input.value = v || "";
      break;
    case "fields": {
      const arr = Array.isArray(v) ? v : [];
      input = h("div.checks", parentMeta ? fields.map((f) =>
        h("label.check", h("input", { type: "checkbox", checked: arr.includes(f.name), onchange: (e) => setVal(p.name, e.target.checked ? [...arr, f.name] : arr.filter((x) => x !== f.name), false) }), f.name))
        : h("span.muted.small", "Choose the input layer first"));
      break;
    }
    case "expression": {
      const ta = h("textarea", { id, rows: 3, spellcheck: false, placeholder: p.description, oninput: (e) => { setVal(p.name, e.target.value, false); current.verify[p.name] = null; } });
      ta.value = v || "";
      input = ta;
      const insert = (txt) => { const s = ta.value; ta.value = `${s}${s && !s.endsWith(" ") ? " " : ""}${txt} `; setVal(p.name, ta.value, false); ta.focus(); };
      extra.push(h("div.fieldchips",
        fields.slice(0, 30).map((f) => h("button.chip", { type: "button", title: f.type, onclick: () => insert(/^[A-Za-z_]\w*$/.test(f.name) ? f.name : `"${f.name}"`) }, f.name)),
        ["=", ">=", "<=", "<>", "AND", "OR", "IN ( )", "LIKE '%'", "IS NULL"].map((op) => h("button.chip", { type: "button", onclick: () => insert(op) }, op)),
        h("button.chip", { type: "button", style: { borderColor: "var(--accent)", color: "var(--accent)" }, onclick: () => verify(p) }, svgIcon("check"), " Verify")));
      const vr = current.verify[p.name];
      if (vr) extra.push(h(`div.hint.${vr.ok ? "ok" : "bad"}`, vr.text));
      break;
    }
    case "crs":
      input = h("input", { id, value: v || "", list: "crs-presets", placeholder: "EPSG:2278", oninput: (e) => setVal(p.name, e.target.value, false) });
      break;
    default:
      input = h("input", { id, value: v || "", oninput: (e) => setVal(p.name, e.target.value, false) });
  }
  return h("div.param",
    h("label", { for: id }, p.label, p.required ? h("span.req", { "aria-label": "required" }, "*") : null),
    input,
    ...extra,
    p.description && p.type !== "expression" ? h("div.hint", p.description) : null);
}

async function verify(p) {
  const layer = current.values[p.parent];
  const expr = current.values[p.name];
  if (!layer || !expr) return;
  try {
    const r = await api.table(layer, { where: expr, limit: 1 });
    current.verify[p.name] = { ok: true, text: `✓ Valid expression — ${r.filtered.toLocaleString()} of ${r.total.toLocaleString()} rows match` };
  } catch (e) {
    current.verify[p.name] = { ok: false, text: `✗ ${e.message}` };
  }
  renderForm();
}

function prevalidate() {
  const { tool, values } = current;
  const errs = [];
  for (const p of visibleParams(tool, values)) {
    const v = values[p.name];
    const empty = v === "" || v == null || (Array.isArray(v) && !v.length);
    if (p.required && empty && p.type !== "boolean") errs.push(`${p.label} is required.`);
    if (p.type === "number" && !empty && p.min != null && Number(v) < p.min) errs.push(`${p.label} must be ≥ ${p.min}.`);
  }
  if (tool.id === "analysis.buffer" && (values.distance === "" || values.distance == null) && !values.distance_field) errs.push("Enter a distance or choose a distance field.");
  return errs;
}

async function run() {
  const { tool, values } = current;
  current.errors = prevalidate();
  if (current.errors.length) return renderForm();
  const params = { use_selection: values.use_selection };
  for (const p of visibleParams(tool, values)) {
    const v = values[p.name];
    if (v === "" || v == null || (Array.isArray(v) && !v.length)) continue;
    params[p.name] = v;
  }
  try {
    current.job = await api.runTool(tool.id, params);
  } catch (e) {
    current.errors = e.message.split("\n");
    return renderForm();
  }
  set({ jobsRunning: state.jobsRunning + 1 });
  renderForm();
  const mine = current;
  mine.poll = setInterval(async () => {
    let j;
    try { j = await api.run(mine.job.run_id); } catch { return; }
    mine.job = j;
    if (current === mine && state.gpTab === "tools" && state.activeToolId === mine.tool.id) renderForm();
    if (["queued", "running"].includes(j.status)) return;
    clearInterval(mine.poll);
    set({ jobsRunning: Math.max(0, state.jobsRunning - 1) });
    await Promise.all([refreshLayers(), refreshSelection(), refreshTools()]);
    set({ runsVersion: state.runsVersion + 1 });
    reloadAll();
    reloadTable();
    const m = j.result;
    if (j.status === "succeeded" && m?.outputs?.length) {
      const o = m.outputs[0];
      openTable(o.layer_id);
      zoomToLayer(o.layer_id);
      toast(`${tool.name} complete — '${o.label}' (${o.feature_count.toLocaleString()} features) added to the map.`, "success");
    } else if (j.status === "succeeded" && m?.result?.kind === "selection") {
      openTable(m.inputs[0].layer_id);
      toast(`${tool.name}: ${m.result.selected_count.toLocaleString()} feature(s) now selected.`, "success");
    } else if (j.status === "failed") toast(`${tool.name} failed: ${j.error}`, "error");
    else if (j.status === "cancelled") toast(`${tool.name} cancelled.`, "warning");
  }, 350);
}

const COUNT_LABELS = {
  input_features: "Input", output_features: "Output", processed: "Processed", matched: "Matched", selected_after: "Selected now",
  fully_inside: "Fully inside", partially_clipped: "Cut at edge", outside_excluded: "Outside", excluded_empty_output: "Empty results", selected_before: "Selected before",
};

function jobCard(j) {
  const m = j.result;
  const status = { queued: "Queued…", running: "Running…", succeeded: "Completed", failed: "Failed", cancelled: "Cancelled" }[j.status];
  const ic = { succeeded: "checkc", failed: "xc", cancelled: "warn" }[j.status];
  const counts = Object.entries(m?.counts || {}).filter(([, v]) => typeof v === "number");
  return h(`div.job.${j.status}`,
    h("div.job-head", ic ? svgIcon(ic) : h("span.spinner"), status,
      j.duration_s != null ? h("span.dur", `${j.duration_s.toFixed(2)} s`) : null,
      m ? h("a.push.small", { href: `/api/tool-runs/${j.run_id}/result`, target: "_blank", rel: "noreferrer" }, "Provenance manifest") : null),
    ["queued", "running"].includes(j.status) ? h("div.progress.indet", h("i")) : null,
    ...(m?.outputs || []).map((o) =>
      h("div.job-out",
        h("div.ot", o.label),
        h("div.os", `${o.feature_count.toLocaleString()} ${o.geometry_family || ""} features · ${o.crs || "CRS unknown"} · new layer`),
        h("div.row",
          h("button.btn.sm", { onclick: () => openTable(o.layer_id) }, svgIcon("table"), "Table"),
          h("button.btn.sm", { onclick: () => zoomToLayer(o.layer_id) }, svgIcon("extent"), "Zoom"),
          h("button.btn.sm", { onclick: () => import("./dialogs.js").then((d) => d.openProperties(o.layer_id)) }, svgIcon("info"), "Properties")))),
    m?.result?.kind === "selection"
      ? h("div.job-out", h("div.ot", `${(m.result.selected_count ?? 0).toLocaleString()} selected`), h("div.os", `${m.result.matched_count} matched in ${layerById(m.inputs[0]?.layer_id)?.label || ""}`),
        h("div.row", h("button.btn.sm", { onclick: () => openTable(m.inputs[0].layer_id) }, svgIcon("table"), "Table"), h("button.btn.sm", { onclick: () => zoomToSelection(m.inputs[0].layer_id) }, svgIcon("zoomsel"), "Zoom to selection")))
      : null,
    counts.length ? h("div.counts", counts.map(([k, v]) => h("div.c", h("b", fmtNum(v)), h("span", COUNT_LABELS[k] || k.replace(/_/g, " "))))) : null,
    (j.messages || []).length
      ? h("ul.msgs", (j.messages || []).filter((x) => x.level !== "debug").map((x) =>
        h(`li.${x.level}`, svgIcon(x.level === "warning" ? "warn" : x.level === "error" ? "xc" : "info"), h("span", x.text))))
      : null,
  );
}

// ------------------------------------------------------------------ history
async function renderHistory() {
  const root = $("#gp");
  root.replaceChildren(h("div.history", h("p.muted", "Loading…")));
  let runs = [];
  try { runs = await api.runs(); } catch (e) { root.replaceChildren(h("div.history", h("p.muted", e.message))); return; }
  if (state.gpTab !== "history") return;
  const name = (id) => state.tools.find((t) => t.id === id)?.name || id;
  root.replaceChildren(h("div.history",
    runs.length ? null : h("div.contents-empty", svgIcon("history"), h("p", "No tool runs yet.")),
    runs.map((r) => h("details.hrun",
      h("summary", h(`span.dot.${r.status}`, { title: r.status }), h("span.hn", name(r.tool_id)),
        h("span.hm", `${(r.submitted_at || "").replace("T", " ").slice(0, 19)} · ${r.duration_s != null ? r.duration_s.toFixed(2) + " s" : "–"}`)),
      h("div.hb",
        h("pre", JSON.stringify(r.params, null, 1)),
        ...(r.result?.outputs || []).map((o) => h("div", "→ ", h("b", o.label), ` (${o.feature_count} features)`)),
        r.error ? h("div.callout.bad", r.error) : null,
        h("div.row", { style: { display: "flex", gap: "6px", marginTop: "6px" } },
          h("button.btn.sm", { onclick: () => openTool(r.tool_id, r.params) }, svgIcon("play"), "Open with these parameters"),
          r.status === "succeeded" ? h("a.btn.sm", { href: `/api/tool-runs/${r.run_id}/result`, target: "_blank", rel: "noreferrer" }, svgIcon("file"), "Manifest") : null))))));
}
