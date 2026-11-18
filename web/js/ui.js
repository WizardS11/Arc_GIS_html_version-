// Small DOM toolkit: element builder, icons, toasts, popover menus, modals.

const ICONS = {
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  moon: '<path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  cursor: '<path d="M5 3l14 7.5-6.2 1.7L10 18.5z"/><path d="M13 12.5l5 5"/>',
  select: '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5" stroke-dasharray="3 2.4"/><path d="M10 9l7 3.3-2.8.8-1.2 2.9z"/>',
  clear: '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5" stroke-dasharray="3 2.4"/><path d="M9 9l6 6M15 9l-6 6"/>',
  zoomsel: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M20 20l-4.6-4.6"/><rect x="8" y="8" width="5" height="5" rx=".5"/>',
  extent: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><circle cx="12" cy="12" r="2.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  adddata: '<path d="M4 7.5c0-1.4 3.6-2.5 8-2.5s8 1.1 8 2.5-3.6 2.5-8 2.5-8-1.1-8-2.5z"/><path d="M4 7.5v9c0 1.4 3.6 2.5 8 2.5"/><path d="M20 7.5V12"/><path d="M18 15v6M15 18h6"/>',
  toolbox: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M8 8V6a2 2 0 012-2h4a2 2 0 012 2v2M3 13h18M10 13v2h4v-2"/>',
  history: '<path d="M3.5 12a8.5 8.5 0 102.5-6"/><path d="M3 4v4h4"/><path d="M12 8v4.5l3 2"/>',
  table: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 9.5h17M3.5 14.5h17M9 9.5v10"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2"/>',
  folder: '<path d="M3.5 6.5a1.5 1.5 0 011.5-1.5h4l2 2h8a1.5 1.5 0 011.5 1.5V18a1.5 1.5 0 01-1.5 1.5H5A1.5 1.5 0 013.5 18z"/>',
  save: '<path d="M5 3.5h11.5l3 3V19a1.5 1.5 0 01-1.5 1.5H5A1.5 1.5 0 013.5 19V5A1.5 1.5 0 015 3.5z"/><path d="M8 3.5v5h7v-5M7.5 20.5v-6h9v6"/>',
  paneleft: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M9 4.5v15"/>',
  paneright: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M15 4.5v15"/>',
  panebottom: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M3.5 14h17"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  buffer: '<circle cx="12" cy="12" r="2.6"/><circle cx="12" cy="12" r="8.5" stroke-dasharray="3 2.3"/>',
  clip: '<circle cx="6.5" cy="6.5" r="2.7"/><circle cx="6.5" cy="17.5" r="2.7"/><path d="M8.6 8.2L20 18M8.6 15.8L20 6"/>',
  selattr: '<path d="M4 6.5h9M4 12h9M4 17.5h9"/><path d="M15.5 12l2 2 3.5-4"/>',
  selloc: '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  project: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.3 3.5 5.2 3.5 8.5s-1 6.2-3.5 8.5c-2.5-2.3-3.5-5.2-3.5-8.5s1-6.2 3.5-8.5z"/>',
  defproj: '<circle cx="12" cy="12" r="7"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/><circle cx="12" cy="12" r="1.5"/>',
  exportfeat: '<path d="M14 3.5h6.5V10M20.5 3.5L11 13"/><path d="M18.5 14v4.5a2 2 0 01-2 2h-11a2 2 0 01-2-2v-11a2 2 0 012-2H10"/>',
  tool: '<path d="M14.5 6.5a4 4 0 00-5.3 5.2L3.5 17.4 6.6 20.5l5.7-5.7a4 4 0 005.2-5.3l-2.5 2.5-2.6-.6-.6-2.6z"/>',
  more: '<circle cx="5.5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18.5" cy="12" r="1.3"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
  chevleft: '<path d="M15 6l-6 6 6 6"/>',
  warn: '<path d="M12 4l9 15.5H3z"/><path d="M12 10v4M12 16.8v.2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  checkc: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8L16 9.5"/>',
  xc: '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>',
  play: '<path d="M7 4.5v15l12.5-7.5z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M4.5 20h15"/>',
  upload: '<path d="M12 16V4.5M7 9.5l5-5 5 5M4.5 20h15"/>',
  palette: '<path d="M12 3.5a8.5 8.5 0 000 17c1.2 0 1.8-.8 1.8-1.7 0-1.3-1.2-1.5-1.2-2.6 0-1 .8-1.7 1.8-1.7h2.3a3.8 3.8 0 003.8-3.8c0-4-3.8-7.2-8.5-7.2z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7.3" r="1"/><circle cx="14.5" cy="7.3" r="1"/>',
  stats: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  columns: '<rect x="3.5" y="4.5" width="17" height="15" rx="1.5"/><path d="M9.2 4.5v15M14.8 4.5v15"/>',
  filter: '<path d="M3.5 5h17l-6.5 8v5.5l-4 1.5V13z"/>',
  swap: '<path d="M7 4L3.5 7.5 7 11M3.5 7.5h13M17 13l3.5 3.5L17 20M20.5 16.5h-13"/>',
  layers: '<path d="M12 3.5l9 4.8-9 4.8-9-4.8z"/><path d="M3 12.3l9 4.8 9-4.8M3 16.2l9 4.8 9-4.8"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  file: '<path d="M6 3.5h8l4.5 4.5v12.5H6z"/><path d="M14 3.5V8h4.5"/>',
  db: '<ellipse cx="12" cy="6" rx="7.5" ry="2.5"/><path d="M4.5 6v12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V6M4.5 12c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5"/>',
  shield: '<path d="M12 3l7.5 3v6c0 4.5-3.2 7.7-7.5 9-4.3-1.3-7.5-4.5-7.5-9V6z"/>',
  library: '<rect x="3.5" y="4" width="4" height="16" rx="1"/><rect x="9.5" y="4" width="4" height="16" rx="1"/><path d="M15.6 5.2l3.8-1 3.1 15.4-3.8.9z"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  hotspot: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="6.5" stroke-dasharray="2.5 2"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2"/>',
  topoint: '<path d="M4 18c4-1 5-11 9-12s5 6 7 6"/><circle cx="12" cy="7" r="2.4" fill="currentColor"/>',
  timeline: '<path d="M3.5 18.5h17"/><path d="M6 18.5V12M10 18.5V8M14 18.5v-4M18 18.5V5"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  buildings: '<path d="M3.5 20.5h17"/><path d="M5 20.5V9l5-2.5v14M10 20.5V4l6 3v13.5M16 20.5V11l3.5 1.5v8"/><path d="M12.5 9.5h1M12.5 12.5h1M12.5 15.5h1M7 12h1M7 15h1"/>',
  tilt: '<path d="M4 17l8 3.5 8-3.5-8-3.5z"/><path d="M12 13.5V4M9 6.5l3-3 3 3"/>',
  compass: '<circle cx="12" cy="12" r="8.5"/><path d="M12 5.5l2.5 6.5H9.5z" fill="currentColor"/><path d="M9.5 12h5L12 18.5z"/>',
  spark: '<path d="M3 17l5-6 4 3 5-8 4 5"/>',
  dashboard: '<rect x="3.5" y="3.5" width="7" height="9" rx="1.2"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.2"/><rect x="13.5" y="11.5" width="7" height="9" rx="1.2"/><rect x="3.5" y="15.5" width="7" height="5" rx="1.2"/>',
};

const TOOL_ICON = {
  "analysis.buffer": "buffer",
  "analysis.clip": "clip",
  "management.select_layer_by_attribute": "selattr",
  "management.select_layer_by_location": "selloc",
  "management.project": "project",
  "management.define_projection": "defproj",
  "conversion.export_features": "exportfeat",
  "management.feature_to_point": "topoint",
  "stpm.create_space_time_cube": "cube",
  "stpm.emerging_hot_spot_analysis": "hotspot",
};
export const toolIcon = (id) => TOOL_ICON[id] || "tool";

export function svgIcon(name, cls = "i") {
  const tpl = document.createElement("template");
  tpl.innerHTML = `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.tool}</svg>`;
  return tpl.content.firstChild;
}

/** Replace every <span data-icon="x"> placeholder under root with the SVG icon. */
export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.firstChild) return;
    el.appendChild(svgIcon(el.dataset.icon));
  });
}

/** Hyperscript element builder. h("div.cls#id", {onclick, style:{}, ...}, children...) */
export function h(sel, attrs, ...children) {
  if (attrs == null || typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs)) {
    if (attrs !== undefined) children.unshift(attrs);
    attrs = {};
  }
  const m = sel.match(/^([a-z0-9-]+)?((?:[.#][\w-]+)*)$/i);
  const el = document.createElement((m && m[1]) || "div");
  if (m && m[2]) {
    for (const part of m[2].match(/[.#][\w-]+/g)) {
      if (part[0] === ".") el.classList.add(part.slice(1));
      else el.id = part.slice(1);
    }
  }
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.className += (el.className ? " " : "") + v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "html") el.innerHTML = v;
    else if (k in el && typeof v !== "string" && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const icon = (name) => svgIcon(name);
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const fmtNum = (v, d = 4) =>
  typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: d })) : String(v ?? "—");

/** Symbol preview for a geometry family. */
export function symbolSvg(family, color, cls = "") {
  const c = esc(color);
  let inner;
  if (family === "Point") inner = `<circle cx="11" cy="9" r="5" fill="${c}" stroke="#fff" stroke-width="1.6"/>`;
  else if (family === "Line") inner = `<path d="M2 14 C7 3, 13 16, 20 4" fill="none" stroke="${c}" stroke-width="3" stroke-linecap="round"/>`;
  else if (family === "Polygon") inner = `<path d="M3 4 L18 2 L20 14 L6 16 Z" fill="${c}" fill-opacity=".35" stroke="${c}" stroke-width="1.8" stroke-linejoin="round"/>`;
  else if (family === "Table") inner = `<rect x="3" y="2.5" width="16" height="13" rx="1.5" fill="none" stroke="${c}" stroke-width="1.6"/><path d="M3 7h16M9 7v8.5" stroke="${c}" stroke-width="1.4"/>`;
  else inner = `<circle cx="6" cy="12" r="3" fill="${c}"/><path d="M10 13 L20 4" stroke="${c}" stroke-width="2.5"/>`;
  const tpl = document.createElement("template");
  tpl.innerHTML = `<svg viewBox="0 0 22 18" class="${cls}" aria-hidden="true">${inner}</svg>`;
  return tpl.content.firstChild;
}

// ---------------------------------------------------------------- toasts
export function toast(text, level = "info") {
  const name = { info: "info", success: "checkc", warning: "warn", error: "xc" }[level] || "info";
  const el = h(`div.toast.${level}`, { role: "status" }, svgIcon(name), h("div", text));
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), level === "error" ? 9000 : level === "warning" ? 7000 : 4500);
}

// ---------------------------------------------------------------- popover menu
let openMenu = null;
export function closeMenu() {
  if (openMenu) openMenu.remove();
  openMenu = null;
}
/** items: [{label, icon, onClick, disabled} | "-" | {label:"…", heading:true} | Node] */
export function showMenu(anchorOrPoint, items) {
  closeMenu();
  const m = h("div.menu", { role: "menu" });
  for (const it of items) {
    if (it === "-") m.appendChild(h("hr"));
    else if (it instanceof Node) m.appendChild(it);
    else if (it.heading) m.appendChild(h("div.mlabel", it.label));
    else
      m.appendChild(
        h("button", { role: "menuitem", disabled: !!it.disabled, onclick: () => { closeMenu(); it.onClick(); } },
          it.icon ? svgIcon(it.icon) : null, it.label),
      );
  }
  document.getElementById("popover-root").appendChild(m);
  const r = anchorOrPoint instanceof Element ? anchorOrPoint.getBoundingClientRect() : { left: anchorOrPoint.x, bottom: anchorOrPoint.y, right: anchorOrPoint.x };
  const mw = m.offsetWidth, mh = m.offsetHeight;
  let x = Math.min(r.left, window.innerWidth - mw - 8);
  let y = r.bottom + 4;
  if (y + mh > window.innerHeight - 8) y = Math.max(8, (r.top ?? y) - mh - 4);
  m.style.left = `${Math.max(8, x)}px`;
  m.style.top = `${y}px`;
  openMenu = m;
  setTimeout(() => {
    const off = (e) => { if (!m.contains(e.target)) { closeMenu(); document.removeEventListener("mousedown", off, true); } };
    document.addEventListener("mousedown", off, true);
  });
  return m;
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

// ---------------------------------------------------------------- modal
export function modal({ title, subtitle, iconName = "info", body, footer, wide = false, onClose }) {
  const root = document.getElementById("modal-root");
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    onClose && onClose();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const box = h(`div.modal${wide ? ".wide" : ""}`, { role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div.modal-head",
      h("div.ic", svgIcon(iconName)),
      h("h2", title, subtitle ? h("div.sub", subtitle) : null),
      h("button.icon-btn", { "aria-label": "Close", onclick: close }, svgIcon("close"))),
    body,
    footer || null,
  );
  const backdrop = h("div.modal-backdrop", { onmousedown: (e) => { if (e.target === backdrop) close(); } }, box);
  root.appendChild(backdrop);
  document.addEventListener("keydown", onKey);
  setTimeout(() => box.querySelector("input:not([type=hidden]),select,button.primary")?.focus(), 30);
  return { close, box };
}
