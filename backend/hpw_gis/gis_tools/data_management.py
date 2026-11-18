"""Project, Define Projection, Export Features."""
from __future__ import annotations

import shapely
from pyproj import CRS

from ..jobs import RunContext, ToolError
from ..registry.tools import Param, ToolSpec, register
from ..storage.io import FID
from .expressions import ExpressionError, evaluate

ANY = ["Point", "Line", "Polygon", "Mixed"]


def project(ctx: RunContext, input_layer: str, output_crs: str, use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection)
    if gdf.crs is None:
        raise ToolError("Input CRS is unknown; Project needs a known source CRS. Use Define Projection first.")
    target = CRS.from_user_input(output_crs)
    if gdf.crs.equals(target):
        ctx.warn("Input is already in the output coordinate system; output is a copy.")
    ctx.transformations.append(f"{gdf.crs.to_string()} -> {target.to_string()} (pyproj default transformation)")
    out = gdf.drop(columns=[FID]).to_crs(target)
    out["ORIG_FID"] = gdf[FID].to_numpy()
    bad = int((~shapely.is_valid(out.geometry.values[out.geometry.notna().to_numpy()])).sum())
    if bad:
        ctx.warn(f"{bad} geometries are invalid after projection.")
    ctx.counts.update({"input_features": len(gdf), "output_features": len(out)})
    lyr = ctx.write_layer(out, label=f"{info['label']} ({target.to_string()})")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


def define_projection(ctx: RunContext, input_layer: str, coordinate_system: str, use_selection: bool = False) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection=False)
    target = CRS.from_user_input(coordinate_system)
    if gdf.crs is not None:
        ctx.warn(f"Input already declares {gdf.crs.to_string()}. Define Projection does NOT transform coordinates; "
                 "it only relabels them. Use Project to transform.")
    out = gdf.drop(columns=[FID]).set_crs(target, allow_override=True)
    out["ORIG_FID"] = gdf[FID].to_numpy()
    b = out.total_bounds
    if target.is_geographic and (abs(b[0]) > 180 or abs(b[2]) > 180 or abs(b[1]) > 90 or abs(b[3]) > 90):
        raise ToolError(f"Coordinates (extent {b.round(2).tolist()}) are outside valid degrees; {target.name} "
                        "cannot be the correct CRS.")
    if target.area_of_use:
        a = target.area_of_use
        g = out.to_crs("EPSG:4326").total_bounds
        if g[0] < a.west - 1 or g[2] > a.east + 1 or g[1] < a.south - 1 or g[3] > a.north + 1:
            ctx.warn(f"Data extent falls outside the area of use of {target.name} ({a.name}). Verify the CRS.")
    ctx.transformations.append(f"CRS label assigned: {target.to_string()} (no coordinate change)")
    ctx.counts.update({"input_features": len(gdf), "output_features": len(out)})
    lyr = ctx.write_layer(out, label=f"{info['label']} [{target.to_string()}]")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


def export_features(ctx: RunContext, input_layer: str, where_clause: str | None = None,
                    use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection)
    if where_clause:
        try:
            mask, _ = evaluate(gdf.drop(columns=[gdf.geometry.name]), where_clause)
        except ExpressionError as e:
            raise ToolError(f"Invalid expression: {e}") from e
        gdf = gdf[mask]
    out = gdf.drop(columns=[FID]).copy()
    out["ORIG_FID"] = gdf[FID].to_numpy()
    ctx.counts.update({"input_features": info["feature_count"], "output_features": len(out)})
    if out.empty:
        ctx.warn("No features matched; an empty layer was created.")
    lyr = ctx.write_layer(out, label=f"{info['label']} Export")
    return {"kind": "layer", "layer_id": lyr["layer_id"]}


register(ToolSpec(
    id="management.project",
    name="Project",
    category="Projections and Transformations",
    toolbox="Data Management",
    summary="Projects spatial data from one coordinate system to another.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/project.htm",
    executor=project,
    output_type="layer",
    params=[
        Param("input_layer", "Input dataset", "layer", geometry=ANY, crs_requirement="known"),
        Param("output_crs", "Output coordinate system", "crs", default="EPSG:2278", role="parameter",
              description="EPSG code or WKT, e.g. EPSG:2278 (NAD83 / Texas South Central ftUS), EPSG:4326."),
    ],
    known_differences=[
        "Datum transformation is chosen automatically by PROJ (best available); ArcGIS lets you pick a named "
        "geographic transformation. Results can differ by up to ~1-2 m where grids are unavailable offline.",
    ],
))

register(ToolSpec(
    id="management.define_projection",
    name="Define Projection",
    category="Projections and Transformations",
    toolbox="Data Management",
    summary="Records the coordinate system of a dataset whose coordinate system is unknown or incorrect.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/define-projection.htm",
    executor=define_projection,
    output_type="layer",
    params=[
        Param("input_layer", "Input dataset", "layer", geometry=ANY),
        Param("coordinate_system", "Coordinate system", "crs", role="parameter",
              description="The TRUE coordinate system of the stored coordinates (confirm with the data owner)."),
    ],
    known_differences=[
        "ArcGIS modifies the input dataset in place. Here the source is read-only, so a derived copy with the "
        "assigned CRS is created.",
    ],
))

register(ToolSpec(
    id="conversion.export_features",
    name="Export Features",
    category="Features",
    toolbox="Conversion",
    summary="Copies features (selected, or matching an optional expression) to a new layer.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/conversion/export-features.htm",
    executor=export_features,
    output_type="layer",
    params=[
        Param("input_layer", "Input features", "layer", geometry=ANY, allow_table=True),
        Param("where_clause", "Expression (optional)", "expression", required=False, parent="input_layer",
              role="parameter"),
    ],
    known_differences=["Field map / sort field parameters are not implemented; all fields are copied."],
))
