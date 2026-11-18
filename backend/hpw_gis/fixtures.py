"""Synthetic, non-sensitive QA fixtures (spec §14.3). Entirely fabricated - NOT Houston production data.

Coordinates are placed near downtown Houston in EPSG:2278 (NAD83 / Texas South Central, US survey feet)
so that basemaps line up, but every asset, ID and attribute is synthetic.

Deliberate QA conditions:
  manholes      - Point,  duplicate MH_NUMBER ('MH-021'), one null MH_NUMBER, rim elevation nulls
  gravity_mains - Line,   branched tree to an outlet, disconnected pair, directed cycle, a pipe digitized
                          against flow, an orphan reference (MH-999), a multipart pipe, null INSTALL_YR
  sewer_basins  - Polygon overlapping basins, a hole, a multipart basin, an invalid self-intersecting bowtie
  level_sensors - CSV lon/lat in EPSG:4326 (geographic -> distance tools gated), duplicated site_name
  sso_events    - zipped Shapefile WITHOUT .prj (unknown CRS -> must Define Projection)
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon

CRS_LOCAL = "EPSG:2278"
ORIGIN_LONLAT = (-95.3700, 29.7600)


def _origin() -> tuple[float, float]:
    t = Transformer.from_crs("EPSG:4326", CRS_LOCAL, always_xy=True)
    x, y = t.transform(*ORIGIN_LONLAT)
    return round(x, -2), round(y, -2)


MANHOLES = [
    # MH_NUMBER, dx, dy, rim
    ("MH-001", 0, 0, 52.1), ("MH-002", 400, 0, 51.8), ("MH-003", 800, 0, 51.2), ("MH-004", 1200, 0, 50.9),
    ("MH-005", 1600, 0, 50.1),
    ("MH-010", 400, 800, 53.0), ("MH-011", 400, 400, 52.4),
    ("MH-020", 1200, 800, 52.8), ("MH-021", 1200, 400, 52.2),
    ("MH-030", 800, -800, 53.4), ("MH-031", 800, -400, 52.6),
    ("MH-040", 2400, 1200, 49.9), ("MH-041", 2800, 1200, None),
    ("MH-050", 2400, -800, 50.5), ("MH-051", 2800, -800, 50.3), ("MH-052", 2800, -1200, None),
    ("MH-021", 1250, 420, 52.2),  # duplicate natural key (data-entry duplicate)
    (None, 2000, 400, 51.0),       # missing MH_NUMBER
]

PIPES = [
    # UFID, US, DS, diameter_in, material, install_yr, reversed_digitizing
    ("P-0001", "MH-001", "MH-002", 12, "VCP", 1962, False),
    ("P-0002", "MH-002", "MH-003", 15, "VCP", 1962, False),
    ("P-0003", "MH-003", "MH-004", 18, "RCP", 1975, False),
    ("P-0004", "MH-004", "MH-005", 24, "RCP", 1975, False),
    ("P-0010", "MH-010", "MH-011", 8, "PVC", 1998, False),
    ("P-0011", "MH-011", "MH-002", 8, "PVC", 1998, True),   # digitized DS->US: geometry order != flow
    ("P-0020", "MH-020", "MH-021", 10, "PVC", None, False),
    ("P-0021", "MH-021", "MH-004", 10, "PVC", 2004, False),
    ("P-0030", "MH-030", "MH-031", 8, "DIP", 1988, False),
    ("P-0031", "MH-031", "MH-003", 12, "DIP", 1988, False),
    ("P-0040", "MH-040", "MH-041", 8, "PVC", 2010, False),  # disconnected component
    ("P-0050", "MH-050", "MH-051", 8, "VCP", 1955, False),  # directed cycle 050->051->052->050
    ("P-0051", "MH-051", "MH-052", 8, "VCP", 1955, False),
    ("P-0052", "MH-052", "MH-050", 8, "VCP", 1955, False),
    ("P-0060", "MH-005", "MH-999", 30, "RCP", 1980, False),  # orphan: MH-999 does not exist
]


def build(out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ox, oy = _origin()
    pos = {}
    mh_rows = []
    for i, (num, dx, dy, rim) in enumerate(MANHOLES):
        pt = Point(ox + dx, oy + dy)
        if num and num not in pos:
            pos[num] = pt
        mh_rows.append({"UFID": f"MH{i + 1:05d}", "MH_NUMBER": num, "RIM_ELEV": rim,
                        "STATUS": "ACTIVE" if i % 7 else "ABANDONED", "geometry": pt})
    manholes = gpd.GeoDataFrame(mh_rows, crs=CRS_LOCAL)

    pipe_rows = []
    for ufid, us, ds, dia, mat, yr, rev in PIPES:
        a = pos[us]
        b = pos.get(ds, Point(a.x + 400, a.y - 200))
        line = LineString([(b.x, b.y), (a.x, a.y)] if rev else [(a.x, a.y), (b.x, b.y)])
        pipe_rows.append({"UFID": ufid, "US_MANHOLE": us, "DS_MANHOLE": ds, "DIAMETER_IN": dia, "MATERIAL": mat,
                          "INSTALL_YR": yr, "LENGTH_FT": round(line.length, 2), "geometry": line})
    # multipart pipe (two disjoint segments recorded as one asset)
    mp = MultiLineString([[(ox + 2000, oy - 400), (ox + 2200, oy - 400)], [(ox + 2250, oy - 400), (ox + 2400, oy - 400)]])
    pipe_rows.append({"UFID": "P-0070", "US_MANHOLE": None, "DS_MANHOLE": None, "DIAMETER_IN": 6, "MATERIAL": "PVC",
                      "INSTALL_YR": 2015, "LENGTH_FT": round(mp.length, 2), "geometry": mp})
    mains = gpd.GeoDataFrame(pipe_rows, crs=CRS_LOCAL)
    mains["INSTALL_YR"] = mains["INSTALL_YR"].astype("Int64")

    def box(x0, y0, x1, y1):
        return Polygon([(ox + x0, oy + y0), (ox + x1, oy + y0), (ox + x1, oy + y1), (ox + x0, oy + y1)])

    east_outer = [(ox + 2200, oy + 900), (ox + 3000, oy + 900), (ox + 3000, oy + 1500), (ox + 2200, oy + 1500)]
    east_hole = [(ox + 2500, oy + 1100), (ox + 2700, oy + 1100), (ox + 2700, oy + 1300), (ox + 2500, oy + 1300)]
    basins = gpd.GeoDataFrame([
        {"BASIN_ID": "B-NORTH", "NAME": "North Synthetic", "AREA_AC_SRC": 33.1, "geometry": box(-200, 200, 1800, 1000)},
        {"BASIN_ID": "B-SOUTH", "NAME": "South Synthetic", "AREA_AC_SRC": 39.4, "geometry": box(-200, -1000, 1800, 250)},
        {"BASIN_ID": "B-EAST", "NAME": "East With Hole", "AREA_AC_SRC": 10.1,
         "geometry": Polygon(east_outer, [east_hole])},
        {"BASIN_ID": "B-ISLANDS", "NAME": "Multipart Islands", "AREA_AC_SRC": None,
         "geometry": MultiPolygon([box(2200, -1400, 3000, -600), box(3200, -1400, 3600, -1000)])},
        {"BASIN_ID": "B-BAD", "NAME": "Invalid Bowtie", "AREA_AC_SRC": 0.0,
         "geometry": Polygon([(ox - 900, oy - 300), (ox - 300, oy + 300), (ox - 300, oy - 300), (ox - 900, oy + 300)])},
    ], crs=CRS_LOCAL)

    to_ll = Transformer.from_crs(CRS_LOCAL, "EPSG:4326", always_xy=True)
    sensors = []
    for sid, (mh, name, dx) in enumerate([("MH-003", "Trunk Mid", 15), ("MH-005", "Outlet", -20),
                                          ("MH-011", "Branch A", 10), ("MH-031", "Branch C", 12),
                                          ("MH-041", "Trunk Mid", 8)], start=1):
        p = pos[mh]
        lon, lat = to_ll.transform(p.x + dx, p.y + dx)
        mh_ufid = manholes.loc[manholes["MH_NUMBER"] == mh, "UFID"].iloc[0]
        sensors.append({"site_id": f"LS-{sid:03d}", "site_name": name, "longitude": round(lon, 7),
                        "latitude": round(lat, 7), "linked_mh_ufid": mh_ufid, "install_date": f"2021-0{sid}-15"})
    sensors_df = pd.DataFrame(sensors)

    rng = np.random.default_rng(42)
    sso = []
    for i, (dx, dy) in enumerate([(820, 30), (1180, 380), (410, 820), (2420, -790), (1650, -50), (2600, 1250)]):
        sso.append({"EVENT_ID": f"SSO-{i + 1:04d}", "EVT_DATE": f"2024-{i + 2:02d}-1{i}",
                    "CAUSE": ["GREASE", "ROOTS", "DEBRIS", "GREASE", "I/I", "ROOTS"][i],
                    "VOL_GAL": int(rng.integers(50, 5000)), "geometry": Point(ox + dx, oy + dy)})
    sso_gdf = gpd.GeoDataFrame(sso, crs=None)

    paths = {
        "manholes": out_dir / "manholes.gpkg",
        "gravity_mains": out_dir / "gravity_mains.gpkg",
        "sewer_basins": out_dir / "sewer_basins.parquet",
        "level_sensors": out_dir / "level_sensors.csv",
        "sso_events": out_dir / "sso_events_no_prj.zip",
    }
    manholes.to_file(paths["manholes"], driver="GPKG", layer="manholes")
    mains.to_file(paths["gravity_mains"], driver="GPKG", layer="gravity_mains")
    basins.to_parquet(paths["sewer_basins"], index=False)
    sensors_df.to_csv(paths["level_sensors"], index=False)
    tmp = out_dir / "_sso_tmp"
    tmp.mkdir(exist_ok=True)
    sso_gdf.to_file(tmp / "sso_events.shp", driver="ESRI Shapefile")
    with zipfile.ZipFile(paths["sso_events"], "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(tmp.iterdir()):
            if p.suffix.lower() != ".prj":
                z.write(p, p.name)
    for p in tmp.iterdir():
        p.unlink()
    tmp.rmdir()
    (out_dir / "README.md").write_text(__doc__ or "", encoding="utf-8")
    return paths


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "fixtures"
    for k, v in build(target).items():
        print(f"{k:15s} {v}")
