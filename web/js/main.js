// Entry point: wires ribbon, panes, splitters, theme, global search, keyboard shortcuts.
import { api } from "./api.js";
import { initContents } from "./contents.js";
import { openAddData, openProjectDialog, openProperties } from "./dialogs.js";
import { initGeoprocessing } from "./geoprocessing.js";
import { BASEMAPS, initMap, refreshBasemap } from "./map.js";
import {
  clearAllSelections, layerById, mapBridge, on, openTable, openTool, refreshLayers, refreshSelection, refreshTools, set, state,
  unionBox, loadMeta, drawable, zoomToLayer, zoomToSelection,
} from "./state.js";
import { initSpaceTime } from "./spacetime.js";
import { initTable } from "./table.js";
import { $, $$, h, hydrateIcons, svgIcon, symbolSvg, toast, toolIcon } from "./ui.js";

if (location.protocol !== "file:") boot();

async function boot() {
  hydrateIcons();
  addCrsPresets();
  initRibbon();
  initPanes();
  initTheme();
  initSearch();
  initStatus();
  initMap();
  initContents();
  initTable();
  initGeoprocessing();
  initSpaceTime();
  initShortcuts();
  try {
    const [layers] = await Promise.all([refreshLayers(), refreshTools(), refreshSelection()]);
    const first = layers.find((l) => l.geometry_family === "Line") || layers[0];
    if (first) openTable(first.layer_id);
    fullExtent();
    pingEngine();
  } catch (e) {
    setEngine("bad", "Engine offline");
    toast(`Cannot reach the GIS engine (${e.message}). Start it with scripts\\run.ps1`, "error");
  }
}

// ------------------------------------------------------------------ ribbon
function initRibbon() {
  $$(".rtab").forEach((t) => t.addEventListener("click", () => {
    $$(".rtab").forEach((x) => x.classList.toggle("active", x === t));
    $$(".rpanel").forEach((p) => p.classList.toggle("active", p.dataset.panel === t.dataset.tab));
  }));
  $$(".rbtn.mode").forEach((b) => b.addEventListener("click", () => set({ mapMode: b.dataset.mode })));
  on("mapMode", () => $$(".rbtn.mode").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mapMode))));

  const actions = {
    "clear-selection": clearAllSelections,
    "zoom-selection": () => zoomToSelection(),
    "full-extent": fullExtent,
    "zoom-in": () => mapBridge.zoomBy(1),
    "zoom-out": () => mapBridge.zoomBy(-1),
    "add-data": openAddData,
    "show-tools": () => { set({ activeToolId: null, gpTab: "tools", panes: { ...state.panes, right: true } }); },
    "show-history": () => set({ gpTab: "history", panes: { ...state.panes, right: true } }),
    "open-table": () => (state.activeLayer ? openTable(state.activeLayer) : toast("Select a layer in Contents first.", "warning")),
    "layer-props": () => (state.activeLayer ? openProperties(state.activeLayer) : toast("Select a layer in Contents first.", "warning")),
    "buildings-3d": () => set({ buildings3d: !state.buildings3d }),
    tilt: () => mapBridge.tilt(),
    north: () => mapBridge.resetNorth(),
    "st-dashboard": () => set({ gpTab: "spacetime", panes: { ...state.panes, right: true } }),
    "open-project": () => openProjectDialog("open"),
    "save-project": () => openProjectDialog("save"),
    theme: toggleTheme,
  };
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (el && actions[el.dataset.action]) actions[el.dataset.action]();
    const tool = e.target.closest(".ribbon [data-tool]");
    if (tool) openTool(tool.dataset.tool);
  });
  on("buildings3d", () => $$('[data-action="buildings-3d"]').forEach((b) => b.setAttribute("aria-pressed", String(!!state.buildings3d))));
  on("pitched", () => $$('[data-action="tilt"]').forEach((b) => b.setAttribute("aria-pressed", String(!!state.pitched))));

  // basemap gallery
  const gal = $("#basemap-gallery");
  const drawGallery = () => gal.replaceChildren(...Object.entries(BASEMAPS).map(([k, b]) =>
    h("button.bm", { "aria-pressed": String(state.basemap === k), title: k === "none" ? "No basemap (offline)" : `${b.label} (OpenStreetMap, online)`, onclick: () => set({ basemap: k }) },
      h(`span.thumb.${k}`), b.label)));
  on("basemap", drawGallery);
  drawGallery();

  // analysis ribbon tools from registry
  on("tools", () => $("#ribbon-tools").replaceChildren(...state.tools.map((t) =>
    h("button.rbtn.big.tool-rbtn", { title: t.summary, onclick: () => openTool(t.id) }, svgIcon(toolIcon(t.id)), h("span", t.name.replace("Select Layer By ", "Select by "))))));

  // selection counter
  on("selection", () => {
    const n = Object.values(state.selection).reduce((a, b) => a + b.length, 0);
    $("#sel-total").textContent = n.toLocaleString();
    const parts = Object.entries(state.selection).filter(([, f]) => f.length).map(([id, f]) => `${layerById(id)?.label || id}: ${f.length}`);
    $("#sb-selection").textContent = n ? `Selected ${n.toLocaleString()} — ${parts.join(" · ")}` : "No selection";
  });
}

async function fullExtent() {
  const ids = state.layers.filter((l) => drawable(l) && state.views[l.layer_id]?.visible).map((l) => l.layer_id);
  if (!ids.length) return;
  const metas = await Promise.all(ids.map((id) => loadMeta(id).catch(() => null)));
  const boxes = metas.map((m) => m?.profile?.extent_4326).filter(Boolean);
  if (boxes.length) mapBridge.zoomTo(unionBox(boxes));
}

// ------------------------------------------------------------------ panes & splitters
function initPanes() {
  const ws = $("#workspace");
  const apply = () => {
    ws.classList.toggle("no-left", !state.panes.left);
    ws.classList.toggle("no-right", !state.panes.right);
    $$(".rbtn.toggle").forEach((b) => b.setAttribute("aria-pressed", String(!!state.panes[b.dataset.pane])));
    window.dispatchEvent(new Event("resize"));
  };
  on("panes", apply);
  $$(".rbtn.toggle").forEach((b) => b.addEventListener("click", () => set({ panes: { ...state.panes, [b.dataset.pane]: !state.panes[b.dataset.pane] } })));
  $$("[data-pane-close]").forEach((b) => b.addEventListener("click", () => set({ panes: { ...state.panes, [b.dataset.paneClose]: false } })));
  try {
    const saved = JSON.parse(localStorage.getItem("hpw-sizes") || "{}");
    for (const [k, v] of Object.entries(saved)) document.documentElement.style.setProperty(k, v);
  } catch { /* storage unavailable */ }

  $$(".splitter").forEach((sp) => sp.addEventListener("mousedown", (e) => {
    e.preventDefault();
    sp.classList.add("drag");
    const kind = sp.dataset.split;
    const startX = e.clientX, startY = e.clientY;
    const root = document.documentElement.style;
    const cs = getComputedStyle(document.documentElement);
    const startLeft = parseInt(cs.getPropertyValue("--left-w")), startRight = parseInt(cs.getPropertyValue("--right-w"));
    const startTable = $("#pane-bottom").getBoundingClientRect().height;
    const move = (ev) => {
      if (kind === "left") root.setProperty("--left-w", `${Math.max(200, Math.min(520, startLeft + ev.clientX - startX))}px`);
      if (kind === "right") root.setProperty("--right-w", `${Math.max(280, Math.min(640, startRight - (ev.clientX - startX)))}px`);
      if (kind === "bottom") root.setProperty("--table-h", `${Math.max(120, Math.min(window.innerHeight * 0.7, startTable - (ev.clientY - startY)))}px`);
      window.dispatchEvent(new Event("resize"));
    };
    const up = () => {
      sp.classList.remove("drag");
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      try {
        localStorage.setItem("hpw-sizes", JSON.stringify(Object.fromEntries(["--left-w", "--right-w", "--table-h"].map((k) => [k, root.getPropertyValue(k)]).filter(([, v]) => v))));
      } catch { /* ignore */ }
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }));
}

// ------------------------------------------------------------------ theme
function initTheme() {
  $("#theme-toggle").addEventListener("click", toggleTheme);
  paintThemeIcon();
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("hpw-theme", next); } catch { /* ignore */ }
  if (next === "dark" && state.basemap === "streets") set({ basemap: "dark" });
  else if (next === "light" && state.basemap === "dark") set({ basemap: "streets" });
  else refreshBasemap();
  paintThemeIcon();
}
function paintThemeIcon() {
  $("#theme-toggle").replaceChildren(svgIcon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon"));
}

// ------------------------------------------------------------------ global search
function initSearch() {
  const input = $("#global-search");
  const box = $("#search-results");
  let hl = 0;
  const results = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) return [];
    const ls = state.layers.filter((l) => l.label.toLowerCase().includes(q) || l.layer_id.includes(q)).slice(0, 6)
      .map((l) => ({ kind: "Layers", label: l.label, sub: `${l.feature_count} · ${l.crs?.srs || "CRS unknown"}`, icon: symbolSvg(l.geometry_family, state.views[l.layer_id]?.color || "#888"), go: () => { openTable(l.layer_id); if (drawable(l)) zoomToLayer(l.layer_id); } }));
    const ts = state.tools.filter((t) => `${t.name} ${t.summary} ${t.category}`.toLowerCase().includes(q)).slice(0, 6)
      .map((t) => ({ kind: "Tools", label: t.name, sub: t.summary, icon: svgIcon(toolIcon(t.id)), go: () => openTool(t.id) }));
    return [...ls, ...ts];
  };
  const draw = () => {
    const rs = results();
    box.hidden = !input.value.trim();
    if (box.hidden) return;
    hl = Math.min(hl, Math.max(0, rs.length - 1));
    let last = null;
    box.replaceChildren(...(rs.length ? rs.flatMap((r, i) => {
      const out = [];
      if (r.kind !== last) out.push(h("div.sr-head", r.kind));
      last = r.kind;
      out.push(h(`button${i === hl ? ".hl" : ""}`, { onmousedown: (e) => { e.preventDefault(); pickR(r); } }, r.icon, h("span", h("div", r.label), h("div.small.muted", r.sub))));
      return out;
    }) : [h("div.sr-head", "No matches")]));
    box._rs = rs;
  };
  const pickR = (r) => { r.go(); input.value = ""; draw(); input.blur(); };
  input.addEventListener("input", () => { hl = 0; draw(); });
  input.addEventListener("blur", () => setTimeout(() => { box.hidden = true; }, 120));
  input.addEventListener("focus", draw);
  input.addEventListener("keydown", (e) => {
    const rs = box._rs || [];
    if (e.key === "ArrowDown") { hl = Math.min(rs.length - 1, hl + 1); draw(); e.preventDefault(); }
    if (e.key === "ArrowUp") { hl = Math.max(0, hl - 1); draw(); e.preventDefault(); }
    if (e.key === "Enter" && rs[hl]) pickR(rs[hl]);
    if (e.key === "Escape") { input.value = ""; draw(); input.blur(); }
  });
}

// ------------------------------------------------------------------ status
function setEngine(cls, text) {
  const el = $("#engine-status");
  el.className = `engine-status ${cls}`;
  el.querySelector("b").textContent = text;
}
async function pingEngine() {
  try {
    const hl = await api.health();
    setEngine("ok", `Engine ready · ${hl.layers} layers · ${hl.tools} tools`);
  } catch {
    setEngine("bad", "Engine offline");
  }
}
function initStatus() {
  on("jobsRunning", () => {
    const n = state.jobsRunning;
    $("#sb-job").replaceChildren(...(n ? [h("span.spinner"), `${n} tool run${n > 1 ? "s" : ""} in progress`] : []));
  });
  on("layers", pingEngine);
  setInterval(pingEngine, 30000);
}

// ------------------------------------------------------------------ shortcuts
function initShortcuts() {
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
    if (e.key === "Escape" && !document.querySelector(".modal-backdrop")) set({ mapMode: "identify" });
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#global-search").focus(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); openProjectDialog("save"); }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "s") set({ mapMode: "select" });
    if (e.key === "e") set({ mapMode: "identify" });
  });
}

function addCrsPresets() {
  document.body.appendChild(h("datalist#crs-presets",
    h("option", { value: "EPSG:2278" }, "NAD83 / Texas South Central (ftUS)"),
    h("option", { value: "EPSG:6588" }, "NAD83(2011) / Texas South Central (ftUS)"),
    h("option", { value: "EPSG:32615" }, "WGS 84 / UTM zone 15N"),
    h("option", { value: "EPSG:4326" }, "WGS 84 (lon/lat degrees)"),
    h("option", { value: "EPSG:3857" }, "Web Mercator")));
}
