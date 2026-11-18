// MapLibre map: viewport loading, layer styling, selection highlight, identify, box select, basemaps, legend.
/* global maplibregl */
import { api } from "./api.js";
import {
  SELECTION_COLOR, drawable, layerById, mapBridge, on, openTable, refreshSelection, select, set, state, zoomToSelection,
} from "./state.js";
import { $, h, svgIcon, symbolSvg, toast } from "./ui.js";

const FID = "_hpw_fid";
const sid = (id) => `src:${id}`;
let map;
let ready = false;
const appliedSel = {};
const loadSeq = {};
const truncated = {};
const belowMinZoom = {};
const appliedWhere = {};
let popup = null;

export const BASEMAPS = {
  streets: { label: "Streets", raster: { "raster-saturation": -0.25, "raster-opacity": 1 } },
  light: { label: "Light gray", raster: { "raster-saturation": -1, "raster-brightness-min": 0.35, "raster-contrast": -0.25, "raster-opacity": 1 } },
  dark: { label: "Dark gray", raster: { "raster-saturation": -1, "raster-brightness-min": 0.88, "raster-brightness-max": 0.06, "raster-contrast": 0.1, "raster-opacity": 1 } },
  none: { label: "None", raster: null },
};

function styleIds(l) {
  const id = l.layer_id;
  if (l.geometry_family === "Polygon") return [`hpw:${id}:fill`, `hpw:${id}:outline`];
  if (l.geometry_family === "Line") return [`hpw:${id}:casing`, `hpw:${id}:line`];
  if (l.geometry_family === "Point") return [`hpw:${id}:circle`];
  return [`hpw:${id}:fill`, `hpw:${id}:outline`, `hpw:${id}:line`, `hpw:${id}:circle`];
}
const SEL = ["boolean", ["feature-state", "selected"], false];

export function initMap() {
  map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
        },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": "#e9edf1" } },
        { id: "osm", type: "raster", source: "osm", paint: {} },
      ],
    },
    center: [-95.3635, 29.7595],
    zoom: 15,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial", maxWidth: 120 }), "bottom-left");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 120 }), "bottom-left");

  mapBridge.zoomTo = (b) => {
    if (!b || b.some((v) => !Number.isFinite(v))) return;
    if (b[0] === b[2] && b[1] === b[3]) map.flyTo({ center: [b[0], b[1]], zoom: Math.max(map.getZoom(), 18) });
    else map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 70, maxZoom: 19, duration: 650 });
  };
  mapBridge.zoomBy = (d) => map.easeTo({ zoom: map.getZoom() + d, duration: 250 });
  mapBridge.tilt = () => map.easeTo({ pitch: map.getPitch() > 5 ? 0 : 60, duration: 600 });
  mapBridge.resetNorth = () => map.easeTo({ bearing: 0, pitch: 0, duration: 600 });
  mapBridge.jumpTo = (v) => map.jumpTo(v);
  mapBridge.getView = () => ({ center: map.getCenter().toArray(), zoom: map.getZoom() });

  map.on("load", () => {
    ready = true;
    applyBasemap();
    syncLayers();
    reloadAll();
  });
  map.on("mousemove", (e) => {
    $("#sb-coords").textContent = `${e.lngLat.lat.toFixed(6)}°, ${e.lngLat.lng.toFixed(6)}°  WGS84`;
    if (state.mapMode !== "identify") return;
    const n = queryAt(e.point, 3).length;
    map.getCanvas().style.cursor = n ? "pointer" : "";
  });
  let t;
  map.on("moveend", () => {
    updateScale();
    set({ viewState: mapBridge.getView() });
    clearTimeout(t);
    t = setTimeout(reloadAll, 180);
  });
  map.on("click", onClick);
  initBoxSelect();
  updateScale();

  on(["layers", "views", "order"], () => { syncLayers(); renderLegend(); });
  on("selection", applySelection);
  on("basemap", applyBasemap);
  on("mapMode", applyMode);
  on("buildings3d", applyBuildings);
  map.on("pitchend", () => set({ pitched: map.getPitch() > 5 }));
  map.on("error", (e) => {
    if (e.sourceId === BLD_SRC && !bldWarned) {
      bldWarned = true;
      toast("3D buildings need an internet connection (OpenFreeMap tiles could not be loaded).", "warning");
    }
  });
  renderLegend();
}

// ------------------------------------------------------------------ 3D buildings
// OpenStreetMap building footprints with heights (render_height / render_min_height, OpenMapTiles schema),
// served as vector tiles by OpenFreeMap. Loaded only when the user turns 3D buildings on.
const BLD_SRC = "openfreemap";
const BLD_LAYER = "3d-buildings";
let bldWarned = false;

function applyBuildings() {
  if (!ready) return;
  const on3d = !!state.buildings3d;
  if (on3d && !map.getSource(BLD_SRC)) {
    map.addSource(BLD_SRC, { type: "vector", url: "https://tiles.openfreemap.org/planet", attribution: '<a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">OpenMapTiles</a>' });
  }
  if (on3d && !map.getLayer(BLD_LAYER)) {
    const before = (map.getStyle().layers || []).find((l) => l.id.startsWith("hpw:"))?.id;
    map.addLayer({
      id: BLD_LAYER, type: "fill-extrusion", source: BLD_SRC, "source-layer": "building", minzoom: 14,
      filter: ["!=", ["get", "hide_3d"], true],
      paint: {
        "fill-extrusion-color": ["interpolate", ["linear"], ["coalesce", ["get", "render_height"], 0], 0, "#d7dee6", 30, "#b9c6d4", 120, "#8ea3ba"],
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 14, 0, 15, ["coalesce", ["get", "render_height"], 0]],
        "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
        "fill-extrusion-opacity": 0.82,
        "fill-extrusion-vertical-gradient": true,
      },
    }, before);
  }
  if (map.getLayer(BLD_LAYER)) map.setLayoutProperty(BLD_LAYER, "visibility", on3d ? "visible" : "none");
  if (on3d) {
    const target = { pitch: Math.max(map.getPitch(), 55), duration: 800 };
    if (map.getZoom() < 15) target.zoom = 16;
    map.easeTo(target);
  }
}

function updateScale() {
  const lat = map.getCenter().lat;
  const mpp = (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** map.getZoom());
  const scale = mpp / 0.0002645833; // 96 dpi
  const nice = scale > 10000 ? Math.round(scale / 1000) * 1000 : scale > 1000 ? Math.round(scale / 100) * 100 : Math.round(scale / 10) * 10;
  $("#sb-scale").textContent = `1 : ${nice.toLocaleString()}`;
}

function applyBasemap() {
  if (!ready) return;
  const bm = BASEMAPS[state.basemap] || BASEMAPS.streets;
  map.setLayoutProperty("osm", "visibility", bm.raster ? "visible" : "none");
  const defaults = { "raster-saturation": 0, "raster-brightness-min": 0, "raster-brightness-max": 1, "raster-contrast": 0, "raster-opacity": 1 };
  for (const [k, v] of Object.entries({ ...defaults, ...(bm.raster || {}) })) map.setPaintProperty("osm", k, v);
  const dark = document.documentElement.dataset.theme === "dark";
  map.setPaintProperty("bg", "background-color", state.basemap === "dark" || (state.basemap === "none" && dark) ? "#1b222c" : "#e9edf1");
}
export const refreshBasemap = applyBasemap;

function applyMode() {
  if (!ready) return;
  const sel = state.mapMode === "select";
  sel ? map.dragPan.disable() : map.dragPan.enable();
  sel ? map.boxZoom.disable() : map.boxZoom.enable();
  map.getCanvas().style.cursor = sel ? "crosshair" : "";
  $("#map-hint").hidden = !sel;
}

// ------------------------------------------------------------------ layers
function syncLayers() {
  if (!ready) return;
  const present = new Set(state.layers.map((l) => l.layer_id));
  for (const lyr of map.getStyle().layers || []) {
    const m = lyr.id.match(/^hpw:(.+):\w+$/);
    if (m && !present.has(m[1])) map.removeLayer(lyr.id);
  }
  for (const key of Object.keys(map.getStyle().sources || {})) if (key.startsWith("src:") && !present.has(key.slice(4))) map.removeSource(key);

  const toLoad = [];
  for (const l of state.layers) {
    if (!drawable(l)) continue;
    const v = state.views[l.layer_id];
    if (!v) continue;
    const src = sid(l.layer_id);
    if (!map.getSource(src)) {
      map.addSource(src, { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: FID });
      const mixed = l.geometry_family === "Mixed";
      const only = (types) => (mixed ? { filter: ["match", ["geometry-type"], types, true, false] } : {});
      for (const id of styleIds(l)) {
        const kind = id.split(":").pop();
        if (kind === "fill") map.addLayer({ id, type: "fill", source: src, ...only(["Polygon", "MultiPolygon"]) });
        if (kind === "outline") map.addLayer({ id, type: "line", source: src, ...only(["Polygon", "MultiPolygon"]), layout: { "line-join": "round" } });
        if (kind === "casing") map.addLayer({ id, type: "line", source: src, layout: { "line-cap": "round", "line-join": "round" } });
        if (kind === "line") map.addLayer({ id, type: "line", source: src, ...only(["LineString", "MultiLineString"]), layout: { "line-cap": "round", "line-join": "round" } });
        if (kind === "circle") map.addLayer({ id, type: "circle", source: src, ...only(["Point", "MultiPoint"]) });
      }
      if (v.visible) toLoad.push(l);
    }
    for (const id of styleIds(l)) {
      if (!map.getLayer(id)) continue;
      const wasHidden = map.getLayoutProperty(id, "visibility") === "none";
      map.setLayoutProperty(id, "visibility", v.visible ? "visible" : "none");
      if (wasHidden && v.visible && !toLoad.includes(l)) toLoad.push(l);
      paint(id, v);
    }
    if (v.visible && (v.where || "") !== (appliedWhere[l.layer_id] ?? "") && !toLoad.includes(l)) toLoad.push(l);
  }
  for (const id of [...state.order].reverse()) {
    const l = layerById(id);
    if (!drawable(l)) continue;
    for (const s of styleIds(l)) if (map.getLayer(s)) map.moveLayer(s);
  }
  toLoad.forEach(loadLayer);
}

// Unique-value renderer: v.renderer = {field, classes: [{value, color, label}], fallback}
function colorExpr(v) {
  const r = v.renderer;
  if (!r?.classes?.length) return v.color;
  return ["match", ["to-string", ["get", r.field]], ...r.classes.flatMap((c) => [String(c.value), c.color]), r.fallback || v.color];
}

function paint(id, v) {
  const kind = id.split(":").pop();
  const pp = (k, val) => map.setPaintProperty(id, k, val);
  const col = colorExpr(v);
  const thematic = !!v.renderer;
  if (kind === "fill") {
    pp("fill-color", ["case", SEL, SELECTION_COLOR, col]);
    pp("fill-opacity", ["case", SEL, 0.45, (thematic ? 0.78 : 0.28) * v.opacity]);
  } else if (kind === "outline") {
    pp("line-color", ["case", SEL, "#00acc1", thematic ? "rgba(15,42,67,0.35)" : v.color]);
    pp("line-width", ["case", SEL, 3.2, thematic ? 0.6 : 1.6]);
    pp("line-opacity", v.opacity);
  } else if (kind === "casing") {
    pp("line-color", ["case", SEL, "#006978", "#ffffff"]);
    pp("line-width", ["case", SEL, 8, 5.5]);
    pp("line-opacity", ["case", SEL, 0.9, 0.85 * v.opacity]);
  } else if (kind === "line") {
    pp("line-color", ["case", SEL, SELECTION_COLOR, col]);
    pp("line-width", ["case", SEL, 4.5, 3]);
    pp("line-opacity", v.opacity);
  } else if (kind === "circle") {
    pp("circle-color", ["case", SEL, SELECTION_COLOR, col]);
    pp("circle-radius", ["interpolate", ["linear"], ["zoom"], 12, ["case", SEL, 5, 3.5], 17, ["case", SEL, 9, 6.5]]);
    pp("circle-stroke-color", ["case", SEL, "#00525c", "#ffffff"]);
    pp("circle-stroke-width", ["case", SEL, 2.4, 1.6]);
    pp("circle-opacity", v.opacity);
    pp("circle-stroke-opacity", v.opacity);
  }
}

async function loadLayer(l) {
  if (!ready) return;
  const seq = (loadSeq[l.layer_id] || 0) + 1;
  loadSeq[l.layer_id] = seq;
  const v = state.views[l.layer_id] || {};
  appliedWhere[l.layer_id] = v.where || "";
  const src0 = map.getSource(sid(l.layer_id));
  const minZoom = Number(l.display?.min_zoom) || 0;
  if (map.getZoom() < minZoom - 0.01) { // dense network / parcel layers: like the library, draw only when zoomed in
    src0?.setData({ type: "FeatureCollection", features: [] });
    belowMinZoom[l.layer_id] = minZoom;
    truncated[l.layer_id] = 0;
    renderTruncation();
    return;
  }
  delete belowMinZoom[l.layer_id];
  const b = map.getBounds();
  const w = b.getEast() - b.getWest(), hgt = b.getNorth() - b.getSouth();
  const bbox = [b.getWest() - w * 0.25, b.getSouth() - hgt * 0.25, b.getEast() + w * 0.25, b.getNorth() + hgt * 0.25];
  try {
    const fc = await api.features(l.layer_id, bbox, v.where);
    if (loadSeq[l.layer_id] !== seq) return;
    const src = map.getSource(sid(l.layer_id));
    if (!src) return;
    src.setData(fc);
    truncated[l.layer_id] = fc.truncated ? fc.total_in_bbox : 0;
    renderTruncation();
    const sel = new Set(state.selection[l.layer_id] || []);
    for (const f of fc.features) map.setFeatureState({ source: sid(l.layer_id), id: Number(f.id) }, { selected: sel.has(Number(f.id)) });
    appliedSel[l.layer_id] = sel;
  } catch (e) {
    toast(`${l.label}: ${e.message}`, "warning");
  }
}

export function reloadAll() {
  if (!ready) return;
  state.layers.filter((l) => drawable(l) && state.views[l.layer_id]?.visible).forEach(loadLayer);
}

function renderTruncation() {
  const vis = (id) => state.views[id]?.visible;
  const t = Object.entries(truncated).filter(([id, n]) => n > 0 && vis(id));
  const z = Object.entries(belowMinZoom).filter(([id]) => vis(id));
  const parts = [];
  if (t.length) parts.push(`⚠ Drawing capped for ${t.map(([id]) => layerById(id)?.label || id).join(", ")} — zoom in`);
  if (z.length) parts.push(`Zoom in to see ${z.map(([id, mz]) => `${layerById(id)?.label || id} (level ${mz}+)`).join(", ")}`);
  $("#sb-warn").textContent = parts.join(" · ");
}

function applySelection() {
  if (!ready) return;
  for (const l of state.layers) {
    if (!drawable(l) || !map.getSource(sid(l.layer_id))) continue;
    const next = new Set(state.selection[l.layer_id] || []);
    const prev = appliedSel[l.layer_id] || new Set();
    for (const id of prev) if (!next.has(id)) map.setFeatureState({ source: sid(l.layer_id), id }, { selected: false });
    for (const id of next) if (!prev.has(id)) map.setFeatureState({ source: sid(l.layer_id), id }, { selected: true });
    appliedSel[l.layer_id] = next;
  }
}

// ------------------------------------------------------------------ identify
function ourVisibleLayerIds() {
  return (map.getStyle().layers || []).map((l) => l.id).filter((id) => id.startsWith("hpw:") && !id.endsWith(":casing") && map.getLayoutProperty(id, "visibility") !== "none");
}
function queryAt(p, r) {
  return map.queryRenderedFeatures([[p.x - r, p.y - r], [p.x + r, p.y + r]], { layers: ourVisibleLayerIds() });
}

function onClick(e) {
  if (state.mapMode !== "identify") return;
  const feats = queryAt(e.point, 5);
  popup?.remove();
  if (!feats.length) return;
  // de-duplicate (fill + outline of same feature)
  const seen = new Set();
  const uniq = feats.filter((f) => { const k = `${f.source}|${f.id}`; if (seen.has(k)) return false; seen.add(k); return true; });
  showPopup(e, uniq, 0);
}

function showPopup(e, feats, idx) {
  const f = feats[idx];
  const layerId = f.source.slice(4);
  const fid = Number(f.id);
  const l = layerById(layerId);
  const ev = e.originalEvent;
  if (idx === 0 && ev) {
    const isSel = (state.selection[layerId] || []).includes(fid);
    const mode = ev.ctrlKey || ev.metaKey ? (isSel ? "remove" : "add") : ev.shiftKey ? "add" : "new";
    select(layerId, [fid], mode);
    if (mode === "new") for (const other of Object.keys(state.selection)) if (other !== layerId && state.selection[other]?.length) select(other, [], "clear");
  }
  const props = Object.entries(f.properties || {}).filter(([k]) => k !== FID);
  const pk = l?.primary_key;
  const title = pk && f.properties?.[pk] != null && pk !== FID ? String(f.properties[pk]) : `Feature ${fid}`;
  const body = h("div.pop",
    h("div.pop-head",
      h("div.t", title),
      h("div.s", `${l?.label ?? layerId} · ${l?.geometry_family ?? ""} · FID ${fid}`)),
    h("div.pop-body", h("table", props.map(([k, v]) =>
      h("tr", h("th", k), h("td", v === null || v === undefined || v === "null" ? h("span.null", "<Null>") : String(v)))))),
    h("div.pop-foot",
      h("button.btn.sm", { onclick: () => { openTable(layerId); } }, svgIcon("table"), "Table"),
      h("button.btn.sm", { onclick: () => zoomToSelection(layerId) }, svgIcon("zoomsel"), "Zoom"),
      feats.length > 1 ? h("button.btn.sm.ghost", { onclick: () => showPopup({ lngLat: popup.getLngLat() }, feats, (idx + 1) % feats.length) }, `Next (${idx + 1}/${feats.length})`) : null,
      h("span.muted", "Shift add · Ctrl toggle")));
  popup?.remove();
  popup = new maplibregl.Popup({ maxWidth: "320px", closeOnClick: true, offset: 8 }).setLngLat(e.lngLat).setDOMContent(body).addTo(map);
  set({ activeLayer: layerId });
}

// ------------------------------------------------------------------ box select
function initBoxSelect() {
  const wrap = $(".map-wrap");
  const boxEl = $("#select-box");
  let start = null;
  const pos = (e) => { const r = wrap.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  wrap.addEventListener("mousedown", (e) => {
    if (state.mapMode !== "select" || e.button !== 0 || e.target.closest(".maplibregl-ctrl, .map-legend")) return;
    start = pos(e);
    Object.assign(boxEl.style, { left: `${start.x}px`, top: `${start.y}px`, width: "0px", height: "0px" });
    boxEl.hidden = false;
  });
  window.addEventListener("mousemove", (e) => {
    if (!start) return;
    const p = pos(e);
    Object.assign(boxEl.style, { left: `${Math.min(p.x, start.x)}px`, top: `${Math.min(p.y, start.y)}px`, width: `${Math.abs(p.x - start.x)}px`, height: `${Math.abs(p.y - start.y)}px` });
  });
  window.addEventListener("mouseup", async (e) => {
    if (!start) return;
    const p = pos(e);
    const s = start;
    start = null;
    boxEl.hidden = true;
    const pad = Math.abs(p.x - s.x) < 4 && Math.abs(p.y - s.y) < 4 ? 5 : 0;
    const a = map.unproject([Math.min(p.x, s.x) - pad, Math.max(p.y, s.y) + pad]);
    const c = map.unproject([Math.max(p.x, s.x) + pad, Math.min(p.y, s.y) - pad]);
    const geom = { type: "Polygon", coordinates: [[[a.lng, a.lat], [c.lng, a.lat], [c.lng, c.lat], [a.lng, c.lat], [a.lng, a.lat]]] };
    const mode = e.shiftKey ? "add" : e.ctrlKey || e.metaKey ? "remove" : "new";
    const targets = state.layers.filter((l) => drawable(l) && state.views[l.layer_id]?.visible);
    let total = 0;
    await Promise.all(targets.map(async (l) => {
      try { total += (await api.selectByGeometry(l.layer_id, geom, mode)).fids.length; } catch (err) { toast(`${l.label}: ${err.message}`, "error"); }
    }));
    await refreshSelection();
    toast(`${total.toLocaleString()} feature(s) selected in ${targets.length} visible layer(s).`, total ? "success" : "info");
  });
}

// ------------------------------------------------------------------ legend
function renderLegend() {
  const el = $("#map-legend");
  const vis = state.order.map(layerById).filter((l) => l && drawable(l) && state.views[l.layer_id]?.visible);
  el.hidden = !vis.length;
  el.replaceChildren(
    h("h4", "Legend", h("button.icon-btn", { style: { width: "20px", height: "20px" }, "aria-label": "Collapse legend", onclick: () => el.classList.toggle("collapsed") }, svgIcon("chev"))),
    ...vis.flatMap((l) => {
      const v = state.views[l.layer_id];
      if (!v.renderer?.classes?.length) return [h("div.lg", symbolSvg(l.geometry_family, v.color), h("span", l.label))];
      const shown = v.renderer.classes.filter((c) => !v.renderer.legendOnly || v.renderer.legendOnly.includes(String(c.value)));
      return [h("div.lg.lg-head", h("span", l.label), v.renderer.caption ? h("span.muted", v.renderer.caption) : null),
        ...shown.map((c) => h("div.lg.lg-class", h("i.sw", { style: { background: c.color } }), h("span", c.label)))];
    }),
  );
}
