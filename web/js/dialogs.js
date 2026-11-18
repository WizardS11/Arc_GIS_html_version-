// Dialogs: Add Data, Layer Properties, Projects.
import { api } from "./api.js";
import {
  loadMeta, mapBridge, openTable, refreshLayers, refreshSelection, refreshTools, set, state,
} from "./state.js";
import { fmtNum, h, modal, svgIcon, symbolSvg, toast } from "./ui.js";

const FORMATS = ["GeoPackage", "GeoParquet", "GeoJSON", "Shapefile (.zip)", "CSV (X/Y or WKT)", "FlatGeobuf"];

// ------------------------------------------------------------------ Add data
export function openAddData() {
  let file = null;
  const fileInput = h("input", { type: "file", hidden: true, accept: ".gpkg,.parquet,.geoparquet,.geojson,.json,.zip,.csv,.fgb", onchange: (e) => pick(e.target.files[0]) });
  const dzFile = h("div.dz-file");
  const dz = h("div.dropzone", {
    tabindex: "0", role: "button", "aria-label": "Choose a file",
    onclick: () => fileInput.click(),
    onkeydown: (e) => { if (e.key === "Enter") fileInput.click(); },
    ondragover: (e) => { e.preventDefault(); dz.classList.add("over"); },
    ondragleave: () => dz.classList.remove("over"),
    ondrop: (e) => { e.preventDefault(); dz.classList.remove("over"); pick(e.dataTransfer.files[0]); },
  },
  svgIcon("upload"), h("div.dz-t", "Drop a GIS file here, or click to browse"),
  h("div.formats", FORMATS.map((f) => h("span.chip", f))), dzFile);
  const label = h("input", { placeholder: "Defaults to the file name" });
  const crs = h("input", { placeholder: "Only if the file has none — e.g. EPSG:2278", list: "crs-presets" });
  const pk = h("input", { placeholder: "Auto-detect" });
  const x = h("input", { placeholder: "Auto-detect" });
  const y = h("input", { placeholder: "Auto-detect" });
  const wkt = h("input", { placeholder: "Optional" });
  const csvBox = h("div", { hidden: true },
    h("div.form-grid", h("div.form-row", h("label", "X / longitude field"), x), h("div.form-row", h("label", "Y / latitude field"), y)),
    h("div.form-row", h("label", "or WKT geometry field"), wkt));
  const err = h("div");
  const fileBody = h("div.modal-body",
    dz, fileInput,
    h("div.form-row", h("label", "Layer name"), label),
    csvBox,
    h("div.form-grid",
      h("div.form-row", h("label", "Coordinate system ", h("span.muted", "(never guessed)")), crs),
      h("div.form-row", h("label", "Primary key field ", h("span.muted", "(verified)")), pk)),
    h("div.callout", svgIcon("shield"), h("div", "The original file is copied unchanged (Bronze), then normalized (Silver). Analysis always writes new layers — sources stay read-only.")),
    err);
  const go = h("button.btn.primary", { disabled: true, onclick: submit }, svgIcon("upload"), "Import & register");
  const fileFoot = h("div.modal-foot", h("button.btn", { onclick: () => dlg.close() }, "Cancel"), go);
  const lib = libraryPane();
  const holder = h("div");
  const tabBar = h("div.modal-tabs",
    h("button", { dataset: { t: "lib" }, onclick: () => show("lib") }, svgIcon("library"), "City layer library"),
    h("button", { dataset: { t: "file" }, onclick: () => show("file") }, svgIcon("upload"), "From a file"));
  const show = (t) => {
    tabBar.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.t === t));
    holder.replaceChildren(...(t === "lib" ? [lib.body, lib.foot] : [fileBody, fileFoot]));
    if (t === "lib") lib.refresh();
  };
  const dlg = modal({ title: "Add data", subtitle: "Add reference layers from the City library, or register your own file", iconName: "adddata",
    body: h("div", tabBar, holder), wide: true, onClose: () => lib.stop() });
  lib.close = () => dlg.close();
  show("lib");

  function pick(f) {
    if (!f) return;
    file = f;
    dzFile.textContent = `${f.name} · ${(f.size / 1024).toFixed(1)} KB`;
    if (!label.value) label.value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    csvBox.hidden = !f.name.toLowerCase().endsWith(".csv");
    go.disabled = false;
  }

  async function submit() {
    if (!file) return;
    go.disabled = true;
    go.lastChild.textContent = "Importing…";
    err.replaceChildren();
    const form = new FormData();
    form.append("file", file);
    if (label.value) form.append("label", label.value);
    if (crs.value) form.append("crs", crs.value);
    if (pk.value) form.append("primary_key", pk.value);
    if (!csvBox.hidden) {
      if (x.value) form.append("x_field", x.value);
      if (y.value) form.append("y_field", y.value);
      if (wkt.value) form.append("wkt_field", wkt.value);
    }
    try {
      const info = await api.importLayer(form);
      await Promise.all([refreshLayers(), refreshTools()]);
      openTable(info.layer_id);
      if (info.profile?.extent_4326) mapBridge.zoomTo(info.profile.extent_4326);
      dlg.close();
      toast(`Registered '${info.label}' — ${info.feature_count.toLocaleString()} ${info.geometry_family} features, ${info.crs?.srs || "CRS UNKNOWN"}.`, "success");
      if (info.warnings.length) openProperties(info.layer_id, "quality");
    } catch (e) {
      err.replaceChildren(h("div.callout.bad", svgIcon("xc"), h("div", e.message)));
      go.disabled = false;
      go.lastChild.textContent = "Import & register";
    }
  }
}

// ------------------------------------------------------------------ City layer library
const GEOM_FAMILY = { Point: "Point", LineString: "Line", Polygon: "Polygon" };
const fmtBytes = (b) => (b == null ? "" : b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);

function libraryPane() {
  let entries = [];
  let timer = null;
  let q = "";
  const pending = new Set(); // requested in this dialog -> report when registered
  const list = h("div.lib-list", h("div.small.muted", h("span.spinner"), " Loading the library…"));
  const summary = h("span.muted.small");
  const search = h("input", { type: "search", placeholder: "Filter library layers…", "aria-label": "Filter library layers", oninput: (e) => { q = e.target.value.toLowerCase(); draw(); } });
  const body = h("div.modal-body.lib-body",
    h("div.lib-toolbar", h("div.gp-search", h("span", { "data-icon": "search" }, svgIcon("search")), search), summary),
    list,
    h("div.callout", svgIcon("shield"), h("div", "Copies of the City dashboard layers (Houston map library + 25-basin flowmeter study), stored in this project. Adding a layer registers it read-only; large layers (parcels, finished-floor points) take a few minutes and draw only when zoomed in.")));
  const foot = h("div.modal-foot", h("span.muted.small", "Layers you add appear in Contents under their library group."), h("button.btn", { onclick: () => pane.close?.() }, "Done"));

  async function refresh() {
    try { entries = await api.library(); } catch (e) { list.replaceChildren(h("div.callout.bad", svgIcon("xc"), h("div", e.message))); return; }
    draw();
    const busy = entries.some((e) => e.status === "queued" || e.status === "importing");
    const done = entries.filter((e) => pending.has(e.layer_id) && (e.status === "registered" || e.status === "error"));
    if (done.length) {
      done.forEach((e) => { pending.delete(e.layer_id); if (e.status === "registered") state.showOnAdd.add(e.layer_id); });
      await Promise.all([refreshLayers(), refreshTools()]);
      done.forEach((e) => toast(e.status === "registered" ? `Added '${e.label}' to the map.` : `${e.label}: ${e.detail}`, e.status === "registered" ? "success" : "error"));
    }
    clearTimeout(timer);
    if (busy || pending.size) timer = setTimeout(refresh, 1500);
  }
  async function add(ids) {
    for (const id of ids) {
      pending.add(id);
      try { await api.libraryAdd(id); } catch (e) { pending.delete(id); toast(e.message, "error"); }
    }
    refresh();
  }
  function draw() {
    const shown = entries.filter((e) => !q || `${e.label} ${e.group} ${e.layer_id}`.toLowerCase().includes(q));
    const groups = {};
    for (const e of shown) (groups[e.group || "Other"] ??= []).push(e);
    const nReg = entries.filter((e) => e.status === "registered").length;
    summary.textContent = `${nReg} of ${entries.length} layers added`;
    list.replaceChildren(...Object.entries(groups).map(([g, es]) => {
      const addable = es.filter((e) => e.status === "available" || e.status === "error");
      return h("section.lib-group",
        h("div.lib-ghead", h("h3", g), h("span.muted.small", `${es.filter((e) => e.status === "registered").length}/${es.length}`),
          h("button.btn.sm.push", { disabled: !addable.length, onclick: () => add(addable.map((e) => e.layer_id)) }, svgIcon("plus"), "Add all")),
        es.map((e) => {
          const fam = GEOM_FAMILY[e.geometry] || "Mixed";
          const n = e.metadata?.feature_count;
          const st = e.status;
          const action = st === "registered" ? h("span.lib-st.ok", svgIcon("check"), "Added")
            : st === "queued" || st === "importing" ? h("span.lib-st.busy", h("span.spinner"), st === "queued" ? "Queued" : "Importing…")
              : st === "missing" ? h("span.lib-st.bad", { title: "Run scripts\\import_city_layers.py" }, "Not copied")
                : h("button.btn.sm", { onclick: () => add([e.layer_id]) }, svgIcon("plus"), st === "error" ? "Retry" : "Add");
          return h("div.lib-row", { title: e.detail || e.metadata?.original_source || "" },
            symbolSvg(fam, e.display?.color || "#1769aa"),
            h("div.lib-text", h("div.lib-name", e.label),
              h("div.lib-meta", [n != null ? `${Number(n).toLocaleString()} features` : null, fmtBytes(e.bytes), e.display?.min_zoom ? `draws at zoom ${e.display.min_zoom}+` : null].filter(Boolean).join(" · "))),
            action);
        }));
    }));
  }
  // Closing the dialog keeps polling while imports are pending, so finished layers still reach the map.
  const pane = { body, foot, refresh, stop: () => { if (!pending.size) clearTimeout(timer); }, close: null };
  return pane;
}

// ------------------------------------------------------------------ Properties
export async function openProperties(layerId, tab = "general") {
  let m;
  try { m = await loadMeta(layerId, true); } catch (e) { return toast(e.message, "error"); }
  const p = m.profile;
  const tabs = { general: "General", quality: `Data quality${p.warnings.length ? ` (${p.warnings.length})` : ""}`, fields: `Fields (${p.fields.length})`, source: "Source & lineage" };
  if (m.relationships.length) tabs.relationships = `Relationships (${m.relationships.length})`;
  const content = h("div.modal-body");
  const tabBar = h("div.modal-tabs", Object.entries(tabs).map(([k, label]) => h("button", { dataset: { t: k }, onclick: () => show(k) }, label)));
  const show = (k) => {
    tabBar.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.t === k));
    content.replaceChildren(...views[k]());
  };
  const crsText = p.crs.srs ? `${p.crs.srs} — ${p.crs.name}` : "UNKNOWN";
  const views = {
    general: () => [
      h("div.cards",
        card(fmtNum(p.feature_count), "Features"),
        card(p.geometry_family, "Geometry"),
        card(p.crs.srs || "Unknown", "Coordinate system", p.crs.status === "unknown" ? "bad" : p.crs.is_geographic ? "warn" : ""),
        card(p.fields.filter((f) => !f.internal).length, "Fields"),
        card(p.invalid_geometry_count, "Invalid geometries", p.invalid_geometry_count ? "bad" : ""),
        card(p.warnings.length, "Warnings", p.warnings.length ? "warn" : "")),
      h("dl.kv",
        h("dt", "Layer ID"), h("dd", h("code", m.layer_id)),
        h("dt", "Tier"), h("dd", m.tier === "gold" ? "Gold — derived analysis result" : "Silver — normalized from an immutable Bronze copy"),
        h("dt", "Coordinate system"), h("dd", crsText),
        h("dt", "Units"), h("dd", p.crs.is_geographic ? "Degrees (geographic) — project before distance analysis" : p.crs.linear_unit || "—"),
        h("dt", "Geometry types"), h("dd", Object.entries(p.geometry_types).map(([k, v]) => `${k}: ${v}`).join(", ") || "none"),
        h("dt", "Primary key"), h("dd", h("code", p.primary_key.field), p.primary_key.field === "_hpw_fid" ? " — internal surrogate (no verified unique source key)" : ` — ${p.primary_key.source}, verified unique & non-null`),
        h("dt", "Extent"), h("dd.mono", p.extent ? p.extent.map((v) => v.toFixed(3)).join(", ") : "—"),
        h("dt", "Extent (WGS84)"), h("dd.mono", p.extent_4326 ? p.extent_4326.map((v) => v.toFixed(6)).join(", ") : "—")),
    ],
    quality: () => [
      p.warnings.length
        ? h("div.callout.warn", svgIcon("warn"), h("div", h("b", `${p.warnings.length} data-quality finding(s)`), h("ul", p.warnings.map((w) => h("li", w)))))
        : h("div.callout.ok", svgIcon("checkc"), h("div", "No data-quality issues detected.")),
      h("div.cards",
        card(p.null_geometry_count, "Null geometries", p.null_geometry_count ? "warn" : ""),
        card(p.empty_geometry_count, "Empty geometries", p.empty_geometry_count ? "warn" : ""),
        card(p.invalid_geometry_count, "Invalid geometries", p.invalid_geometry_count ? "bad" : ""),
        card(p.multipart_count, "Multipart features"),
        card(p.duplicate_geometry_count, "Duplicate geometries", p.duplicate_geometry_count ? "warn" : ""),
        card(p.duplicate_attribute_rows, "Duplicate rows", p.duplicate_attribute_rows ? "warn" : "")),
      p.invalid_examples.length ? h("table.grid", h("thead", h("tr", h("th", "FID"), h("th", "Reason"))), h("tbody", p.invalid_examples.map((x) => h("tr", h("td", String(x.fid)), h("td", x.reason))))) : null,
    ],
    fields: () => [h("table.grid", h("thead", h("tr", h("th", "Field"), h("th", "Type"), h("th.num", "Nulls"), h("th.num", "Distinct"), h("th", "Unique"))),
      h("tbody", p.fields.map((f) => h("tr", h("td", h("code", f.name), f.internal ? h("span.muted", " internal id") : null, f.name === p.primary_key.field ? h("span.badge.info", { style: { marginLeft: "6px" } }, "PK") : null),
        h("td", f.type), h("td.num", fmtNum(f.null_count)), h("td.num", f.distinct_count == null ? "—" : fmtNum(f.distinct_count)), h("td", f.unique ? h("span.badge.ok", "unique") : "")))))],
    source: () => [
      h("dl.kv",
        h("dt", "Source"), h("dd", m.source_uri),
        h("dt", "Source format"), h("dd", p.source_format || m.source_format || "geoparquet"),
        h("dt", "Source SHA-256"), h("dd.mono", p.source_sha256 || "—"),
        h("dt", "Version"), h("dd", h("code", m.version_id)),
        h("dt", "Stored as"), h("dd.mono", m.path),
        h("dt", "Bronze copy"), h("dd.mono", m.bronze_path || "— (derived)"),
        h("dt", "Version SHA-256"), h("dd.mono", m.sha256),
        h("dt", "Permissions"), h("dd", "Source read-only · analysis writes new derived layers"),
        p.lineage ? [h("dt", "Created by"), h("dd", h("code", p.lineage.tool_id), " run ", h("code", p.lineage.run_id.slice(0, 12)), " from ", p.lineage.inputs.map((i) => i.label).join(", "),
          " · ", h("a", { href: `/api/tool-runs/${p.lineage.run_id}/result`, target: "_blank", rel: "noreferrer" }, "manifest"))] : null),
      p.lineage ? h("pre.small", { style: { background: "var(--surface-2)", padding: "8px", borderRadius: "6px", marginTop: "12px" } }, JSON.stringify(p.lineage.params, null, 1)) : null,
    ],
    relationships: () => [h("table.grid", h("thead", h("tr", h("th", "Local field"), h("th", "Target"), h("th", "Cardinality"), h("th", "Status"), h("th.num", "Matched"), h("th", "Findings"))),
      h("tbody", m.relationships.map((r) => h("tr",
        h("td", h("code", r.local_field)), h("td", h("code", `${r.target_layer}.${r.target_field}`)), h("td", r.kind.replace(/_/g, "-")),
        h("td", h(`span.badge.${r.validation?.status === "valid" ? "ok" : "warn"}`, r.validation?.status || "—")),
        h("td.num", r.validation?.matched ?? "—"), h("td", { style: { whiteSpace: "normal" } }, (r.validation?.messages || []).join(" "))))))],
  };
  modal({ title: m.label, subtitle: `Layer properties · ${m.geometry_family} · ${m.tier === "gold" ? "analysis result" : "source layer"}`, iconName: "info", wide: true,
    body: h("div", tabBar, content) });
  show(tabs[tab] ? tab : "general");
}

function card(value, label, tone = "") {
  return h(`div.stat-card${tone ? "." + tone : ""}`, h("b", String(value)), h("span", label));
}

// ------------------------------------------------------------------ Projects
export async function openProjectDialog(mode) {
  let list = [];
  try { list = await api.projects(); } catch (e) { toast(e.message, "error"); }
  if (mode === "save") {
    const name = h("input", { value: state.projectName || "", maxlength: "80", placeholder: "e.g. North basin review", list: "proj-names" });
    const dl = h("datalist#proj-names", list.map((p) => h("option", { value: p.name })));
    const save = async () => {
      const n = name.value.trim();
      if (!n) return;
      const st = { order: state.order, views: state.views, basemap: state.basemap, tableLayers: state.tableLayers, ...(mapBridge.getView ? mapBridge.getView() : {}), panes: state.panes };
      try {
        await api.saveProject(n, st);
        set({ projectName: n });
        document.getElementById("project-name").textContent = n;
        dlg.close();
        toast(`Project '${n}' saved — layers, symbology, order, open tables, map view and selections.`, "success");
      } catch (e) { toast(e.message, "error"); }
    };
    const dlg = modal({ title: "Save project", iconName: "save",
      body: h("div.modal-body", h("div.form-row", h("label", "Project name"), name, dl),
        h("p.muted.small", "Saves layer order, visibility, colors, transparency, open tables, the map view and current selections.")),
      footer: h("div.modal-foot", h("button.btn", { onclick: () => dlg.close() }, "Cancel"), h("button.btn.primary", { onclick: save }, svgIcon("save"), "Save")) });
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    return;
  }
  const dlg = modal({ title: "Open project", iconName: "folder",
    body: h("div.modal-body",
      list.length ? h("ul.proj-list", list.map((p) => h("li", h("button", { onclick: () => open(p.name) }, svgIcon("folder"), h("span.pt", p.name), h("span.muted.small", p.updated_at.replace("T", " ").slice(0, 16))))))
        : h("div.contents-empty", svgIcon("folder"), h("p", "No saved projects yet.")) ) });
  async function open(n) {
    try {
      const p = await api.openProject(n);
      await refreshLayers();
      const present = new Set(state.layers.map((l) => l.layer_id));
      const st = p.state;
      const missing = (st.order || []).filter((id) => !present.has(id));
      set({
        order: [...st.order.filter((id) => present.has(id)), ...state.order.filter((id) => !st.order.includes(id))],
        views: { ...state.views, ...Object.fromEntries(Object.entries(st.views || {}).filter(([k]) => present.has(k))) },
        basemap: st.basemap || "streets",
        tableLayers: (st.tableLayers || []).filter((id) => present.has(id)),
        activeTable: (st.tableLayers || []).filter((id) => present.has(id))[0] ?? null,
        projectName: n,
      });
      if (st.center && st.zoom) mapBridge.jumpTo({ center: st.center, zoom: st.zoom });
      await refreshSelection();
      document.getElementById("project-name").textContent = n;
      dlg.close();
      toast(`Opened '${n}'.${missing.length ? ` Skipped missing layers: ${missing.join(", ")}` : ""}`, missing.length ? "warning" : "success");
    } catch (e) { toast(e.message, "error"); }
  }
}
