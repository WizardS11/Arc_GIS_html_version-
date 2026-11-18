// Attribute table pane: tabs per layer, server-side paging/sort/search/filter, selection sync, stats, export.
import { api, exportUrl } from "./api.js";
import { closeTable, layerById, on, select, set, state, zoomToSelection } from "./state.js";
import { $, fmtNum, h, showMenu, svgIcon, symbolSvg, toast } from "./ui.js";

const FID = "_hpw_fid";
const PAGE = 200;
const tableState = {}; // per layer: {offset, sort, search, where, selectedOnly, hidden:Set}
let data = null;
let lastClicked = null;
let fetchSeq = 0;
let collapsed = false;

const ts = (id) => (tableState[id] ??= { offset: 0, sort: [], search: "", where: "", selectedOnly: false, hidden: new Set() });

export function initTable() {
  on(["tableLayers", "activeTable"], () => { renderShell(); load(); });
  on("layers", () => { renderTabs(); if (state.activeTable && !layerById(state.activeTable)) closeTable(state.activeTable); });
  on("selection", () => {
    const t = state.activeTable && ts(state.activeTable);
    if (t?.selectedOnly) load();
    else paintSelection();
    renderSelInfo();
  });
  on("panes", applyPane);
  renderShell();
}

function applyPane() {
  $("#pane-bottom").classList.toggle("closed", !state.panes.bottom);
  document.querySelector('.splitter[data-split="bottom"]').hidden = !state.panes.bottom || collapsed;
}

// ------------------------------------------------------------------ shell
function renderShell() {
  const pane = $("#pane-bottom");
  pane.classList.toggle("collapsed", collapsed);
  applyPane();
  if (!state.tableLayers.length) {
    pane.replaceChildren(h("div.ttabs", h("span.muted.small", { style: { alignSelf: "center", padding: "0 8px" } }, "Attribute table — click a layer in Contents or a feature on the map to open its table.")));
    return;
  }
  const id = state.activeTable;
  pane.replaceChildren(
    h("div.ttabs#ttabs"),
    collapsed || !id ? null : toolsBar(id),
    collapsed || !id ? null : h("div.stats-bar#stats-bar", { hidden: true }),
    collapsed || !id ? null : h("div.tscroll#tscroll", h("div.tempty", "Loading…")),
    collapsed || !id ? null : h("div.tfoot#tfoot"),
  );
  renderTabs();
}

function renderTabs() {
  const el = $("#ttabs");
  if (!el) return;
  el.replaceChildren(
    ...state.tableLayers.map((id) => {
      const l = layerById(id);
      return h(`div.ttab${id === state.activeTable ? ".active" : ""}`, { role: "tab", onclick: () => { collapsed = false; set({ activeTable: id, activeLayer: id }); } },
        l ? symbolSvg(l.geometry_family, state.views[id]?.color || "#888", "sw") : null,
        h("span", l?.label ?? id),
        h("button.icon-btn", { "aria-label": "Close table", onclick: (e) => { e.stopPropagation(); closeTable(id); } }, svgIcon("close")));
    }),
    h("span.spacer"),
    h("div.ttabs-actions",
      h("button.icon-btn", { title: collapsed ? "Expand" : "Collapse", "aria-label": collapsed ? "Expand table" : "Collapse table", onclick: () => { collapsed = !collapsed; renderShell(); if (!collapsed) load(); } },
        svgIcon(collapsed ? "up" : "down")),
      h("button.icon-btn", { title: "Close pane", "aria-label": "Close table pane", onclick: () => set({ panes: { ...state.panes, bottom: false } }) }, svgIcon("close"))),
  );
}

function toolsBar(id) {
  const t = ts(id);
  let timer;
  const whereInput = h("input", { value: t.where, placeholder: "Filter  e.g.  DIAMETER_IN >= 12 AND MATERIAL = 'PVC'", spellcheck: false, "aria-label": "Filter expression" });
  return h("div.ttools",
    h("div.search-box", h("span", { "data-icon": "search" }, svgIcon("search")),
      h("input", { type: "search", value: t.search, placeholder: "Search all fields", "aria-label": "Search table",
        oninput: (e) => { clearTimeout(timer); timer = setTimeout(() => { t.search = e.target.value; t.offset = 0; load(); }, 250); } })),
    h("form.where", { onsubmit: (e) => { e.preventDefault(); t.where = whereInput.value.trim(); t.offset = 0; load(); } },
      whereInput,
      h("button.btn", { type: "submit", title: "Apply filter" }, svgIcon("filter"), "Apply"),
      t.where ? h("button.btn.ghost", { type: "button", title: "Clear filter", onclick: () => { t.where = ""; t.offset = 0; renderShell(); load(); } }, svgIcon("close")) : null),
    h("label.check", h("input", { type: "checkbox", checked: t.selectedOnly, onchange: (e) => { t.selectedOnly = e.target.checked; t.offset = 0; load(); } }), "Selected only"),
    h("span.sep"),
    h("span.selinfo#selinfo"),
    h("button.btn.sm", { onclick: () => zoomToSelection(id), title: "Zoom to selected features" }, svgIcon("zoomsel"), "Zoom"),
    h("button.btn.sm", { onclick: () => select(id, [], "switch"), title: "Switch selection" }, svgIcon("swap"), "Switch"),
    h("button.btn.sm", { onclick: () => select(id, [], "clear"), title: "Clear selection" }, svgIcon("clear"), "Clear"),
    h("span.sep"),
    h("button.btn.sm", { onclick: (e) => statsMenu(id, e.currentTarget) }, svgIcon("stats"), "Statistics"),
    h("button.btn.sm", { onclick: (e) => columnsMenu(id, e.currentTarget) }, svgIcon("columns"), "Fields"),
    h("button.btn.sm", { onclick: (e) => exportMenu(id, e.currentTarget) }, svgIcon("download"), "Export"),
  );
}

function renderSelInfo() {
  const el = $("#selinfo");
  const l = layerById(state.activeTable);
  if (!el || !l) return;
  const n = state.selection[l.layer_id]?.length || 0;
  el.replaceChildren(h("b", n.toLocaleString()), ` of ${l.feature_count.toLocaleString()} selected`);
}

// ------------------------------------------------------------------ data
async function load() {
  const id = state.activeTable;
  if (!id || collapsed || !$("#tscroll")) return;
  const t = ts(id);
  const seq = ++fetchSeq;
  try {
    const d = await api.table(id, { offset: t.offset, limit: PAGE, sort: t.sort, search: t.search || null, where: t.where || null, selected_only: t.selectedOnly });
    if (seq !== fetchSeq || state.activeTable !== id) return;
    data = d;
    document.querySelector(".where input")?.classList.remove("err");
    renderGrid(id);
  } catch (e) {
    if (seq !== fetchSeq) return;
    document.querySelector(".where input")?.classList.add("err");
    $("#tscroll").replaceChildren(h("div.tempty", h("div", h("b", "Cannot load rows"), h("div.muted", e.message))));
  }
  renderSelInfo();
}

export function reloadTable() { load(); }

function renderGrid(id) {
  const t = ts(id);
  const cols = data.columns.filter((c) => !t.hidden.has(c.name));
  const sel = new Set(state.selection[id] || []);
  const thead = h("thead", h("tr",
    h("th.rownum", "#"),
    cols.map((c) => {
      const s = t.sort.find((x) => x.field === c.name);
      const num = c.type === "integer" || c.type === "double";
      return h(`th${num ? ".num" : ""}`, {
        tabindex: "0", title: `${c.name} · ${c.type} · ${c.null_count} null · click to sort, Shift+click to add`,
        "aria-sort": s ? (s.desc ? "descending" : "ascending") : "none",
        onclick: (e) => sortBy(id, c.name, e.shiftKey), onkeydown: (e) => { if (e.key === "Enter") sortBy(id, c.name, e.shiftKey); },
      },
      c.name === FID ? "FID" : c.name,
      c.name === data.primary_key && c.name !== FID ? h("span.ft", { title: "Primary key" }, "PK") : null,
      s ? h("span.sort", s.desc ? "▼" : "▲") : null);
    })));
  const tbody = h("tbody", data.rows.map((r, i) => {
    const fid = Number(r[FID]);
    return h(`tr${sel.has(fid) ? ".sel" : ""}`, {
      tabindex: "0", dataset: { fid: String(fid) }, "aria-selected": sel.has(fid) ? "true" : "false",
      onclick: (e) => rowClick(id, fid, e),
      ondblclick: async () => { await select(id, [fid], "new"); zoomToSelection(id); },
      onkeydown: (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); rowClick(id, fid, e); }
        if (e.key === "ArrowDown") { e.preventDefault(); e.currentTarget.nextElementSibling?.focus(); }
        if (e.key === "ArrowUp") { e.preventDefault(); e.currentTarget.previousElementSibling?.focus(); }
      },
    },
    h("td.rownum", String(t.offset + i + 1)),
    cols.map((c) => {
      const v = r[c.name];
      return h(`td${typeof v === "number" ? ".num" : ""}`, { title: v == null ? "" : String(v) }, v === null || v === undefined ? h("span.null", "<Null>") : typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toLocaleString(undefined, { maximumFractionDigits: 6, useGrouping: false })) : typeof v === "boolean" ? (v ? "True" : "False") : String(v));
    }));
  }));
  const scroll = $("#tscroll");
  scroll.replaceChildren(data.rows.length ? h("table.grid.attr", thead, tbody) : h("div.tempty", "No rows match."));
  const f = $("#tfoot");
  const from = data.filtered ? t.offset + 1 : 0, to = Math.min(t.offset + PAGE, data.filtered);
  f.replaceChildren(
    h("span", `Rows ${from.toLocaleString()}–${to.toLocaleString()} of ${data.filtered.toLocaleString()}`, data.filtered !== data.total ? h("span.muted", ` (filtered from ${data.total.toLocaleString()})`) : null),
    h("button.btn.sm", { disabled: t.offset === 0, onclick: () => { t.offset = Math.max(0, t.offset - PAGE); load(); } }, svgIcon("chevleft"), "Prev"),
    h("button.btn.sm", { disabled: t.offset + PAGE >= data.filtered, onclick: () => { t.offset += PAGE; load(); } }, "Next"),
    h("span.hint", "Click select · Ctrl toggle · Shift range · Double-click zoom · ↑↓ Enter"),
  );
}

function paintSelection() {
  const id = state.activeTable;
  if (!id || !$("#tscroll")) return;
  const sel = new Set(state.selection[id] || []);
  document.querySelectorAll("#tscroll tbody tr").forEach((tr) => {
    const on = sel.has(Number(tr.dataset.fid));
    tr.classList.toggle("sel", on);
    tr.setAttribute("aria-selected", on ? "true" : "false");
  });
}

function sortBy(id, field, add) {
  const t = ts(id);
  const cur = t.sort.find((s) => s.field === field);
  const next = cur ? (cur.desc ? null : { field, desc: true }) : { field, desc: false };
  t.sort = add ? [...t.sort.filter((s) => s.field !== field), ...(next ? [next] : [])] : next ? [next] : [];
  t.offset = 0;
  load();
}

function rowClick(id, fid, e) {
  if (e.shiftKey && lastClicked != null && data) {
    const ids = data.rows.map((r) => Number(r[FID]));
    const a = ids.indexOf(lastClicked), b = ids.indexOf(fid);
    if (a >= 0 && b >= 0) return select(id, ids.slice(Math.min(a, b), Math.max(a, b) + 1), "add");
  }
  lastClicked = fid;
  const isSel = (state.selection[id] || []).includes(fid);
  select(id, [fid], e.ctrlKey || e.metaKey ? (isSel ? "remove" : "add") : "new");
}

// ------------------------------------------------------------------ menus
function columnsMenu(id, anchor) {
  const t = ts(id);
  const items = (data?.columns || []).map((c) =>
    h("label.check", { style: { padding: "3px 10px", display: "flex" } },
      h("input", { type: "checkbox", checked: !t.hidden.has(c.name), onchange: (e) => { e.target.checked ? t.hidden.delete(c.name) : t.hidden.add(c.name); if (data) renderGrid(id); } }),
      c.name === FID ? "FID (internal id)" : c.name, h("span.muted.small", ` ${c.type}`)));
  showMenu(anchor, [{ heading: true, label: "Visible fields" }, ...items]);
}

function statsMenu(id, anchor) {
  const cols = (data?.columns || []).filter((c) => !c.internal);
  showMenu(anchor, [{ heading: true, label: "Field statistics" }, ...cols.map((c) => ({ label: `${c.name}  ·  ${c.type}`, icon: "stats", onClick: () => showStats(id, c.name) }))]);
}

async function showStats(id, field) {
  const bar = $("#stats-bar");
  try {
    const s = await api.stats(id, field);
    const keys = ["count", "nulls", "distinct", "sum", "mean", "median", "min", "max", "std"].filter((k) => s[k] !== undefined);
    bar.replaceChildren(
      h("b", field), h("span.muted", s.scope === "selected" ? "(selected features)" : "(all features)"),
      ...keys.map((k) => h("span", h("span.k", `${k} `), h("b", fmtNum(s[k], 4)))),
      s.top_values ? h("span", h("span.k", "top "), s.top_values.slice(0, 5).map((t) => `${t.value ?? "<Null>"} (${t.count})`).join(", ")) : null,
      h("button.icon-btn", { style: { marginLeft: "auto" }, "aria-label": "Close statistics", onclick: () => { bar.hidden = true; } }, svgIcon("close")));
    bar.hidden = false;
  } catch (e) {
    toast(e.message, "error");
  }
}

function exportMenu(id, anchor) {
  const n = state.selection[id]?.length || 0;
  const fmts = [["gpkg", "GeoPackage (.gpkg)"], ["geoparquet", "GeoParquet (.parquet)"], ["geojson", "GeoJSON (WGS84)"], ["csv", "CSV with WKT"], ["shapefile", "Shapefile (.zip)"]];
  showMenu(anchor, [
    { heading: true, label: "All features" },
    ...fmts.map(([f, label]) => ({ label, icon: "download", onClick: () => doExport(id, f, false) })),
    { heading: true, label: `Selected features (${n})` },
    ...fmts.map(([f, label]) => ({ label, icon: "download", disabled: !n, onClick: () => doExport(id, f, true) })),
  ]);
}

async function doExport(id, fmt, selOnly) {
  try {
    const r = await fetch(exportUrl(id, fmt, selOnly));
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const blob = await r.blob();
    const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "")?.[1] || id;
    const a = h("a", { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    toast(`Exported ${r.headers.get("X-HPW-Feature-Count")} features (${r.headers.get("X-HPW-CRS")}) → ${name}`, "success");
    JSON.parse(r.headers.get("X-HPW-Warnings") || "[]").forEach((w) => toast(w, "warning"));
  } catch (e) {
    toast(`Export failed: ${e.message}`, "error");
  }
}
