"""Space Time Pattern Mining: Create Space Time Cube By Aggregating Points + Emerging Hot Spot Analysis.

ArcGIS stores a cube as netCDF. Here the cube is an ordinary Gold polygon layer with one feature per
location x time step (LOCATION_ID, TIME_STEP, START_TIME, END_TIME, COUNT, ...), so it can be drawn,
filtered by time step, tabulated and exported like any other layer.
"""
from __future__ import annotations

import math
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from ..jobs import RunContext, ToolError
from ..registry.tools import LINEAR_UNITS, Param, ToolSpec, register
from ..storage.io import FID
from .common import require_projected, to_crs_units

TIME_UNITS = ["years", "months", "weeks", "days"]
MIN_POINTS = 60
MIN_STEPS = 10

PATTERNS = {
    1: "New Hot Spot", 2: "Consecutive Hot Spot", 3: "Intensifying Hot Spot", 4: "Persistent Hot Spot",
    5: "Diminishing Hot Spot", 6: "Sporadic Hot Spot", 7: "Oscillating Hot Spot", 8: "Historical Hot Spot",
    -1: "New Cold Spot", -2: "Consecutive Cold Spot", -3: "Intensifying Cold Spot", -4: "Persistent Cold Spot",
    -5: "Diminishing Cold Spot", -6: "Sporadic Cold Spot", -7: "Oscillating Cold Spot", -8: "Historical Cold Spot",
    0: "No Pattern Detected",
}


# =============================================================================== pure functions
_SUFFIX = re.compile(r"\s*(\(EPSG:\d+\)|\[EPSG:\d+\]|\(\d+\)|Points|Space Time Cube)$")


def base_label(label: str) -> str:
    """'PACP (EPSG:2278) (2) Points' -> 'PACP': keeps chained output names readable."""
    original, prev = label, None
    while prev != label:
        prev, label = label, _SUFFIX.sub("", label).strip()
    return label or original



def parse_times(values: pd.Series) -> pd.Series:
    """Date or text values -> naive datetimes. Unparseable / placeholder values (e.g. 0000/00/00) -> NaT."""
    if pd.api.types.is_datetime64_any_dtype(values):
        s = values
        if getattr(s.dt, "tz", None) is not None:
            s = s.dt.tz_convert("UTC").dt.tz_localize(None)
        return s
    s = values.astype("string").str.strip()
    return pd.to_datetime(s, errors="coerce", format="mixed")


def _offset(unit: str, n: int) -> pd.DateOffset:
    if unit == "weeks":
        return pd.DateOffset(days=7 * n)
    return pd.DateOffset(**{unit: n})


def time_edges(tmin: pd.Timestamp, tmax: pd.Timestamp, interval: int, unit: str, alignment: str = "end_time",
               reference: pd.Timestamp | None = None) -> tuple[list[pd.Timestamp], str]:
    """Bin edges covering [tmin, tmax] and which side is closed.

    end_time: bins end at the last event, each bin includes its end and excludes its start (closed 'right').
    start_time: bins start at the first event, each includes its start and excludes its end (closed 'left').
    reference_time: bins are aligned so one ends at the reference (acts as start_time when the reference is at
    or before the first event).
    """
    if interval < 1:
        raise ToolError("Time step interval must be a whole number >= 1.")
    if alignment == "start_time":
        anchor, closed = tmin, "left"
    elif alignment == "reference_time":
        if reference is None:
            raise ToolError("Reference time alignment needs a reference time.")
        anchor = reference
        closed = "left" if reference <= tmin else "right"
    else:
        anchor, closed = tmax, "right"
    at = lambda k: anchor + _offset(unit, interval * k)  # noqa: E731 - offsets from the anchor avoid month drift
    lo = 0
    while (at(lo) >= tmin) if closed == "right" else (at(lo) > tmin):
        lo -= 1
        if lo < -100000:
            raise ToolError("Too many time steps; use a larger time step interval.")
    hi = 0
    while (at(hi) < tmax) if closed == "right" else (at(hi) <= tmax):
        hi += 1
        if hi > 100000:
            raise ToolError("Too many time steps; use a larger time step interval.")
    return [at(k) for k in range(lo, hi + 1)], closed


def assign_time_steps(times: np.ndarray, edges: list[pd.Timestamp], closed: str) -> np.ndarray:
    e = np.array([np.datetime64(x) for x in edges]).astype("datetime64[ns]")
    t = times.astype("datetime64[ns]")
    side = "left" if closed == "right" else "right"
    return np.searchsorted(e, t, side=side) - 1


def grid_index(x: np.ndarray, y: np.ndarray, origin: tuple[float, float], size: float, shape: str) -> np.ndarray:
    """(n, 2) integer bin keys. Upper-left bin is centred on `origin` (upper-left corner of the extent)."""
    x0, y0 = origin
    if shape == "fishnet":
        col = np.floor((x - x0) / size + 0.5).astype(np.int64)
        row = np.floor((y0 - y) / size + 0.5).astype(np.int64)
        return np.column_stack([row, col])
    # flat-topped hexagons: height (flat to flat) = size, circumradius R = size / sqrt(3)
    R = size / math.sqrt(3.0)
    qf = (x - x0) / (1.5 * R)
    rf = (y0 - y) / size - qf / 2.0
    # cube rounding (x=q, z=r, y=-q-r)
    xs, zs = qf, rf
    ys = -xs - zs
    rx, ry, rz = np.round(xs), np.round(ys), np.round(zs)
    dx, dy, dz = np.abs(rx - xs), np.abs(ry - ys), np.abs(rz - zs)
    fix_x = (dx > dy) & (dx > dz)
    fix_y = ~fix_x & (dy > dz)
    rx = np.where(fix_x, -ry - rz, rx)
    rz = np.where(~fix_x & ~fix_y, -rx - ry, rz)
    return np.column_stack([rz.astype(np.int64), rx.astype(np.int64)])  # (r, q)


def bin_polygon(key: tuple[int, int], origin: tuple[float, float], size: float, shape: str) -> shapely.Polygon:
    x0, y0 = origin
    a, b = int(key[0]), int(key[1])
    if shape == "fishnet":
        cx, cy = x0 + b * size, y0 - a * size
        h = size / 2.0
        return shapely.box(cx - h, cy - h, cx + h, cy + h)
    R = size / math.sqrt(3.0)
    q, r = b, a
    cx, cy = x0 + 1.5 * R * q, y0 - size * (r + q / 2.0)
    return shapely.Polygon([(cx + R * math.cos(math.radians(60 * k)), cy + R * math.sin(math.radians(60 * k)))
                            for k in range(6)])


def _norm_p(z: np.ndarray) -> np.ndarray:
    from math import erfc
    return np.vectorize(lambda v: erfc(abs(v) / math.sqrt(2.0)), otypes=[float])(z)


def mann_kendall(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mann-Kendall trend test per row of `x` (rows = series, columns = time). Returns (z, two-sided p)."""
    x = np.atleast_2d(np.asarray(x, dtype=float))
    n_rows, n = x.shape
    s = np.zeros(n_rows)
    for k in range(1, n):
        s += np.sign(x[:, k:] - x[:, :-k]).sum(axis=1)
    var = np.full(n_rows, n * (n - 1) * (2 * n + 5), dtype=float)
    for i in range(n_rows):
        _, t = np.unique(x[i], return_counts=True)
        t = t[t > 1]
        if len(t):
            var[i] -= float((t * (t - 1) * (2 * t + 5)).sum())
    var /= 18.0
    z = np.zeros(n_rows)
    ok = var > 0
    z[ok & (s > 0)] = (s[ok & (s > 0)] - 1) / np.sqrt(var[ok & (s > 0)])
    z[ok & (s < 0)] = (s[ok & (s < 0)] + 1) / np.sqrt(var[ok & (s < 0)])
    return z, _norm_p(z)


def confidence_bin(z: np.ndarray, p: np.ndarray) -> np.ndarray:
    """-3..3: sign of z times 3/2/1 for 99/95/90 % confidence, 0 when not significant."""
    lvl = np.where(p <= 0.01, 3, np.where(p <= 0.05, 2, np.where(p <= 0.10, 1, 0)))
    return (np.sign(z) * lvl).astype(int)


def fdr_bins(z: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Confidence bins with a Benjamini-Hochberg False Discovery Rate correction at 90/95/99 %."""
    flat_p = p.ravel()
    m = len(flat_p)
    order = np.sort(flat_p)
    ranks = np.arange(1, m + 1)
    level = np.zeros(m, dtype=int)
    for alpha, lv in ((0.10, 1), (0.05, 2), (0.01, 3)):
        ok = order <= alpha * ranks / m
        if ok.any():
            thresh = order[np.nonzero(ok)[0].max()]
            level[flat_p <= thresh] = lv
    return (np.sign(z.ravel()) * level).astype(int).reshape(z.shape)


def neighbor_csr(centroids: np.ndarray, distance: float) -> tuple[np.ndarray, np.ndarray]:
    """CSR (indptr, indices) of locations whose centroid is within `distance` (self included)."""
    tree = shapely.STRtree(centroids)
    src, dst = tree.query(centroids, predicate="dwithin", distance=distance)
    order = np.lexsort((dst, src))
    src, dst = src[order], dst[order]
    indptr = np.zeros(len(centroids) + 1, dtype=np.int64)
    np.add.at(indptr, src + 1, 1)
    return np.cumsum(indptr), dst


def gi_star(x: np.ndarray, indptr: np.ndarray, indices: np.ndarray, time_steps: int) -> np.ndarray:
    """Getis-Ord Gi* z-scores for every bin of an (L, T) cube.

    Binary space-time weights: a bin's neighbours are the locations within the neighbourhood distance
    (itself included) in the same and the `time_steps` preceding time steps. Global window = entire cube.
    """
    n_loc, n_t = x.shape
    n = x.size
    xbar = x.mean()
    s = math.sqrt(max((x ** 2).mean() - xbar ** 2, 0.0))
    if s == 0:
        raise ToolError("Every bin has the same value; hot spot analysis is not possible.")
    spatial = np.add.reduceat(x[indices], indptr[:-1], axis=0)  # every row has >= 1 neighbour (itself)
    c = np.cumsum(spatial, axis=1)
    window = c.copy()
    k = int(time_steps)
    if k + 1 < n_t:
        window[:, k + 1:] = c[:, k + 1:] - c[:, :-(k + 1)]
    deg = np.diff(indptr).astype(float)
    tcount = np.minimum(np.arange(n_t), k) + 1
    w = deg[:, None] * tcount[None, :]
    denom = s * np.sqrt(np.maximum((n * w - w ** 2) / (n - 1), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(denom > 0, (window - xbar * w) / denom, 0.0)
    return z


def classify_patterns(hs_bin: np.ndarray, trend_bin: np.ndarray) -> np.ndarray:
    """ArcGIS emerging hot spot categories (1..8 hot, -1..-8 cold, 0 none) per location."""
    n_loc, n_t = hs_bin.shape
    out = np.zeros(n_loc, dtype=int)
    for i in range(n_loc):
        for sign in (1, -1):
            sig = (hs_bin[i] * sign) > 0
            opp = (hs_bin[i] * sign) < 0
            share = sig.sum() / n_t
            if sig[-1]:
                run = 0
                for v in sig[::-1]:
                    if not v:
                        break
                    run += 1
                before = sig[: n_t - run].any()
                if sig.sum() == 1:
                    cat = 1  # new
                elif share >= 0.9:
                    t = trend_bin[i] * sign
                    cat = 3 if t > 0 else 5 if t < 0 else 4  # intensifying / diminishing / persistent
                elif run >= 2 and not before:
                    cat = 2  # consecutive
                elif opp.any():
                    cat = 7  # oscillating
                else:
                    cat = 6  # sporadic
                out[i] = sign * cat
                break
            if share >= 0.9:
                out[i] = sign * 8  # historical
                break
    return out


def default_neighborhood_distance(centroids: np.ndarray, weights: np.ndarray, bin_size: float) -> float:
    """Kernel-density default search radius on location centroids (weighted by total value), never less
    than the distance that reaches first-order (queen) neighbours of a grid bin."""
    xy = shapely.get_coordinates(centroids)
    w = np.clip(np.asarray(weights, dtype=float), 0, None)
    if w.sum() <= 0:
        w = np.ones(len(xy))
    mc = (xy * w[:, None]).sum(0) / w.sum()
    d = np.hypot(xy[:, 0] - mc[0], xy[:, 1] - mc[1])
    sd = math.sqrt(((d ** 2) * w).sum() / w.sum())
    order = np.argsort(d)
    cw = np.cumsum(w[order])
    dm = float(d[order][np.searchsorted(cw, cw[-1] / 2.0)])
    n = max(w.sum(), 1.0)
    radius = 0.9 * min(sd, math.sqrt(1.0 / math.log(2.0)) * dm) * n ** -0.2
    return max(radius, math.sqrt(2.0) * bin_size * 1.001)


# =============================================================================== executors
def create_space_time_cube(ctx: RunContext, input_layer: str, time_field: str, time_step_interval: float = 1,
                           time_step_unit: str = "months", time_step_alignment: str = "end_time",
                           reference_time: str | None = None, distance_interval: float | None = None,
                           distance_units: str = "feet", aggregation_shape: str = "fishnet",
                           summary_field: str | None = None, summary_statistic: str = "sum",
                           use_selection: bool = True) -> dict:
    info = ctx.registry.get(input_layer)
    gdf = ctx.input_gdf(input_layer, "input", use_selection)
    require_projected(gdf, info["label"])
    n_in = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    n_nogeom = n_in - len(gdf)
    if n_nogeom:
        ctx.warn(f"{n_nogeom} features with null/empty geometry excluded.")
    multi = int((gdf.geometry.geom_type == "MultiPoint").sum())
    if multi:
        ctx.warn(f"{multi} multipoint features are aggregated at their centroid.")
    times = parse_times(gdf[time_field])
    n_notime = int(times.isna().sum())
    if n_notime:
        samples = gdf.loc[times.isna(), time_field].astype(str).value_counts().head(3).index.tolist()
        ctx.warn(f"{n_notime} features have no usable date in '{time_field}' (e.g. {samples}) and are excluded "
                 "- unknown dates are never guessed.")
    keep = times.notna().to_numpy().copy()
    values = None
    n_nullsum = 0
    if summary_field:
        values = pd.to_numeric(gdf[summary_field], errors="coerce")
        n_nullsum = int((values.isna() & times.notna()).sum())
        if n_nullsum:
            ctx.warn(f"{n_nullsum} features have a null/non-numeric '{summary_field}' and are excluded "
                     "(ArcGIS drops features with null summary values).")
        keep &= values.notna().to_numpy()
    gdf, times = gdf[keep], times[keep]
    if values is not None:
        values = values[keep].to_numpy(dtype=float)
    if len(gdf) < MIN_POINTS:
        raise ToolError(f"Only {len(gdf)} usable points; Create Space Time Cube needs at least {MIN_POINTS}.")

    tmin, tmax = times.min(), times.max()
    ref = None
    if time_step_alignment == "reference_time":
        ref = pd.to_datetime(reference_time, errors="coerce") if reference_time else None
        if ref is None or pd.isna(ref):
            raise ToolError("Reference time alignment needs a valid reference time (e.g. 2026-01-01).")
    interval = int(time_step_interval)
    if interval != time_step_interval:
        raise ToolError("Time step interval must be a whole number.")
    edges, closed = time_edges(tmin, tmax, interval, time_step_unit, time_step_alignment, ref)
    n_t = len(edges) - 1
    if n_t < MIN_STEPS:
        raise ToolError(f"The data span {tmin.date()} to {tmax.date()} gives only {n_t} time steps of "
                        f"{interval} {time_step_unit}; at least {MIN_STEPS} are needed for the trend test. "
                        "Use a smaller time step interval.")
    step = assign_time_steps(times.to_numpy(), edges, closed)

    pts = shapely.centroid(gdf.geometry.values)
    xy = shapely.get_coordinates(pts)
    minx, miny, maxx, maxy = xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max()
    if distance_interval:
        size = to_crs_units(float(distance_interval), distance_units, gdf)
        size_user = float(distance_interval)
    else:
        size = max(maxx - minx, maxy - miny) / 100.0
        if size <= 0:
            raise ToolError("All points share one location; provide a distance interval.")
        size_user = size * gdf.crs.axis_info[0].unit_conversion_factor / LINEAR_UNITS[distance_units]
        ctx.message(f"Distance interval not given: default = longest extent side / 100 = {size_user:,.1f} "
                    f"{distance_units}.")
    origin = (float(minx), float(maxy))
    keys = grid_index(xy[:, 0], xy[:, 1], origin, size, aggregation_shape)
    uniq, loc = np.unique(keys, axis=0, return_inverse=True)
    loc = loc.ravel()
    n_loc = len(uniq)
    if n_loc * n_t > 5_000_000:
        raise ToolError(f"The cube would have {n_loc * n_t:,} bins; use a larger distance or time interval.")
    ctx.progress(0.4)

    counts = np.zeros((n_loc, n_t))
    np.add.at(counts, (loc, step), 1)
    summary = None
    if values is not None:
        if summary_statistic == "sum":
            summary = np.zeros((n_loc, n_t))
            np.add.at(summary, (loc, step), values)
        elif summary_statistic == "mean":
            tot = np.zeros((n_loc, n_t))
            np.add.at(tot, (loc, step), values)
            with np.errstate(invalid="ignore", divide="ignore"):
                summary = np.where(counts > 0, tot / np.where(counts > 0, counts, 1), 0.0)
        else:
            init = -np.inf if summary_statistic == "max" else np.inf
            summary = np.full((n_loc, n_t), init)
            (np.maximum if summary_statistic == "max" else np.minimum).at(summary, (loc, step), values)
            summary[~np.isfinite(summary)] = 0.0

    polys = [bin_polygon(tuple(k), origin, size, aggregation_shape) for k in uniq]
    starts = [edges[i] for i in range(n_t)]
    ends = [edges[i + 1] for i in range(n_t)]
    rows = {
        "LOCATION_ID": np.repeat(np.arange(n_loc), n_t),
        "TIME_STEP": np.tile(np.arange(n_t), n_loc),
        "START_TIME": np.tile(np.array(starts, dtype="datetime64[ns]"), n_loc),
        "END_TIME": np.tile(np.array(ends, dtype="datetime64[ns]"), n_loc),
        "COUNT": counts.ravel().astype(np.int64),
    }
    sum_name = None
    if summary is not None:
        sum_name = f"{summary_statistic.upper()}_{summary_field}"[:64]
        rows[sum_name] = summary.ravel()
    cube = gpd.GeoDataFrame(rows, geometry=np.repeat(np.array(polys, dtype=object), n_t), crs=gdf.crs)
    ctx.progress(0.6)

    z, p = mann_kendall(counts)
    oz, op = mann_kendall(counts.sum(axis=0))
    trend = gpd.GeoDataFrame({
        "LOCATION_ID": np.arange(n_loc),
        "COUNT_TOTAL": counts.sum(axis=1).astype(np.int64),
        "STEPS_WITH_DATA": (counts > 0).sum(axis=1).astype(np.int64),
        "COUNT_TREND_ZSCORE": z, "COUNT_TREND_PVALUE": p, "COUNT_TREND_BIN": confidence_bin(z, p),
    }, geometry=polys, crs=gdf.crs)
    direction = "not statistically significant" if op[0] > 0.10 else ("increasing" if oz[0] > 0 else "decreasing")
    ctx.message(f"Cube: {n_loc:,} locations x {n_t} time steps of {interval} {time_step_unit} = {n_loc * n_t:,} "
                f"bins ({tmin.date()} to {tmax.date()}, alignment {time_step_alignment}, {aggregation_shape} "
                f"{size_user:,.1f} {distance_units}).")
    ctx.message(f"Overall data trend: {direction} (Mann-Kendall z = {oz[0]:.3f}, p = {op[0]:.4f}).")
    zero = float((counts == 0).mean())
    ctx.message(f"{zero:.0%} of bins contain zero points" + (" - the cube is sparse." if zero > 0.9 else "."))
    ctx.counts.update({
        "input_features": n_in, "excluded_null_geometry": n_nogeom, "excluded_unknown_time": n_notime,
        "excluded_null_summary": n_nullsum, "aggregated_points": int(len(gdf)), "locations": n_loc,
        "time_steps": n_t, "bins": n_loc * n_t, "zero_bins_pct": round(zero * 100, 2),
        "bin_size": round(size_user, 4), "bin_size_units": distance_units,
        "first_time": str(tmin), "last_time": str(tmax),
        "overall_trend": {"direction": direction, "z": float(oz[0]), "p": float(op[0])},
        "trend_bins": {str(k): int(v) for k, v in zip(*np.unique(confidence_bin(z, p), return_counts=True))},
        "series": {"start": [str(s.date()) for s in starts], "end": [str(e.date()) for e in ends],
                   "count": counts.sum(axis=0).astype(int).tolist(),
                   **({sum_name: [round(float(v), 6) for v in summary.sum(axis=0)]} if sum_name else {})},
    })
    base = base_label(info["label"])
    cube_lyr = ctx.write_layer(cube, label=f"{base} Space Time Cube")
    trend_lyr = ctx.write_layer(trend, label=f"{base} Cube Trends", role="trend")
    return {"kind": "layer", "layer_id": cube_lyr["layer_id"], "trend_layer_id": trend_lyr["layer_id"],
            "summary_field": sum_name}


def emerging_hot_spot_analysis(ctx: RunContext, input_cube: str, analysis_field: str = "COUNT",
                               location_field: str = "LOCATION_ID", time_step_field: str = "TIME_STEP",
                               neighborhood_distance: float | None = None, distance_units: str = "feet",
                               neighborhood_time_step: float = 1, use_selection: bool = False) -> dict:
    info = ctx.registry.get(input_cube)
    gdf = ctx.input_gdf(input_cube, "input", use_selection=False)
    require_projected(gdf, info["label"])
    for f in (analysis_field, location_field, time_step_field):
        if f not in gdf.columns:
            raise ToolError(f"Field '{f}' not found; the input must be a space-time cube layer.")
    vals = pd.to_numeric(gdf[analysis_field], errors="coerce")
    if vals.isna().any():
        raise ToolError(f"{int(vals.isna().sum())} bins have a null '{analysis_field}'.")
    locs, loc_idx = np.unique(gdf[location_field].to_numpy(), return_inverse=True)
    steps, t_idx = np.unique(gdf[time_step_field].to_numpy(), return_inverse=True)
    n_loc, n_t = len(locs), len(steps)
    if n_loc * n_t != len(gdf) or pd.Series(loc_idx * n_t + t_idx).duplicated().any():
        raise ToolError("The input is not a complete space-time cube (every location needs exactly one bin per "
                        "time step). Create it with Create Space Time Cube.")
    if n_t < MIN_STEPS:
        raise ToolError(f"The cube has {n_t} time steps; at least {MIN_STEPS} are needed.")
    if n_loc < 2:
        raise ToolError("The cube needs at least two locations.")
    x = np.zeros((n_loc, n_t))
    x[loc_idx, t_idx] = vals.to_numpy(dtype=float)
    first = np.full(n_loc, -1)
    first[loc_idx[::-1]] = np.arange(len(gdf))[::-1]
    geoms = gdf.geometry.values[first]
    cents = shapely.centroid(geoms)
    bin_size = float(np.sqrt(np.median(shapely.area(geoms)))) if (shapely.area(geoms) > 0).any() else 0.0

    if neighborhood_distance:
        dist = to_crs_units(float(neighborhood_distance), distance_units, gdf)
    else:
        dist = default_neighborhood_distance(cents, x.sum(axis=1), bin_size)
    dist_user = dist * gdf.crs.axis_info[0].unit_conversion_factor / LINEAR_UNITS[distance_units]
    k = int(neighborhood_time_step)
    if k < 0 or k != neighborhood_time_step:
        raise ToolError("Neighborhood time step must be a whole number >= 0.")
    indptr, indices = neighbor_csr(cents, dist)
    deg = np.diff(indptr)
    ctx.message(f"Neighborhood distance {dist_user:,.1f} {distance_units}"
                f"{'' if neighborhood_distance else ' (default)'}; neighborhood time step {k}; "
                f"spatial neighbors per location: min {deg.min()}, median {int(np.median(deg))}, max {deg.max()} "
                "(self included).")
    if deg.max() <= 1:
        ctx.warn("No location has a spatial neighbor at this distance; increase the neighborhood distance.")
    ctx.progress(0.3)

    z = gi_star(x, indptr, indices, k)
    p = _norm_p(z)
    hs = fdr_bins(z, p)
    ez, ep = mann_kendall(z)
    vz, vp = mann_kendall(x)
    ebin, vbin = confidence_bin(ez, ep), confidence_bin(vz, vp)
    cat = classify_patterns(hs, ebin)
    ctx.progress(0.7)

    v = analysis_field.upper()
    loc_out = gpd.GeoDataFrame({
        location_field: locs,
        "CATEGORY": cat,
        "PATTERN": [PATTERNS[c] for c in cat],
        f"{v}_TOTAL": x.sum(axis=1),
        "NUM_TIME_STEPS": np.full(n_loc, n_t),
        "NUM_HOT": (hs > 0).sum(axis=1), "NUM_COLD": (hs < 0).sum(axis=1),
        "FINAL_HS_BIN": hs[:, -1],
        f"EMERGING_{v}_TREND_ZSCORE": ez, f"EMERGING_{v}_TREND_PVALUE": ep, f"EMERGING_{v}_TREND_BIN": ebin,
        f"{v}_TREND_ZSCORE": vz, f"{v}_TREND_PVALUE": vp, f"{v}_TREND_BIN": vbin,
    }, geometry=geoms, crs=gdf.crs)
    bins = gdf.drop(columns=[FID]).copy()
    bins[f"EMERGING_{v}_HS_ZSCORE"] = z[loc_idx, t_idx]
    bins[f"EMERGING_{v}_HS_PVALUE"] = p[loc_idx, t_idx]
    bins[f"EMERGING_{v}_HS_BIN"] = hs[loc_idx, t_idx]

    cats = {PATTERNS[c]: int(n) for c, n in zip(*np.unique(cat, return_counts=True))}
    for name, n in sorted(cats.items(), key=lambda kv: -kv[1]):
        ctx.message(f"  {name}: {n:,} locations")
    ctx.counts.update({
        "locations": n_loc, "time_steps": n_t, "bins": int(x.size),
        "neighborhood_distance": round(dist_user, 3), "neighborhood_distance_units": distance_units,
        "neighborhood_time_step": k, "hot_bins": int((hs > 0).sum()), "cold_bins": int((hs < 0).sum()),
        "categories": cats,
        "series": {"value": [round(float(v), 6) for v in x.sum(axis=0)],
                   "hot_bins": (hs > 0).sum(axis=0).astype(int).tolist(),
                   "cold_bins": (hs < 0).sum(axis=0).astype(int).tolist()},
    })
    base = base_label(info["label"])
    loc_lyr = ctx.write_layer(loc_out, label=f"{base} Emerging Hot Spots")
    bin_lyr = ctx.write_layer(bins, label=f"{base} Hot Spot Bins", role="bins")
    return {"kind": "layer", "layer_id": loc_lyr["layer_id"], "bins_layer_id": bin_lyr["layer_id"]}


# =============================================================================== registration
register(ToolSpec(
    id="stpm.create_space_time_cube",
    name="Create Space Time Cube",
    category="Space Time Pattern Mining",
    toolbox="Space Time Pattern Mining",
    summary="Aggregates points into space-time bins (fishnet or hexagon grid x time steps) and tests each "
            "location for a trend.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/space-time-pattern-mining/"
                  "create-space-time-cube.htm",
    executor=create_space_time_cube,
    output_type="layer",
    params=[
        Param("input_layer", "Input features", "layer", geometry=["Point"], crs_requirement="projected",
              description="Points with a date. For pipes (lines) run Feature To Point first."),
        Param("time_field", "Time field", "field", parent="input_layer", field_types=["date", "string"],
              description="Date field, or text dates such as 2024-06-14. Unknown dates are excluded, not guessed."),
        Param("time_step_interval", "Time step interval", "number", default=3, min=1, role="parameter"),
        Param("time_step_unit", "Time step unit", "enum", default="months", values=TIME_UNITS, role="parameter"),
        Param("time_step_alignment", "Time step alignment", "enum", default="end_time",
              values=["end_time", "start_time", "reference_time"],
              value_labels={"end_time": "End time", "start_time": "Start time", "reference_time": "Reference time"},
              role="parameter"),
        Param("reference_time", "Reference time", "string", required=True, role="parameter",
              visible_when={"time_step_alignment": ["reference_time"]}, description="e.g. 2026-01-01"),
        Param("distance_interval", "Distance interval (bin size)", "number", required=False, min=0.000001,
              role="parameter", description="Leave empty for the default (longest extent side / 100)."),
        Param("distance_units", "Distance units", "linear_unit", default="feet", values=list(LINEAR_UNITS),
              role="parameter"),
        Param("aggregation_shape", "Aggregation shape type", "enum", default="fishnet",
              values=["fishnet", "hexagon"], value_labels={"fishnet": "Fishnet grid", "hexagon": "Hexagon grid"},
              role="parameter"),
        Param("summary_field", "Summary field", "field", required=False, parent="input_layer",
              field_types=["integer", "double"], role="parameter"),
        Param("summary_statistic", "Summary statistic", "enum", default="sum",
              values=["sum", "mean", "min", "max"], role="parameter"),
    ],
    known_differences=[
        "Output is two Gold layers (cube bins and per-location trends) instead of a netCDF cube.",
        "Default distance interval uses only the 'longest extent side / 100' rule; ArcGIS takes the larger of "
        "that and a spatial-distribution estimate.",
        "Time step interval is required (default 3 months); ArcGIS can derive it with histogram bin-width "
        "optimisers.",
        "Empty bins are filled with zeros (ArcGIS ZEROS fill); spatial / space-time / temporal-trend fills, "
        "defined locations and template cubes are not implemented.",
        "Locations are numbered by grid row/column order; ArcGIS's LOCATION_ID numbering may differ.",
        "Text date fields are parsed; ArcGIS requires a date field.",
    ],
))

register(ToolSpec(
    id="stpm.emerging_hot_spot_analysis",
    name="Emerging Hot Spot Analysis",
    category="Space Time Pattern Mining",
    toolbox="Space Time Pattern Mining",
    summary="Finds new, intensifying, persistent, diminishing, sporadic, oscillating and historical hot and "
            "cold spots in a space-time cube.",
    reference_url="https://pro.arcgis.com/en/pro-app/latest/tool-reference/space-time-pattern-mining/"
                  "emerginghotspots.htm",
    executor=emerging_hot_spot_analysis,
    output_type="layer",
    params=[
        Param("input_cube", "Input space time cube", "layer", geometry=["Polygon"], crs_requirement="projected",
              description="A cube layer made by Create Space Time Cube."),
        Param("analysis_field", "Analysis variable", "field", default="COUNT", parent="input_cube",
              field_types=["integer", "double"], role="parameter"),
        Param("location_field", "Location ID field", "field", default="LOCATION_ID", parent="input_cube",
              role="parameter"),
        Param("time_step_field", "Time step field", "field", default="TIME_STEP", parent="input_cube",
              field_types=["integer"], role="parameter"),
        Param("neighborhood_distance", "Neighborhood distance", "number", required=False, min=0.000001,
              role="parameter", description="Leave empty for the default."),
        Param("distance_units", "Distance units", "linear_unit", default="feet", values=list(LINEAR_UNITS),
              role="parameter"),
        Param("neighborhood_time_step", "Neighborhood time step", "number", default=1, min=0, role="parameter",
              description="Number of preceding time steps included in each bin's neighborhood."),
    ],
    known_differences=[
        "Fixed distance conceptualization and the entire-cube global window only; K nearest neighbors, "
        "contiguity, number of spatial neighbors, polygon analysis mask and other global windows are not "
        "implemented.",
        "Default neighborhood distance: kernel-density default search radius on location centroids weighted by "
        "the analysis variable, never less than the first-order queen distance (sqrt 2 x bin size). ArcGIS adapts "
        "the same formula but does not publish the exact adaptation, so defaults can differ.",
        "A bin counts as a significant hot/cold spot at >= 90 % confidence after FDR correction (HS_BIN != 0); "
        "the clustering trend is significant at >= 90 % (TREND_BIN != 0). ArcGIS does not document these "
        "thresholds.",
        "The 90 % rule is applied as share >= 0.9 of all time steps, without rounding.",
        "Results are written to new Gold layers (locations + bins) instead of into the netCDF cube.",
    ],
))
