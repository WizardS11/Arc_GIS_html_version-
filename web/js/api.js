// REST client for the local GIS engine.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailText(d) {
  if (Array.isArray(d)) return d.map((x) => (typeof x === "string" ? x : x.msg || JSON.stringify(x))).join("\n");
  if (typeof d === "string") return d;
  return JSON.stringify(d);
}

async function req(path, init) {
  const r = await fetch(path, init);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) throw new ApiError(r.status, detailText((data && data.detail) ?? data ?? r.statusText));
  return data;
}

const json = (body, method = "POST") => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => req("/api/health"),
  layers: () => req("/api/layers"),
  metadata: (id) => req(`/api/layers/${id}/metadata`),
  features: (id, bbox, where) => {
    const q = new URLSearchParams();
    if (bbox) q.set("bbox", bbox.map((v) => v.toFixed(7)).join(","));
    if (where) q.set("where", where);
    const s = q.toString();
    return req(`/api/layers/${id}/features${s ? `?${s}` : ""}`);
  },
  library: () => req("/api/library"),
  libraryAdd: (id) => req(`/api/library/${encodeURIComponent(id)}/add`, { method: "POST" }),
  table: (id, q) => req(`/api/layers/${id}/table`, json(q)),
  stats: (id, field) => req(`/api/layers/${id}/statistics/${encodeURIComponent(field)}`),
  importLayer: (form) => req("/api/layers/import", { method: "POST", body: form }),
  selection: () => req("/api/selection"),
  setSelection: (id, fids, mode) => req(`/api/selection/${id}`, json({ fids, mode }, "PUT")),
  selectByGeometry: (id, geometry, mode) => req(`/api/selection/${id}/by-geometry`, json({ geometry, mode })),
  selectionExtent: (id) => req(`/api/selection/${id}/extent`),
  tools: () => req("/api/tools"),
  runTool: (tool_id, params) => req("/api/tool-runs", json({ tool_id, params })),
  run: (id) => req(`/api/tool-runs/${id}`),
  runs: () => req("/api/tool-runs"),
  cancel: (id) => req(`/api/tool-runs/${id}/cancel`, { method: "POST" }),
  projects: () => req("/api/projects"),
  saveProject: (name, state) => req("/api/projects", json({ name, state })),
  openProject: (name) => req(`/api/projects/${encodeURIComponent(name)}`),
};

export const exportUrl = (id, format, selectedOnly) => `/api/layers/${id}/export?format=${format}&selected_only=${selectedOnly}`;
