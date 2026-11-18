// Contents pane: grouped layer list with visibility, symbol color, drag reorder, context menu.
import { openProperties } from "./dialogs.js";
import {
  PALETTE, drawable, layerById, moveLayer, on, openTable, openTool, select, set, setView, state, zoomToLayer, zoomToSelection,
} from "./state.js";
import { $, h, showMenu, svgIcon, symbolSvg } from "./ui.js";

let dragId = null;

export function initContents() {
  on(["layers", "views", "order", "selection", "activeLayer", "collapsedGroups"], render);
  $("#layer-filter").addEventListener("input", render);
  render();
}

function render() {
  const root = $("#contents");
  const q = $("#layer-filter").value.trim().toLowerCase();
  const ordered = state.order.map(layerById).filter(Boolean).filter((l) => !q || l.label.toLowerCase().includes(q) || l.layer_id.includes(q));
  const sources = ordered.filter((l) => l.tier !== "gold");
  const libGroups = [...new Set(sources.map((l) => l.group).filter(Boolean))];
  const groups = [
    ["results", "Analysis results", ordered.filter((l) => l.tier === "gold")],
    ...libGroups.map((g) => [`lib:${g}`, g, sources.filter((l) => l.group === g)]),
    ["sources", libGroups.length ? "Other source layers · read-only" : "Source layers · read-only", sources.filter((l) => !l.group)],
  ];
  root.replaceChildren(
    ...groups.filter(([, , ls]) => ls.length).map(([key, name, ls]) => {
      const collapsed = !!state.collapsedGroups[key];
      const nOn = ls.filter((l) => state.views[l.layer_id]?.visible && drawable(l)).length;
      return h(`div.group${collapsed ? ".collapsed" : ""}${key.startsWith("lib:") ? ".lib" : ""}`,
        h("button.group-head", { onclick: () => set({ collapsedGroups: { ...state.collapsedGroups, [key]: !collapsed } }) },
          svgIcon("chev"), name, h("span.count", { title: `${nOn} of ${ls.length} shown` }, key === "results" ? String(ls.length) : `${nOn}/${ls.length}`)),
        h("ul.layer-list", ls.map(row)));
    }),
  );
  if (!state.layers.length) root.appendChild(h("div.contents-empty", svgIcon("layers"), h("p", "No layers yet."), h("button.btn.primary", { onclick: () => document.querySelector('[data-action="add-data"]').click() }, "Add data")));
  else if (!ordered.length) root.appendChild(h("div.contents-empty", "No layers match the filter."));
}

function row(l) {
  const v = state.views[l.layer_id];
  const nsel = state.selection[l.layer_id]?.length || 0;
  const crsUnknown = l.crs?.status !== "known";
  const canDraw = drawable(l);
  const visible = v.visible && canDraw;
  const colorInput = h("input", { type: "color", value: v.color, "aria-label": `Symbol color for ${l.label}`, oninput: (e) => setView(l.layer_id, { color: e.target.value }) });
  const li = h(`li.lyr${state.activeLayer === l.layer_id ? ".active" : ""}${visible ? "" : ".hidden-lyr"}`, {
    draggable: "true",
    dataset: { id: l.layer_id },
    ondragstart: (e) => { dragId = l.layer_id; li.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; },
    ondragend: () => { dragId = null; li.classList.remove("dragging"); },
    ondragover: (e) => {
      if (!dragId || dragId === l.layer_id) return;
      e.preventDefault();
      const r = li.getBoundingClientRect();
      const after = e.clientY > r.top + r.height / 2;
      li.classList.toggle("drop-after", after);
      li.classList.toggle("drop-before", !after);
    },
    ondragleave: () => li.classList.remove("drop-after", "drop-before"),
    ondrop: (e) => {
      e.preventDefault();
      const after = li.classList.contains("drop-after");
      li.classList.remove("drop-after", "drop-before");
      if (!dragId || dragId === l.layer_id) return;
      const without = state.order.filter((x) => x !== dragId);
      const idx = without.indexOf(l.layer_id) + (after ? 1 : 0);
      moveLayer(dragId, idx);
    },
    oncontextmenu: (e) => { e.preventDefault(); layerMenu(l, { x: e.clientX, y: e.clientY }); },
  },
  h("div.lyr-row",
    h("span.lyr-grip", { title: "Drag to reorder" }, svgIcon("grip")),
    h("input", {
      type: "checkbox", checked: visible, disabled: !canDraw, "aria-label": `Show ${l.label}`,
      title: canDraw ? "Show / hide" : crsUnknown ? "Unknown coordinate system — run Define Projection to draw it" : "Non-spatial table",
      onchange: (e) => setView(l.layer_id, { visible: e.target.checked }),
    }),
    h("label.sym", { title: "Change color" }, symbolSvg(l.geometry_family, v.color), colorInput),
    h("div.lyr-text", { onclick: () => { set({ activeLayer: l.layer_id }); openTable(l.layer_id); }, ondblclick: () => canDraw && zoomToLayer(l.layer_id), title: `${l.label}\nClick: open table · Double-click: zoom` },
      h("div.lyr-name", l.label),
      h("div.lyr-meta",
        h("span", `${l.feature_count.toLocaleString()} ${l.geometry_family === "Table" ? "rows" : "features"}`),
        h("span", "·"),
        h(`span.crs${crsUnknown ? ".bad" : l.crs.is_geographic ? ".geo" : ""}`, { title: l.crs?.name || "Unknown coordinate system" }, l.crs?.srs || "CRS unknown"),
        nsel ? h("button.badge.sel", { title: "Zoom to selection", onclick: (e) => { e.stopPropagation(); zoomToSelection(l.layer_id); } }, `${nsel} selected`) : null,
        l.warnings.length ? h("button.badge.warn", { title: l.warnings.join("\n"), onclick: (e) => { e.stopPropagation(); openProperties(l.layer_id, "quality"); } }, svgIcon("warn"), String(l.warnings.length)) : null,
      )),
    h("div.lyr-actions",
      h("button.icon-btn", { title: "Zoom to layer", "aria-label": "Zoom to layer", disabled: !canDraw, onclick: () => zoomToLayer(l.layer_id) }, svgIcon("extent")),
      h("button.icon-btn", { title: "More", "aria-label": "Layer options", onclick: (e) => layerMenu(l, e.currentTarget) }, svgIcon("more")))),
  h("div.lyr-extra",
    h("label", "Transparency",
      h("input", { type: "range", min: "0.1", max: "1", step: "0.05", value: String(v.opacity), oninput: (e) => setView(l.layer_id, { opacity: Number(e.target.value) }) }))),
  );
  return li;
}

function layerMenu(l, anchor) {
  const v = state.views[l.layer_id];
  const nsel = state.selection[l.layer_id]?.length || 0;
  const idx = state.order.indexOf(l.layer_id);
  const swatches = h("div.swatches", PALETTE.slice(0, 8).concat(["#000000", "#ffffff"].slice(0, 0)).map((c) =>
    h("button", { style: { background: c }, title: c, "aria-label": `Color ${c}`, onclick: () => { setView(l.layer_id, { color: c }); document.querySelector(".menu")?.remove(); } })));
  const opacity = h("div.mrange", "Opacity",
    h("input", { type: "range", min: "0.1", max: "1", step: "0.05", value: String(v.opacity), oninput: (e) => setView(l.layer_id, { opacity: Number(e.target.value) }) }));
  showMenu(anchor, [
    { label: "Attribute table", icon: "table", onClick: () => openTable(l.layer_id) },
    { label: "Zoom to layer", icon: "extent", disabled: !drawable(l), onClick: () => zoomToLayer(l.layer_id) },
    { label: `Zoom to selection (${nsel})`, icon: "zoomsel", disabled: !nsel, onClick: () => zoomToSelection(l.layer_id) },
    { label: "Clear selection", icon: "clear", disabled: !nsel, onClick: () => select(l.layer_id, [], "clear") },
    "-",
    { label: "Move to top", icon: "up", disabled: idx === 0, onClick: () => moveLayer(l.layer_id, 0) },
    { label: "Move to bottom", icon: "down", disabled: idx === state.order.length - 1, onClick: () => moveLayer(l.layer_id, state.order.length) },
    "-",
    { heading: true, label: "Symbology" },
    swatches,
    opacity,
    "-",
    { label: "Buffer…", icon: "buffer", onClick: () => openTool("analysis.buffer", { input_layer: l.layer_id }) },
    { label: "Clip…", icon: "clip", onClick: () => openTool("analysis.clip", { input_layer: l.layer_id }) },
    { label: "Space-time analysis…", icon: "hotspot", onClick: () => set({ gpTab: "spacetime", spacetimeInput: l.layer_id, panes: { ...state.panes, right: true } }) },
    { label: "Export features…", icon: "exportfeat", onClick: () => openTool("conversion.export_features", { input_layer: l.layer_id }) },
    "-",
    { label: "Properties", icon: "info", onClick: () => openProperties(l.layer_id) },
  ]);
}
