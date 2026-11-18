"""Clip (Analysis > Extract)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from ..jobs import RunContext, ToolError
from ..registry.tools import Param, ToolSpec, register
from ..storage.io import FID
from .common import INVALID_PARAM_VALUES, align_crs, handle_geometry_quality, require_known_crs

_DIM = {"Point": 0, "Line": 1, "Polygon": 2}


def clip_geometries(geoms: np.ndarray, mask_geom, keep_dim: int) -> np.ndarray:
    """Pure clip: intersect each geometry with mask, keeping only parts of dimension `keep_dim`."""
    out = shapely.intersection(geoms, mask_geom)
    res = np.empty(len(out), dtype=object)
    for i, g in enumerate(out):
        res[i] = _keep_dimension(g, keep_dim)
    return res


def _keep_dimension(g, dim: int):
    if g is None or g.is_empty:
        return None
    if shapely.get_dimensions(g) == dim and g.geom_type != "GeometryCollection":
        return g
    parts = [p for p in shapely.get_parts(g) if shapely.get_dimensions(p) == dim and not p.is_empty]
    if not parts:
        return None
    if dim == 0:
        return shapely.MultiPoint(parts) if len(parts) > 1 else parts[0]
    if dim == 1:
        return shapely.line_merge(shapely.MultiLineString(parts)) if len(parts) > 1 else parts[0]
    return shapely.MultiPolygon(parts) if len(parts) > 1 else parts[0]


def clip(ctx: RunContext, input_layer: str, clip_layer: str, invalid_geometry: str = "repair",
         use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    cinfo = ctx.registry.get(clip_layer)
    inp = ctx.input_gdf(input_layer, "input", use_selection)
    clp = ctx.input_gdf(clip_layer, "clip", use_selection)
    require_known_crs(inp, info["label"])
    clp = align_crs(ctx, clp, inp, f"Clip features ({cinfo['label']})")
    n_in = len(inp)
    inp = handle_geometry_quality(ctx, inp, info["label"], invalid_geometry)
    clp = handle_geometry_quality(ctx, clp, cinfo["label"], invalid_geometry)
    if clp.empty:
        raise ToolError("Clip features contain no usable polygons.")
    ctx.progress(0.2)
    mask_geom = shapely.union_all(clp.geometry.values)
    shapely.prepare(mask_geom)
    ctx.progress(0.4)
    dim = _DIM[info["geometry_family"]]
    inside_full = shapely.covered_by(inp.geometry.values, mask_geom)
    touching = shapely.intersects(inp.geometry.values, mask_geom)
    clipped = clip_geometries(inp.geometry.values, mask_geom, dim)
    ctx.progress(0.8)
    keep = np.array([g is not None for g in clipped])
    out = inp.drop(columns=[FID]).copy()
    out["ORIG_FID"] = inp[FID].to_numpy()
    out = out.set_geometry(gpd.GeoSeries(clipped, index=out.index, crs=inp.crs))[keep]
    n_partial = int((touching & ~inside_full & keep).sum())
    n_outside = int((~keep).sum())
    lower_dim_only = int((touching & ~keep).sum())
    if lower_dim_only:
        ctx.warn(f"{lower_dim_only} features touch the clip boundary only at lower dimension (e.g. a polygon sharing "
                 "an edge) and are excluded, as their output geometry type would differ.")
    ctx.counts.update({"input_features": n_in, "fully_inside": int((inside_full & keep).sum()),
                       "partially_clipped": n_partial, "outside_excluded": n_outside, "output_features": len(out)})
    ctx.message(f"Clip: {int((inside_full & keep).sum())} inside, {n_partial} cut at boundary, {n_outside} outside.")
    if info["geometry_family"] == "Line" and "LENGTH_FT" in out.columns:
        ctx.warn("Attribute 'LENGTH_FT' is copied from the source and NOT recalculated for clipped lines.")
    lyr = ctx.write_layer(out, label=f"{info['label']} Clip")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


register(ToolSpec(
    id="analysis.clip",
    name="Clip",
    category="Extract",
    toolbox="Analysis",
    summary="Extracts input features that overlay the clip features (cookie-cutter).",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/clip.htm",
    executor=clip,
    output_type="layer",
    params=[
        Param("input_layer", "Input features", "layer", geometry=["Point", "Line", "Polygon"],
              crs_requirement="known"),
        Param("clip_layer", "Clip features", "layer", geometry=["Polygon"], crs_requirement="known",
              description="All (or selected) polygons are unioned into one clip boundary."),
        Param("invalid_geometry", "Invalid geometry", "enum", default="repair", values=INVALID_PARAM_VALUES,
              role="parameter"),
    ],
    known_differences=[
        "Clip features are restricted to polygons (ArcGIS also accepts lines/points when inputs are lower-dimension).",
        "No XY tolerance/cluster processing: vertices are not snapped, so sliver results can differ from ArcGIS at "
        "the ~1e-9 coordinate level.",
        "Attribute values (e.g. length/area fields) are copied, not recalculated - same as ArcGIS (Shape_Length "
        "system fields are recomputed by ArcGIS but are not stored here).",
        "Output adds ORIG_FID for lineage.",
    ],
))
