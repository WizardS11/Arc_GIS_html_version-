"""Copy the City dashboard reference layers into this project (read-only sources stay untouched).

Two collections are copied from the Dashboard_requirement workspace:

1. The shared Houston map library (``map-library/manifest.json``): every layer is stored there as
   display tiles (``DK.mapAssets.register(id, FeatureCollection)``, EPSG:4326). The tiles of each layer
   are merged, de-duplicated by the library feature id and written to one GeoParquet file per layer in
   ``data/city_library/``. Attribute names and values are kept; epoch-millisecond date columns are
   stored as datetimes (rule below, every conversion is listed in the report).
2. The flowmeter-25-basins dashboard GeoJSON layers: copied byte-for-byte to
   ``data/flowmeter_25_basins/``.

The script then writes ``config/city_layers.yaml`` - the catalog the workbench offers under
"City layer library". Layers are registered on demand from the app (large layers take a while).

    .venv\\Scripts\\python.exe scripts\\import_city_layers.py [--source D:\\City_Project\\Dashboard_requirement]
        [--only gravity_mains,parcels] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(r"D:\City_Project\Dashboard_requirement")
LIB_OUT = PROJECT_ROOT / "data" / "city_library"
FM_OUT = PROJECT_ROOT / "data" / "flowmeter_25_basins"
CATALOG = PROJECT_ROOT / "config" / "city_layers.yaml"
REPORT = PROJECT_ROOT / "data" / "city_library" / "IMPORT_REPORT.json"

WRAP_RE = re.compile(r'^\s*DK\.mapAssets\.register\(\s*"[^"]*"\s*,', re.S)
DATE_NAME_RE = re.compile(r"(DATE|_DT$|^DT_|INSTALLED|REMOVED|LASTUPDATE|_TIME$|^TIME_)", re.I)
# 1800-01-01 .. 2100-01-01. The sources use 1899-12-30 as a "no date" placeholder; it is kept as written.
EPOCH_MS_MIN, EPOCH_MS_MAX = -5_364_662_400_000, 4_102_444_800_000

FM_LABELS = {
    "basin_boundaries": "Basin Boundaries (25 basins)",
    "cleanout_25b": "Cleanouts (25 basins)",
    "flowmeter_boundaries": "Flowmeter Boundaries (25 basins)",
    "flowmeters_current": "Flowmeters - current (25 basins)",
    "gravity_mains_25b": "Gravity Mains (25 basins)",
    "macp": "MACP Manhole Inspections (25 basins)",
    "manholes": "Manholes (25 basins)",
    "open_ditches_25b": "Open Ditches (25 basins)",
    "pacp": "PACP Pipe Inspections (25 basins)",
    "parcels_hcad": "HCAD Parcels (25 basins)",
    "pavement_edge": "Pavement Edge (25 basins)",
    "service_laterals": "Service Laterals (25 basins)",
    "stormwaterjunction": "Stormwater Junctions (25 basins)",
    "stormwaterline": "Stormwater Lines (25 basins)",
}
FM_COLORS = {
    "pacp": "#d35400", "macp": "#8e44ad", "manholes": "#0d4f86", "gravity_mains_25b": "#2b7bbd",
    "service_laterals": "#7cb342", "flowmeters_current": "#c62828", "basin_boundaries": "#0f2a43",
    "flowmeter_boundaries": "#b45309", "cleanout_25b": "#00897b", "open_ditches_25b": "#00838f",
    "parcels_hcad": "#8d99a6", "pavement_edge": "#5d6d7e", "stormwaterjunction": "#3949ab",
    "stormwaterline": "#1e88e5",
}
GEOM_TYPE = {"line": "LineString", "point": "Point", "polygon": "Polygon"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_tile(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = WRAP_RE.match(text)
    if not m:
        raise ValueError(f"{path} is not a DK.mapAssets tile")
    body = text[m.end():].rstrip().rstrip(";").rstrip()
    if not body.endswith(")"):
        raise ValueError(f"{path}: unexpected tile ending")
    return json.loads(body[:-1])


def date_columns(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        if not DATE_NAME_RE.search(str(c)):
            continue
        s = df[c]
        if not (pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)):
            continue
        v = s.dropna().to_numpy(dtype=float)
        if not len(v):
            continue
        if np.all(np.mod(v, 1) == 0) and v.min() >= EPOCH_MS_MIN and v.max() <= EPOCH_MS_MAX \
                and np.abs(v).max() > 1e10:  # >1e10 ms excludes plain years / small integers
            out.append(c)
    return out


def convert_library_layer(lib_root: Path, layer: dict, out: Path) -> dict:
    t0 = time.perf_counter()
    key = layer.get("featureKey") or "_map_feature_id"
    frames, geoms, seen, dup = [], [], set(), 0
    for tile in layer["tiles"]:
        fc = read_tile(lib_root / tile["url"])
        recs, gs = [], []
        for f in fc["features"]:
            fid = f.get("id")
            if fid is not None:
                if fid in seen:
                    dup += 1
                    continue
                seen.add(fid)
            props = dict(f.get("properties") or {})
            props.setdefault(key, fid)
            recs.append(props)
            gs.append(f.get("geometry"))
        if recs:
            frames.append(pd.DataFrame.from_records(recs))
            geoms.append(shapely.from_geojson(np.array([json.dumps(g) if g else None for g in gs], dtype=object),
                                              on_invalid="ignore"))
    df = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    geom = np.concatenate(geoms) if geoms else np.array([], dtype=object)
    for c in df.columns:  # JSON mixes int and float for one numeric field -> keep it numeric
        if df[c].dtype == object:
            kinds = {type(v) for v in df[c].dropna()}
            if kinds and kinds <= {int, float}:
                df[c] = pd.to_numeric(df[c])
    conv = date_columns(df)
    for c in conv:
        df[c] = pd.to_datetime(df[c], unit="ms", errors="coerce")
    for c in df.columns:  # tiles may infer different scalar types for the same field; keep a single type
        if df[c].dtype == object:
            kinds = {type(v) for v in df[c].dropna().head(5000)}
            if len(kinds) > 1:
                df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    gdf = gpd.GeoDataFrame(df, geometry=gpd.GeoSeries(geom, crs="EPSG:4326"))
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out, index=False)
    return {"layer": layer["id"], "features": int(len(gdf)), "tiles": len(layer["tiles"]),
            "duplicate_tile_copies_removed": dup, "expected_total": layer.get("totalCount"),
            "epoch_ms_columns_converted_to_datetime": conv, "seconds": round(time.perf_counter() - t0, 1),
            "output": str(out.relative_to(PROJECT_ROOT)), "sha256": sha256(out)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--only", default="", help="comma-separated library layer ids")
    ap.add_argument("--force", action="store_true", help="rebuild layers that were already copied")
    args = ap.parse_args()
    src = args.source
    lib_root = src / "map-library"
    manifest = json.loads((lib_root / "manifest.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {"library": {}}
    report.update({"source_root": str(src), "library_id": manifest.get("id"),
                   "library_version": manifest.get("version"), "run_at": datetime.now(timezone.utc).isoformat()})
    catalog: list[dict] = []

    for i, layer in enumerate(manifest["layers"], 1):
        lid = layer["id"]
        out = LIB_OUT / f"{lid}.parquet"
        if (not only or lid in only) and (args.force or not out.exists()):
            print(f"[{i}/{len(manifest['layers'])}] {lid}: {len(layer['tiles'])} tiles ...", flush=True)
            r = convert_library_layer(lib_root, layer, out)
            report["library"][lid] = r
            print(f"    {r['features']:,} features (library total {r['expected_total']:,}) in {r['seconds']} s",
                  flush=True)
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        src_info = layer.get("source") or {}
        catalog.append({
            "layer_id": f"city_{lid}",
            "label": layer["label"],
            "group": layer.get("group") or "City library",
            "source": {"uri": f"${{DATA_ROOT}}/city_library/{lid}.parquet", "format": "geoparquet",
                       "refresh_policy": "manual"},
            "geometry": {"type": GEOM_TYPE.get(layer.get("geometry"), "Unknown")},
            "display": {"color": (layer.get("style") or {}).get("color") or (layer.get("style") or {}).get("fillColor"),
                        "min_zoom": layer.get("minZoom") or 0, "popup": layer.get("popup") or []},
            "metadata": {"collection": "Houston map library", "library_version": manifest.get("version"),
                         "library_layer_id": lid, "feature_count": layer.get("totalCount"),
                         "count_unit": layer.get("countUnit"), "original_source": src_info.get("path"),
                         "source_snapshot": src_info.get("snapshot"),
                         "observation_date": src_info.get("observationDate"),
                         "display_copy": "Library display payload in EPSG:4326 (original GIS is EPSG:2278)."},
            "permissions": {"source_read_only": True, "allow_derived_outputs": True, "allow_source_edits": False},
        })

    fm_src = src / "dashboard-kit" / "dashboard-kit" / "dashboards" / "flowmeter-25-basins" / "layers"
    FM_OUT.mkdir(parents=True, exist_ok=True)
    report.setdefault("flowmeter_25_basins", {})
    for p in sorted(fm_src.glob("*.geojson")):
        dest = FM_OUT / p.name
        if args.force or not dest.exists() or dest.stat().st_size != p.stat().st_size:
            shutil.copy2(p, dest)
            report["flowmeter_25_basins"][p.stem] = {"bytes": dest.stat().st_size, "sha256": sha256(dest),
                                                     "copied_from": str(p)}
            print(f"copied {p.name}", flush=True)
        catalog.append({
            "layer_id": f"fm25_{p.stem}",
            "label": FM_LABELS.get(p.stem, p.stem.replace("_", " ").title()),
            "group": "Flowmeter study - 25 basins",
            "source": {"uri": f"${{DATA_ROOT}}/flowmeter_25_basins/{p.name}", "format": "geojson",
                       "refresh_policy": "manual"},
            "display": {"color": FM_COLORS.get(p.stem), "min_zoom": 0, "popup": []},
            "metadata": {"collection": "flowmeter-25-basins dashboard", "original_source": str(p)},
            "permissions": {"source_read_only": True, "allow_derived_outputs": True, "allow_source_edits": False},
        })

    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    header = ("# City layer library catalog - generated by scripts/import_city_layers.py. Do not edit by hand;\n"
              "# re-run the script. Entries are offered in the workbench (Add data > City layer library) and\n"
              "# registered on demand. Sources are read-only copies; outputs are always new Gold layers.\n")
    CATALOG.write_text(header + yaml.safe_dump({"layers": catalog}, sort_keys=False, allow_unicode=True),
                       encoding="utf-8")
    print(f"catalog: {len(catalog)} layers -> {CATALOG.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
