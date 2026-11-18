// Tiny observable store + shared actions. Components subscribe to keys with on("key", fn).
import { api } from "./api.js";
import { toast } from "./ui.js";

// Qualitative palette for layer identity only (never implies severity). Selection uses cyan.
export const PALETTE = ["#1a73e8", "#188038", "#8e44ad", "#c0392b", "#d35400", "#00897b", "#b7950b", "#5d6d7e", "#ad1457", "#6d4c41", "#3949ab", "#7cb342"];
export const SELECTION_COLOR = "#00d4f0";

export const state = {
  layers: [],
  views: {}, // layer_id -> {visible, color, opacity}
  order: [], // top-most first
  selection: {}, // layer_id -> fids
  meta: {}, // layer_id -> full metadata
  tools: [],
  tableLayers: [],
  activeTable: null,
  activeLayer: null, // highlighted in Contents
  mapMode: "identify",
  basemap: "streets",
  activeToolId: null,
  toolPreset: null,
  gpTab: "tools",
  runsVersion: 0,
  viewState: null,
  projectName: null,
  panes: { left: true, right: true, bottom: true },
  collapsedGroups: {},
  jobsRunning: 0,
  showOnAdd: new Set(), // library layers added this session -> visible on first appearance
  spacetime: null, // active space-time analysis (see spacetime.js)
  buildings3d: false, // OpenFreeMap vector buildings extruded by OSM height (online)
  pitched: false,
};

const subs = new Map();
export function on(keys, fn) {
  for (const k of [].concat(keys)) {
    if (!subs.has(k)) subs.set(k, new Set());
    subs.get(k).add(fn);
  }
}
export function set(patch) {
  Object.assign(state, patch);
  const fns = new Set();
  for (const k of Object.keys(patch)) for (const f of subs.get(k) || []) fns.add(f);
  fns.forEach((f) => f(state));
}

// --------------------------------------------------------------------------- actions
export async function refreshLayers() {
  const layers = await api.layers();
  const views = { ...state.views };
  let order = state.order.filter((id) => layers.some((l) => l.layer_id === id));
  const firstLoad = state.order.length === 0;
  layers.forEach((l, i) => {
    // Library reference layers start hidden (availability is not visibility) unless just added by the user.
    if (!views[l.layer_id]) {
      const fresh = state.showOnAdd.has(l.layer_id);
      views[l.layer_id] = {
        visible: l.crs?.status === "known" && (!l.collection || fresh),
        color: l.display?.color || PALETTE[i % PALETTE.length],
        opacity: 0.9,
      };
    }
    if (!order.includes(l.layer_id)) order = [l.layer_id, ...order];
  });
  if (firstLoad) {
    const rank = { Point: 0, Line: 1, Mixed: 1, Polygon: 2, Table: 3, Other: 3 };
    const fam = (id) => layers.find((l) => l.layer_id === id).geometry_family;
    order.sort((a, b) => rank[fam(a)] - rank[fam(b)]);
  }
  const meta = { ...state.meta };
  for (const l of layers) if (meta[l.layer_id] && meta[l.layer_id].version_id !== l.version_id) delete meta[l.layer_id];
  set({ layers, views, order, meta });
  return layers;
}

export async function refreshTools() {
  set({ tools: await api.tools() });
}

export async function refreshSelection() {
  set({ selection: await api.selection() });
}

export async function loadMeta(id, force = false) {
  if (state.meta[id] && !force) return state.meta[id];
  const m = await api.metadata(id);
  state.meta = { ...state.meta, [id]: m };
  return m;
}

export async function select(id, fids, mode) {
  try {
    const r = await api.setSelection(id, fids, mode);
    set({ selection: { ...state.selection, [id]: r.fids } });
  } catch (e) {
    toast(e.message, "error");
  }
}

export async function clearAllSelections() {
  for (const [id, fids] of Object.entries(state.selection)) if (fids.length) await select(id, [], "clear");
}

export function setView(id, patch) {
  set({ views: { ...state.views, [id]: { ...state.views[id], ...patch } } });
}

export function moveLayer(id, toIndex) {
  const o = state.order.filter((x) => x !== id);
  o.splice(Math.max(0, Math.min(toIndex, o.length)), 0, id);
  set({ order: o });
}

export function openTable(id) {
  const t = state.tableLayers.includes(id) ? state.tableLayers : [...state.tableLayers, id];
  set({ tableLayers: t, activeTable: id, activeLayer: id, panes: { ...state.panes, bottom: true } });
}

export function closeTable(id) {
  const t = state.tableLayers.filter((x) => x !== id);
  set({ tableLayers: t, activeTable: state.activeTable === id ? t[t.length - 1] ?? null : state.activeTable });
}

export function openTool(id, preset = null) {
  set({ activeToolId: id, toolPreset: preset, gpTab: "tools", panes: { ...state.panes, right: true } });
}

// map-zoom bridge (set by map.js)
export const mapBridge = { zoomTo: () => {}, zoomBy: () => {}, tilt: () => {}, resetNorth: () => {} };

export async function zoomToLayer(id) {
  const m = await loadMeta(id);
  if (!m.profile?.extent_4326) return toast(`${m.label}: no drawable extent (unknown CRS or no geometry).`, "warning");
  mapBridge.zoomTo(m.profile.extent_4326);
}

export async function zoomToSelection(id) {
  const ids = id ? [id] : Object.keys(state.selection).filter((k) => state.selection[k]?.length);
  const boxes = [];
  for (const lid of ids) {
    try { boxes.push((await api.selectionExtent(lid)).bbox); } catch { /* layer without selection */ }
  }
  if (!boxes.length) return toast("Nothing is selected.", "warning");
  mapBridge.zoomTo(unionBox(boxes));
}

export function unionBox(bs) {
  return [Math.min(...bs.map((b) => b[0])), Math.min(...bs.map((b) => b[1])), Math.max(...bs.map((b) => b[2])), Math.max(...bs.map((b) => b[3]))];
}

export const layerById = (id) => state.layers.find((l) => l.layer_id === id);
export const drawable = (l) => l && l.crs?.status === "known" && l.geometry_family !== "Table" && l.feature_count > 0;
