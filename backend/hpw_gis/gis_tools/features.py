"""Feature To Point (Data Management > Features)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from ..jobs import RunContext
from ..registry.tools import Param, ToolSpec, register
from ..storage.io import FID


def feature_points(geoms: np.ndarray, point_location: str = "centroid") -> np.ndarray:
    """Pure: one point per geometry. 'centroid' = geometric centroid; 'inside' = a point guaranteed to lie on
    the feature (on the line for lines, inside the polygon for polygons). Null/empty -> None."""
    missing = shapely.is_missing(geoms) | shapely.is_empty(geoms)
    out = np.empty(len(geoms), dtype=object)
    ok = ~missing
    if point_location == "inside":
        g = geoms[ok]
        lines = np.isin(shapely.get_type_id(g), [1, 5])  # LineString / MultiLineString
        pts = shapely.point_on_surface(g)
        if lines.any():  # midpoint along the line (by length) is more useful than an arbitrary vertex
            merged = shapely.line_merge(g[lines])
            single = shapely.get_type_id(merged) == 1
            mid = shapely.point_on_surface(g[lines])
            mid[single] = shapely.line_interpolate_point(merged[single], 0.5, normalized=True)
            pts[lines] = mid
        out[ok] = pts
    else:
        out[ok] = shapely.centroid(geoms[ok])
    out[missing] = None
    return out


def feature_to_point(ctx: RunContext, input_layer: str, point_location: str = "centroid",
                     use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection)
    pts = feature_points(gdf.geometry.values, point_location)
    out = gdf.drop(columns=[FID]).copy()
    out["ORIG_FID"] = gdf[FID].to_numpy()
    out = out.set_geometry(gpd.GeoSeries(pts, index=out.index, crs=gdf.crs))
    n_null = int(out.geometry.isna().sum())
    if n_null:
        ctx.warn(f"{n_null} features have null/empty geometry and produce a null point.")
    ctx.counts.update({"input_features": len(gdf), "output_features": len(out), "null_geometry": n_null})
    lyr = ctx.write_layer(out, label=f"{info['label']} Points")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


register(ToolSpec(
    id="management.feature_to_point",
    name="Feature To Point",
    category="Features",
    toolbox="Data Management",
    summary="Creates a point for each input feature (its centroid, or a point that lies on the feature).",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/feature-to-point.htm",
    executor=feature_to_point,
    output_type="layer",
    params=[
        Param("input_layer", "Input features", "layer", geometry=["Point", "Line", "Polygon", "Mixed"],
              crs_requirement="known"),
        Param("point_location", "Point location", "enum", default="centroid", values=["centroid", "inside"],
              value_labels={"centroid": "Centroid", "inside": "Inside (on the feature)"}, role="parameter"),
    ],
    known_differences=[
        "'Inside' places line points at the middle of the line by length (single-part lines) or on the line "
        "for multipart lines; ArcGIS documents only that the point lies on the feature.",
        "Z values are not kept on output points (2D centroids).",
        "Output adds ORIG_FID (as ArcGIS) - all source attributes are kept.",
    ],
))
