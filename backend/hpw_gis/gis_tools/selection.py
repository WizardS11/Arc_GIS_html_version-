"""Select Layer By Attribute / Select Layer By Location (Data Management > Layers and Table Views)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from ..jobs import SELECTION_TYPE_LABELS, SELECTION_TYPES, RunContext, ToolError
from ..registry.tools import Param, ToolSpec, register
from ..storage.io import FID
from .common import align_crs, require_projected, to_crs_units
from .expressions import ExpressionError, evaluate

ALL_GEOMS = ["Point", "Line", "Polygon"]

# overlap_type -> human label
RELATIONSHIPS = {
    "intersect": "Intersect",
    "within_a_distance": "Within a distance",
    "contains": "Contains",
    "completely_contains": "Completely contains",
    "within": "Within",
    "completely_within": "Completely within",
    "boundary_touches": "Boundary touches",
    "crosses": "Crosses",
    "overlaps": "Overlaps (same dimension)",
    "have_their_center_in": "Have their center in",
    "are_identical_to": "Are identical to",
}


def spatial_match(inp: gpd.GeoDataFrame, sel: gpd.GeoDataFrame, relation: str, distance: float | None) -> np.ndarray:
    """Return boolean mask over `inp` rows that satisfy `relation` against ANY feature of `sel`.

    Pure function: both frames must already share a CRS; `distance` is in CRS units.
    """
    n = len(inp)
    mask = np.zeros(n, dtype=bool)
    if n == 0 or len(sel) == 0:
        return mask
    ig = inp.geometry.values
    sg = sel.geometry.values
    valid_in = ~(shapely.is_missing(ig) | shapely.is_empty(ig))
    tree = shapely.STRtree(sg)
    idx_in = np.where(valid_in)[0]
    probe = ig[idx_in]
    if relation == "intersect":
        pairs = tree.query(probe, predicate="intersects")
    elif relation == "within_a_distance":
        pairs = tree.query(probe, predicate="dwithin", distance=float(distance or 0.0))
    elif relation == "contains":  # input covers select feature (boundary contact allowed)
        pairs = tree.query(probe, predicate="covers")
    elif relation == "completely_contains":
        pairs = tree.query(probe, predicate="contains_properly")
    elif relation == "within":
        pairs = tree.query(probe, predicate="covered_by")
    elif relation == "completely_within":
        cand = tree.query(probe, predicate="intersects")
        ok = shapely.contains_properly(sg[cand[1]], probe[cand[0]])
        pairs = cand[:, ok]
    elif relation == "boundary_touches":
        cand = tree.query(probe, predicate="intersects")
        ok = shapely.intersects(_bnd(probe[cand[0]]), _bnd(sg[cand[1]]))
        pairs = cand[:, ok]
    elif relation == "crosses":
        pairs = tree.query(probe, predicate="crosses")
    elif relation == "overlaps":
        pairs = tree.query(probe, predicate="overlaps")
    elif relation == "have_their_center_in":
        centers = shapely.centroid(probe)
        pairs = tree.query(centers, predicate="covered_by")
    elif relation == "are_identical_to":
        cand = tree.query(probe, predicate="intersects")
        ok = shapely.equals(probe[cand[0]], sg[cand[1]])
        pairs = cand[:, ok]
    else:
        raise ToolError(f"Unsupported spatial relationship '{relation}'")
    if pairs.size:
        mask[idx_in[np.unique(pairs[0])]] = True
    return mask


def _bnd(geoms: np.ndarray) -> np.ndarray:
    """Boundary for lines/polygons; points (empty boundary) use the point itself."""
    t = shapely.get_type_id(geoms)
    return np.where(np.isin(t, [0, 4]), geoms, shapely.boundary(geoms))


def _finish_selection(ctx: RunContext, layer_id: str, matched_fids: set[int], selection_type: str, invert: bool,
                      label: str) -> dict:
    full = ctx.registry.gdf(layer_id)
    all_fids = set(int(x) for x in full[FID])
    if invert:
        matched_fids = all_fids - matched_fids
    before = len(ctx.selection.get(layer_id))
    res = ctx.selection.apply(layer_id, matched_fids, selection_type, all_fids)
    ctx.counts.update({"input_features": len(all_fids), "matched": len(matched_fids), "selected_before": before,
                       "selected_after": len(res)})
    ctx.message(f"{label}: {len(matched_fids)} features matched; selection now {len(res)} of {len(all_fids)} "
                f"({SELECTION_TYPE_LABELS[selection_type]}).")
    return {"kind": "selection", "layer_id": layer_id, "selected_count": len(res), "matched_count": len(matched_fids),
            "fids": sorted(res)}


def select_by_attributes(ctx: RunContext, input_layer: str, where_clause: str | None, selection_type: str = "new",
                         invert: bool = False, use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection=False)
    if selection_type == "clear":
        return _finish_selection(ctx, input_layer, set(), "clear", False, info["label"])
    if not where_clause:
        if selection_type in ("switch",):
            return _finish_selection(ctx, input_layer, set(), "switch", False, info["label"])
        raise ToolError("An expression is required (e.g. DIAMETER_IN >= 12 AND MATERIAL = 'PVC').")
    try:
        mask, used = evaluate(gdf.drop(columns=[gdf.geometry.name]), where_clause)
    except ExpressionError as e:
        raise ToolError(f"Invalid expression: {e}") from e
    ctx.message(f"Expression fields: {', '.join(sorted(used)) or '(none)'}")
    matched = set(int(x) for x in gdf.loc[mask, FID])
    return _finish_selection(ctx, input_layer, matched, selection_type, invert, info["label"])


def select_by_location(ctx: RunContext, input_layer: str, overlap_type: str, select_features: str,
                       search_distance: float | None = None, distance_units: str = "feet",
                       selection_type: str = "new", invert: bool = False, use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    inp = ctx.input_gdf(input_layer, "input", use_selection=False)
    sel = ctx.input_gdf(select_features, "selecting", use_selection=use_selection)
    sel = align_crs(ctx, sel, inp, "Selecting features")
    dist = None
    if overlap_type == "within_a_distance":
        require_projected(inp, info["label"])
        if search_distance is None:
            raise ToolError("Search distance is required for 'Within a distance'.")
        dist = to_crs_units(float(search_distance), distance_units, inp)
        ctx.message(f"Search distance {search_distance} {distance_units} = {dist:.4f} {inp.crs.axis_info[0].unit_name} "
                    "(planar).")
    elif search_distance:
        ctx.warn("Search distance is ignored for this relationship.")
    mask = spatial_match(inp, sel, overlap_type, dist)
    matched = set(int(x) for x in inp.loc[mask, FID])
    return _finish_selection(ctx, input_layer, matched, selection_type, invert, info["label"])


SEL_TYPE_PARAM = dict(name="selection_type", label="Selection type", type="enum", default="new",
                      values=SELECTION_TYPES, value_labels=SELECTION_TYPE_LABELS, role="parameter")

register(ToolSpec(
    id="management.select_layer_by_attribute",
    name="Select Layer By Attribute",
    category="Layers and Table Views",
    toolbox="Data Management",
    summary="Adds, updates, or removes a selection based on an attribute query (SQL-like WHERE clause).",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/select-layer-by-attribute.htm",
    executor=select_by_attributes,
    output_type="selection",
    params=[
        Param("input_layer", "Input rows", "layer", geometry=ALL_GEOMS + ["Mixed"], allow_table=True),
        Param(**SEL_TYPE_PARAM),
        Param("where_clause", "Expression", "expression", required=False, parent="input_layer", role="parameter",
              description="e.g. DIAMETER_IN >= 12 AND MATERIAL IN ('PVC','VCP') AND INSTALL_YR IS NOT NULL",
              visible_when={"selection_type": ["new", "add", "remove", "subset"]}),
        Param("invert", "Invert where clause", "boolean", required=False, default=False, role="parameter"),
    ],
    known_differences=[
        "Expression dialect is a documented SQL subset (=, <>, <, <=, >, >=, LIKE, IN, BETWEEN, IS [NOT] NULL, "
        "AND/OR/NOT, DATE 'yyyy-mm-dd'); SQL functions (UPPER, CAST, ...) are not yet supported.",
        "LIKE is case-sensitive (file geodatabase behaviour); some ArcGIS data sources are case-insensitive.",
        "Selection is held per workbench session/project, not inside a map document layer.",
    ],
))

register(ToolSpec(
    id="management.select_layer_by_location",
    name="Select Layer By Location",
    category="Layers and Table Views",
    toolbox="Data Management",
    summary="Selects features based on a spatial relationship to features in another layer.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/select-layer-by-location.htm",
    executor=select_by_location,
    output_type="selection",
    params=[
        Param("input_layer", "Input features", "layer", geometry=ALL_GEOMS, crs_requirement="known"),
        Param("overlap_type", "Relationship", "enum", default="intersect", values=list(RELATIONSHIPS),
              value_labels=RELATIONSHIPS, role="parameter"),
        Param("select_features", "Selecting features", "layer", geometry=ALL_GEOMS, crs_requirement="known",
              description="If this layer has a selection, only selected features are used."),
        Param("search_distance", "Search distance", "number", required=True, min=0, role="parameter",
              visible_when={"overlap_type": ["within_a_distance"]}),
        Param("distance_units", "Distance units", "linear_unit", default="feet", role="parameter",
              visible_when={"overlap_type": ["within_a_distance"]}),
        Param(**SEL_TYPE_PARAM),
        Param("invert", "Invert spatial relationship", "boolean", required=False, default=False, role="parameter"),
    ],
    known_differences=[
        "Uses exact GEOS predicates without an XY tolerance; ArcGIS applies the data's XY tolerance, so features "
        "within ~0.001 m of a boundary may evaluate differently.",
        "'Within a distance' is planar only and requires a projected CRS (ArcGIS uses geodesic for GCS data).",
        "Not yet implemented: *_CLEMENTINI variants, SHARE_A_LINE_SEGMENT_WITH, CROSSED_BY_THE_OUTLINE_OF, "
        "WITHIN_A_DISTANCE_GEODESIC, WITHIN_A_DISTANCE_3D.",
    ],
))
