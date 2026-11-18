"""Buffer (Analysis > Proximity)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from ..jobs import RunContext, ToolError
from ..registry.tools import LINEAR_UNITS, Param, ToolSpec, register
from ..storage.io import FID
from .common import INVALID_PARAM_VALUES, handle_geometry_quality, require_projected, to_crs_units


def buffer_geometries(geoms: np.ndarray, distances: np.ndarray, line_end_type: str = "round",
                      quad_segs: int = 16) -> np.ndarray:
    """Pure planar buffer. `distances` in CRS units, per feature."""
    cap = "flat" if line_end_type == "flat" else "round"
    return shapely.buffer(geoms, distances, quad_segs=quad_segs, cap_style=cap)


def buffer(ctx: RunContext, input_layer: str, distance: float | None = None, distance_field: str | None = None,
           units: str = "feet", line_end_type: str = "round", dissolve_option: str = "none",
           dissolve_fields: list[str] | None = None, method: str = "planar", invalid_geometry: str = "repair",
           use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    if method != "planar":
        raise ToolError("Geodesic buffering is not implemented yet. Use method 'planar' on a projected CRS.")
    gdf = ctx.input_gdf(input_layer, "input", use_selection)
    require_projected(gdf, info["label"])
    n_in = len(gdf)
    gdf = handle_geometry_quality(ctx, gdf, info["label"], invalid_geometry)

    if distance_field:
        raw = pd.to_numeric(gdf[distance_field], errors="coerce")
        nulls = int(raw.isna().sum())
        if nulls:
            ctx.warn(f"{nulls} features have null/non-numeric '{distance_field}' and are excluded.")
        gdf = gdf[raw.notna()]
        raw = raw[raw.notna()]
        user_dist = raw.to_numpy(dtype=float)
        ctx.message(f"Distance from field '{distance_field}' interpreted as {units}.")
    else:
        if distance is None:
            raise ToolError("Provide a linear distance or a distance field.")
        user_dist = np.full(len(gdf), float(distance))
    factor = to_crs_units(1.0, units, gdf)
    crs_dist = user_dist * factor
    unit_name = gdf.crs.axis_info[0].unit_name
    ctx.message(f"Buffer distance(s) converted from {units} to CRS units ({unit_name}) by factor {factor:.10g}; "
                f"method=planar, line end={line_end_type}.")

    fam = info["geometry_family"]
    if fam != "Polygon" and (crs_dist < 0).any():
        ctx.warn("Negative distances only apply to polygons; such point/line features produce no output.")
    if fam != "Line" and line_end_type == "flat":
        ctx.warn("Line end type FLAT applies to line input only; ignored.")
    ctx.progress(0.3)
    out_geoms = buffer_geometries(gdf.geometry.values, crs_dist, line_end_type if fam == "Line" else "round")
    ctx.progress(0.7)

    out = gdf.drop(columns=[FID]).copy()
    out["BUFF_DIST"] = user_dist
    out["BUFF_UNITS"] = units
    out["ORIG_FID"] = gdf[FID].to_numpy()
    out = out.set_geometry(gpd.GeoSeries(out_geoms, index=out.index, crs=gdf.crs))
    keep = ~(shapely.is_empty(out.geometry.values) | shapely.is_missing(out.geometry.values))
    n_empty = int((~keep).sum())
    if n_empty:
        ctx.warn(f"{n_empty} features produced empty buffers (e.g. negative distance larger than the polygon) and "
                 "are excluded.")
    out = out[keep]

    if dissolve_option == "all":
        geom = shapely.union_all(out.geometry.values)
        out = gpd.GeoDataFrame({"BUFF_COUNT": [len(out)]}, geometry=[geom], crs=gdf.crs)
    elif dissolve_option == "list":
        if not dissolve_fields:
            raise ToolError("Dissolve option 'list' requires at least one dissolve field.")
        grp = out.groupby(dissolve_fields, dropna=False)
        geoms = grp.geometry.apply(lambda s: shapely.union_all(s.values))
        counts = grp.size()
        out = gpd.GeoDataFrame(geoms.index.to_frame(index=False), geometry=list(geoms.values), crs=gdf.crs)
        out["BUFF_COUNT"] = counts.to_numpy()
    ctx.counts.update({"input_features": n_in, "processed": int(keep.sum()), "excluded_empty_output": n_empty,
                       "output_features": len(out)})
    lyr = ctx.write_layer(out, label=f"{info['label']} Buffer")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


register(ToolSpec(
    id="analysis.buffer",
    name="Buffer",
    category="Proximity",
    toolbox="Analysis",
    summary="Creates buffer polygons around input features to a specified distance.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/buffer.htm",
    executor=buffer,
    output_type="layer",
    params=[
        Param("input_layer", "Input features", "layer", geometry=["Point", "Line", "Polygon"],
              crs_requirement="projected"),
        Param("distance", "Distance (linear)", "number", required=False, role="parameter",
              description="Leave empty to use a distance field. Negative values shrink polygons."),
        Param("distance_field", "Distance field", "field", required=False, parent="input_layer",
              field_types=["integer", "double"], role="parameter"),
        Param("units", "Distance units", "linear_unit", default="feet", values=list(LINEAR_UNITS), role="parameter"),
        Param("line_end_type", "End type (lines)", "enum", default="round", values=["round", "flat"],
              role="parameter"),
        Param("dissolve_option", "Dissolve type", "enum", default="none", values=["none", "all", "list"],
              value_labels={"none": "No dissolve", "all": "Dissolve all output into a single feature",
                            "list": "Dissolve by attribute fields"}, role="parameter"),
        Param("dissolve_fields", "Dissolve fields", "fields", required=True, parent="input_layer", role="parameter",
              visible_when={"dissolve_option": ["list"]}),
        Param("method", "Method", "enum", default="planar", values=["planar", "geodesic"],
              value_labels={"planar": "Planar", "geodesic": "Geodesic (not yet supported)"}, role="parameter"),
        Param("invalid_geometry", "Invalid geometry", "enum", default="repair", values=INVALID_PARAM_VALUES,
              role="parameter"),
    ],
    known_differences=[
        "Planar only; GEODESIC method returns a clear error. ArcGIS defaults to geodesic for GCS input; we refuse "
        "geographic input instead.",
        "Curves are approximated with 16 segments per quarter circle (GEOS; inscribed polygon, point-buffer area "
        "~0.16% low); ArcGIS stores true arcs where the format supports them.",
        "Side type (LEFT/RIGHT/OUTSIDE_ONLY) is not implemented; FULL is always used.",
        "Dissolve 'all' produces one multipart feature (ArcGIS may produce multiple singlepart features unless "
        "multipart is requested).",
        "Output adds BUFF_DIST, BUFF_UNITS and ORIG_FID (ArcGIS adds BUFF_DIST and ORIG_FID).",
    ],
))
