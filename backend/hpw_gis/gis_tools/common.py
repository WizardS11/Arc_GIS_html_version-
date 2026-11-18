"""Shared CRS / unit / validity safeguards (spec §7.1)."""
from __future__ import annotations

import geopandas as gpd
import shapely

from ..jobs import RunContext, ToolError
from ..registry.tools import LINEAR_UNITS


def require_known_crs(gdf: gpd.GeoDataFrame, label: str) -> None:
    if gdf.crs is None:
        raise ToolError(f"{label}: coordinate reference system is UNKNOWN. Run Define Projection first.")


def require_projected(gdf: gpd.GeoDataFrame, label: str) -> None:
    require_known_crs(gdf, label)
    if not gdf.crs.is_projected:
        raise ToolError(f"{label}: {gdf.crs.name} is geographic (degrees); planar distances would be meaningless. "
                        "Run Project to a projected CRS (e.g. EPSG:2278 Texas South Central ftUS) first.")


def crs_unit_to_meters(gdf: gpd.GeoDataFrame) -> float:
    ax = gdf.crs.axis_info[0]
    f = ax.unit_conversion_factor
    if not f or f <= 0:
        raise ToolError(f"Cannot determine linear unit of {gdf.crs.name}")
    return float(f)


def to_crs_units(value: float, unit: str, gdf: gpd.GeoDataFrame) -> float:
    """Convert a user distance in `unit` to the layer's CRS linear units."""
    if unit not in LINEAR_UNITS:
        raise ToolError(f"Unsupported linear unit '{unit}'")
    return value * LINEAR_UNITS[unit] / crs_unit_to_meters(gdf)


def align_crs(ctx: RunContext, gdf: gpd.GeoDataFrame, target: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    """Reproject `gdf` to target's CRS if they differ (recorded as an explicit transformation)."""
    require_known_crs(gdf, label)
    if not gdf.crs.equals(target.crs):
        ctx.transformations.append(f"{label}: {gdf.crs.to_string()} -> {target.crs.to_string()} (pyproj)")
        ctx.message(f"Projecting {label} from {gdf.crs.to_string()} to {target.crs.to_string()} for processing.")
        return gdf.to_crs(target.crs)
    return gdf


def handle_geometry_quality(ctx: RunContext, gdf: gpd.GeoDataFrame, label: str, invalid: str) -> gpd.GeoDataFrame:
    """Drop null/empty geometries (reported) and repair/skip/fail invalid geometries per `invalid`."""
    n0 = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    dropped = n0 - len(gdf)
    if dropped:
        ctx.warn(f"{label}: {dropped} features with null/empty geometry excluded.")
    bad = ~shapely.is_valid(gdf.geometry.values)
    nbad = int(bad.sum())
    ctx.counts.setdefault("excluded_null_or_empty", {})[label] = dropped
    ctx.counts.setdefault("invalid_geometry", {})[label] = nbad
    if nbad:
        if invalid == "fail":
            raise ToolError(f"{label}: {nbad} invalid geometries (e.g. "
                            f"{shapely.is_valid_reason(gdf.geometry.values[bad][0])}). "
                            "Choose 'repair' or 'skip' for invalid geometry handling.")
        if invalid == "skip":
            ctx.warn(f"{label}: {nbad} invalid geometries skipped.")
            gdf = gdf[~bad]
        else:
            gdf = gdf.copy()
            gdf.loc[bad, gdf.geometry.name] = shapely.make_valid(gdf.geometry.values[bad])
            ctx.warn(f"{label}: {nbad} invalid geometries repaired in the working copy with make_valid "
                     "(source unchanged).")
    return gdf


INVALID_PARAM_VALUES = ["repair", "skip", "fail"]
