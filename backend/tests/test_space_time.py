"""Space-time cube + emerging hot spot analysis + feature to point: known answers and an end-to-end run."""
import math

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import LineString, Point, box

from hpw_gis.gis_tools.features import feature_points
from hpw_gis.gis_tools.space_time import (
    assign_time_steps, bin_polygon, classify_patterns, confidence_bin, fdr_bins, gi_star, grid_index,
    mann_kendall, neighbor_csr, parse_times, time_edges,
)

from .conftest import run

T = pd.Timestamp


# ----------------------------------------------------------------------------- time bins
def test_end_time_alignment_includes_bin_end():
    edges, closed = time_edges(T("2024-01-15"), T("2024-12-15"), 1, "months", "end_time")
    assert closed == "right" and edges[-1] == T("2024-12-15") and edges[0] == T("2023-12-15")
    assert len(edges) - 1 == 12
    steps = assign_time_steps(np.array(["2024-01-15", "2024-02-15", "2024-02-16", "2024-12-15"],
                                       dtype="datetime64[ns]"), edges, closed)
    assert steps.tolist() == [0, 1, 2, 11]  # bin k = (edge_k, edge_k+1]


def test_start_time_alignment_includes_bin_start():
    edges, closed = time_edges(T("2024-01-15"), T("2024-12-15"), 1, "months", "start_time")
    assert closed == "left" and edges[0] == T("2024-01-15") and edges[-1] == T("2025-01-15")
    steps = assign_time_steps(np.array(["2024-01-15", "2024-02-15", "2024-12-15"], dtype="datetime64[ns]"),
                              edges, closed)
    assert steps.tolist() == [0, 1, 11]


def test_reference_time_in_middle_has_a_bin_ending_at_reference():
    edges, closed = time_edges(T("2024-01-10"), T("2024-12-20"), 1, "months", "reference_time", T("2024-06-01"))
    assert T("2024-06-01") in edges and closed == "right"
    assert edges[0] < T("2024-01-10") and edges[-1] >= T("2024-12-20")


def test_month_steps_do_not_drift_from_month_end():
    edges, _ = time_edges(T("2024-01-01"), T("2024-05-31"), 1, "months", "end_time")
    assert T("2024-02-29") in edges and T("2024-03-31") in edges


def test_parse_times_treats_placeholders_as_unknown():
    s = parse_times(pd.Series(["2024-06-14 00:00:00", "0000/00/00", None, "2021/09/27"]))
    assert s.isna().tolist() == [False, True, True, False]
    assert s[3] == T("2021-09-27")


# ----------------------------------------------------------------------------- grids
def test_fishnet_upper_left_bin_centred_on_extent_corner():
    keys = grid_index(np.array([0.0, 4.9, 5.1, 0.0]), np.array([100.0, 100.0, 100.0, 94.0]), (0.0, 100.0), 10.0,
                      "fishnet")
    assert keys.tolist() == [[0, 0], [0, 0], [0, 1], [1, 0]]
    assert bin_polygon((0, 0), (0.0, 100.0), 10.0, "fishnet").equals(box(-5, 95, 5, 105))


def test_hexagon_bins_contain_their_points():
    rng = np.random.default_rng(1)
    x, y = rng.uniform(0, 500, 400), rng.uniform(0, 500, 400)
    keys = grid_index(x, y, (0.0, 500.0), 40.0, "hexagon")
    for k, px, py in zip(keys, x, y):
        hexagon = bin_polygon(tuple(k), (0.0, 500.0), 40.0, "hexagon")
        assert hexagon.buffer(1e-6).contains(Point(px, py))
    hexagon = bin_polygon((0, 0), (0.0, 0.0), 40.0, "hexagon")
    b = hexagon.bounds
    assert b[3] - b[1] == pytest.approx(40.0)  # height = distance interval
    assert b[2] - b[0] == pytest.approx(2 * 40.0 / math.sqrt(3))  # width = 2h / sqrt 3


# ----------------------------------------------------------------------------- statistics
def test_mann_kendall_known_values():
    z, p = mann_kendall(np.arange(1, 11, dtype=float))
    assert z[0] == pytest.approx(44 / math.sqrt(125))  # S = 45, var = 10*9*25/18
    assert p[0] < 0.001
    z, p = mann_kendall(np.array([[5.0] * 10]))
    assert z[0] == 0 and p[0] == 1
    z, _ = mann_kendall(np.array([[1, 1, 2, 2, 3, 3, 4, 4, 5, 5]], dtype=float))  # ties reduce the variance
    var = (10 * 9 * 25 - 5 * (2 * 1 * 9)) / 18
    assert z[0] == pytest.approx((40 - 1) / math.sqrt(var))


def test_confidence_and_fdr_bins():
    z = np.array([3.0, -2.0, 1.7, 0.5])
    p = np.array([0.0027, 0.0455, 0.0891, 0.617])
    assert confidence_bin(z, p).tolist() == [3, -2, 1, 0]
    fdr = fdr_bins(z, p)  # Benjamini-Hochberg by hand: alpha .10 -> 2 discoveries, .05 -> 1, .01 -> 0
    assert fdr.tolist() == [2, -1, 0, 0]
    assert np.all(np.abs(fdr) <= np.abs(confidence_bin(z, p)))  # FDR is never less strict


def test_gi_star_flags_planted_cluster():
    n = 7  # 7 x 7 grid, cluster in the middle 3 x 3, 12 time steps
    cents = np.array([Point(c, r) for r in range(n) for c in range(n)], dtype=object)
    x = np.ones((n * n, 12))
    mid = [r * n + c for r in (2, 3, 4) for c in (2, 3, 4)]
    x[mid] = 20
    indptr, idx = neighbor_csr(cents, 1.5)
    assert np.diff(indptr)[24] == 9  # queen neighbours + self
    z = gi_star(x, indptr, idx, 1)
    assert z[24].min() > 3
    assert z[0].max() < 0


def test_classify_patterns_rules():
    zero = np.zeros(10, dtype=int)
    rows = {
        "new": np.r_[zero[:9], 2],
        "consecutive": np.r_[zero[:7], 1, 2, 2],
        "intensifying": np.full(10, 2),
        "persistent": np.full(10, 2),
        "historical": np.r_[np.full(9, 2), 0],
        "sporadic": np.array([1, 0, 1, 0, 0, 1, 0, 0, 0, 1]),
        "oscillating": np.array([-2, 0, 1, 0, 0, 0, 0, 0, 0, 1]),
        "new cold": np.r_[zero[:9], -1],
        "none": zero,
    }
    trend = np.array([0, 0, 2, 0, 0, 0, 0, 0, 0])
    cats = classify_patterns(np.vstack(list(rows.values())), trend)
    assert dict(zip(rows, cats.tolist())) == {"new": 1, "consecutive": 2, "intensifying": 3, "persistent": 4,
                                              "historical": 8, "sporadic": 6, "oscillating": 7, "new cold": -1,
                                              "none": 0}
    assert classify_patterns(np.full((1, 10), 2), np.array([-1]))[0] == 5  # diminishing


def test_base_label_strips_chain_suffixes():
    from hpw_gis.gis_tools.space_time import base_label
    assert base_label("PACP Pipe Inspections (25 basins) (EPSG:2278) (2) Points") == "PACP Pipe Inspections (25 basins)"
    assert base_label("PACP (25 basins) Space Time Cube (3)") == "PACP (25 basins)"
    assert base_label("Points") == "Points"


def test_feature_to_point_line_midpoint_and_centroid():
    g = np.array([LineString([(0, 0), (10, 0), (10, 10)]), box(0, 0, 2, 2), None], dtype=object)
    inside = feature_points(g, "inside")
    assert inside[0].equals(Point(10, 0)) and box(0, 0, 2, 2).contains(inside[1]) and inside[2] is None
    cen = feature_points(g, "centroid")
    assert cen[1].equals(Point(1, 1))


# ----------------------------------------------------------------------------- end to end
def _events(tmp_path):
    """Synthetic inspections (EPSG:2278 feet) on a 2 x 2 mile area: background noise everywhere plus a
    cluster that only appears - and keeps growing - in the last 8 of 20 quarters."""
    rng = np.random.default_rng(7)
    x0, y0 = 3_100_000.0, 13_800_000.0
    rows = []
    start = T("2021-01-01")
    for q in range(20):
        for _ in range(25):
            rows.append((x0 + rng.uniform(0, 10560), y0 + rng.uniform(0, 10560), start + pd.DateOffset(months=3 * q, days=int(rng.integers(0, 85)))))
        if q >= 12:
            for _ in range(10 + 6 * (q - 12)):
                rows.append((x0 + 8000 + rng.uniform(0, 1500), y0 + 8000 + rng.uniform(0, 1500),
                             start + pd.DateOffset(months=3 * q, days=int(rng.integers(0, 85)))))
    df = pd.DataFrame(rows, columns=["x", "y", "INSPECT_DT"])
    df["INSPECT_DT"] = df["INSPECT_DT"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df.loc[:4, "INSPECT_DT"] = "0000/00/00"
    df["PACP_SCORE"] = rng.integers(0, 6, len(df)).astype(float)
    lines = [LineString([(a, b), (a + 50, b)]) for a, b in zip(df.x, df.y)]
    gdf = gpd.GeoDataFrame(df.drop(columns=["x", "y"]), geometry=lines, crs="EPSG:2278")
    p = tmp_path / "pipes.gpkg"
    gdf.to_file(p, driver="GPKG")
    return p


def test_pipeline_feature_to_point_cube_and_emerging_hot_spots(client, tmp_path):
    p = _events(tmp_path)
    with open(p, "rb") as f:
        r = client.post("/api/layers/import", files={"file": ("pipes.gpkg", f)}, data={"label": "Pipes"})
    assert r.status_code == 200, r.text
    lid = r.json()["layer_id"]

    j = run(client, "stpm.create_space_time_cube", input_layer=lid, time_field="INSPECT_DT")
    assert j["error"] == "validation_error" and "Line geometry not accepted" in " ".join(j["detail"])
    pts = run(client, "management.feature_to_point", input_layer=lid, point_location="inside")
    assert pts["status"] == "succeeded"
    pid = pts["result"]["result"]["layer_id"]

    few = run(client, "stpm.create_space_time_cube", input_layer=pid, time_field="INSPECT_DT",
              time_step_interval=1, time_step_unit="years")
    assert few["status"] == "failed" and "at least 10" in few["error"]

    cube = run(client, "stpm.create_space_time_cube", input_layer=pid, time_field="INSPECT_DT",
               time_step_interval=3, time_step_unit="months", distance_interval=1320, distance_units="feet",
               summary_field="PACP_SCORE", summary_statistic="sum")
    assert cube["status"] == "succeeded", [m["text"] for m in cube["messages"] if m["level"] == "debug"]
    c = cube["result"]["counts"]
    assert c["excluded_unknown_time"] == 5 and c["time_steps"] == 20
    assert c["locations"] * 20 == c["bins"]
    assert c["overall_trend"]["direction"] == "increasing"
    assert len(c["series"]["count"]) == 20 and sum(c["series"]["count"]) == c["aggregated_points"]
    assert len(c["series"]["SUM_PACP_SCORE"]) == 20
    cube_id = cube["result"]["result"]["layer_id"]
    t = client.post(f"/api/layers/{cube_id}/table", json={"limit": 5}).json()
    assert {"LOCATION_ID", "TIME_STEP", "START_TIME", "END_TIME", "COUNT", "SUM_PACP_SCORE"} <= \
        {col["name"] for col in t["columns"]}
    assert t["total"] == c["bins"]

    eh = run(client, "stpm.emerging_hot_spot_analysis", input_cube=cube_id, neighborhood_distance=2000)
    assert eh["status"] == "succeeded", eh.get("error")
    cats = eh["result"]["counts"]["categories"]
    hot = sum(n for k, n in cats.items() if "Hot Spot" in k and k.split()[0] in ("New", "Consecutive", "Intensifying"))
    assert hot >= 1, cats
    s = eh["result"]["counts"]["series"]
    assert sum(s["hot_bins"]) == eh["result"]["counts"]["hot_bins"] and len(s["value"]) == 20
    loc_id = eh["result"]["result"]["layer_id"]
    rows = client.post(f"/api/layers/{loc_id}/table", json={"limit": 1000}).json()["rows"]
    assert {r["PATTERN"] for r in rows} <= set(__import__("hpw_gis.gis_tools.space_time", fromlist=["x"]).PATTERNS.values())
    # the planted cluster (x0+8000..9500, y0+8000..9500) is an emerging hot spot
    meta = client.get(f"/api/layers/{loc_id}/metadata").json()
    assert meta["feature_count"] == c["locations"]
    feats = client.get(f"/api/layers/{loc_id}/features").json()["features"]
    target = gpd.GeoSeries([Point(3_108_750, 13_808_750)], crs="EPSG:2278").to_crs("EPSG:4326")[0]
    hit = [f for f in feats if shapely.geometry.shape(f["geometry"]).contains(target)]
    assert hit and hit[0]["properties"]["CATEGORY"] in (1, 2, 3), hit[0]["properties"]
    bins_id = eh["result"]["result"]["bins_layer_id"]
    bt = client.post(f"/api/layers/{bins_id}/table", json={"limit": 1, "where": "TIME_STEP = 19"}).json()
    assert bt["filtered"] == c["locations"]
    assert "EMERGING_COUNT_HS_BIN" in bt["rows"][0]

    # the cube itself can be analysed on its summary field too
    eh2 = run(client, "stpm.emerging_hot_spot_analysis", input_cube=cube_id, analysis_field="SUM_PACP_SCORE")
    assert eh2["status"] == "succeeded", eh2.get("error")
    assert eh2["result"]["counts"]["neighborhood_distance"] >= 1320 * math.sqrt(2)


def test_emerging_rejects_incomplete_cube(client, tmp_path):
    g = gpd.GeoDataFrame({"LOCATION_ID": [0, 0, 1], "TIME_STEP": [0, 1, 0], "COUNT": [1, 2, 3]},
                         geometry=[box(0, 0, 10, 10)] * 2 + [box(10, 0, 20, 10)], crs="EPSG:2278")
    p = tmp_path / "bad.gpkg"
    g.to_file(p, driver="GPKG")
    with open(p, "rb") as f:
        lid = client.post("/api/layers/import", files={"file": ("bad.gpkg", f)}).json()["layer_id"]
    j = run(client, "stpm.emerging_hot_spot_analysis", input_cube=lid)
    assert j["status"] == "failed" and "complete space-time cube" in j["error"]
