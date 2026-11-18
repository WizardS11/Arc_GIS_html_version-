"""Integration tests: import -> register -> tool -> derived layer -> readback -> export -> provenance (spec §14)."""
import io
import json
import math
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from hpw_gis.storage.io import sha256_path

from .conftest import run


def layers(client):
    return {l["layer_id"]: l for l in client.get("/api/layers").json()}


def test_health_and_bootstrap(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["gdal_drivers"]["GPKG"]
    ls = layers(client)
    assert {"manholes", "gravity_mains", "sewer_basins", "level_sensors", "sso_events"} <= set(ls)
    assert ls["manholes"]["geometry_family"] == "Point"
    assert ls["gravity_mains"]["geometry_family"] == "Line"
    assert ls["sewer_basins"]["geometry_family"] == "Polygon"


def test_onboarding_profile_flags_quality_issues(client):
    ls = layers(client)
    mh = client.get("/api/layers/manholes/metadata").json()
    assert mh["primary_key"] == "UFID"
    assert mh["crs"]["srs"] == "EPSG:2278" and mh["crs"]["linear_unit"] == "US survey foot"
    assert any("Natural key 'MH_NUMBER' is not unique" in w for w in mh["warnings"])
    basins = client.get("/api/layers/sewer_basins/metadata").json()
    assert basins["profile"]["invalid_geometry_count"] == 1
    assert basins["profile"]["multipart_count"] == 1
    assert ls["sso_events"]["crs"]["status"] == "unknown"
    assert ls["level_sensors"]["crs"]["is_geographic"] is True
    rels = {r["local_field"]: r for r in client.get("/api/layers/gravity_mains/metadata").json()["relationships"]}
    assert rels["DS_MANHOLE"]["validation"]["unmatched"] == 1      # orphan MH-999
    assert rels["US_MANHOLE"]["validation"]["target_duplicate_keys"] == 1


def test_compatibility_explains_ineligible_layers(client):
    tool = client.get("/api/tools/analysis.buffer").json()
    comp = {c["layer_id"]: c for c in tool["params"][0]["compatibility"]}
    assert comp["manholes"]["compatible"]
    assert not comp["level_sensors"]["compatible"] and "Geographic" in comp["level_sensors"]["reason"]
    assert not comp["sso_events"]["compatible"] and "unknown" in comp["sso_events"]["reason"]
    clip = client.get("/api/tools/analysis.clip").json()
    clip_comp = {c["layer_id"]: c for c in clip["params"][1]["compatibility"]}
    assert clip_comp["sewer_basins"]["compatible"] and not clip_comp["gravity_mains"]["compatible"]


def test_select_by_attributes_and_selection_modes(client):
    r = run(client, "management.select_layer_by_attribute", input_layer="gravity_mains",
            where_clause="DIAMETER_IN >= 12", selection_type="new")
    assert r["status"] == "succeeded", r
    first = set(r["result"]["result"]["fids"])
    assert len(first) == 6  # 12,15,18,24,12,30
    r = run(client, "management.select_layer_by_attribute", input_layer="gravity_mains",
            where_clause="MATERIAL = 'RCP'", selection_type="subset")
    assert r["result"]["result"]["selected_count"] == 3
    r = run(client, "management.select_layer_by_attribute", input_layer="gravity_mains", selection_type="switch")
    assert r["result"]["result"]["selected_count"] == 16 - 3
    bad = run(client, "management.select_layer_by_attribute", input_layer="gravity_mains",
              where_clause="DIAMETER_IN >>= 3")
    assert bad["status"] == "failed" and "Invalid expression" in bad["error"]


def test_select_by_location_pipes_in_basin(client):
    client.put("/api/selection/sewer_basins", json={"fids": [0], "mode": "new"})  # B-NORTH only
    r = run(client, "management.select_layer_by_location", input_layer="gravity_mains", overlap_type="intersect",
            select_features="sewer_basins", selection_type="new")
    assert r["status"] == "succeeded", r
    fids = r["result"]["result"]["fids"]
    g = client.post("/api/layers/gravity_mains/table", json={"selected_only": True, "limit": 100}).json()
    ids = sorted(row["UFID"] for row in g["rows"])
    assert ids == ["P-0010", "P-0011", "P-0020", "P-0021"] and len(fids) == 4


def test_select_within_distance_requires_projected(client):
    r = run(client, "management.select_layer_by_location", input_layer="manholes", overlap_type="within_a_distance",
            select_features="manholes", search_distance=50, distance_units="feet")
    assert r["status"] == "succeeded"
    r = client.post("/api/tool-runs", json={"tool_id": "management.select_layer_by_location", "wait": True,
                                            "params": {"input_layer": "level_sensors", "overlap_type": "intersect",
                                                       "select_features": "sso_events"}})
    assert r.status_code == 422 and "unknown" in json.dumps(r.json()["detail"]).lower()


def test_buffer_creates_persistent_layer_with_provenance(client, settings):
    src_info = client.get("/api/layers/manholes/metadata").json()
    src_hash_before = sha256_path(Path(src_info["path"]))
    r = run(client, "analysis.buffer", input_layer="manholes", distance=100, units="feet")
    assert r["status"] == "succeeded", r["messages"]
    out = r["result"]["outputs"][0]
    assert out["feature_count"] == 18 and out["crs"] == "EPSG:2278" and out["geometry_family"] == "Polygon"
    gdf = gpd.read_parquet(out["path"])
    # 100 international ft in US-survey-ft CRS units: area within GEOS segmentation tolerance
    r_crs = 100 * 0.3048 / (1200 / 3937)
    assert gdf.geometry.area.mean() == pytest.approx(math.pi * r_crs ** 2, rel=0.005)
    assert {"BUFF_DIST", "ORIG_FID", "UFID", "MH_NUMBER"} <= set(gdf.columns)
    manifest = client.get(f"/api/tool-runs/{r['run_id']}/result").json()
    assert manifest["inputs"][0]["sha256"] == src_info["sha256"]
    assert manifest["parameters"]["distance"] == 100.0
    assert manifest["reference_documentation_url"].startswith("https://pro.arcgis.com/")
    assert manifest["known_differences"]
    # source read-only: silver file unchanged
    assert sha256_path(Path(src_info["path"])) == src_hash_before
    lyr = client.get(f"/api/layers/{out['layer_id']}/metadata").json()
    assert lyr["tier"] == "gold" and lyr["parent_run_id"] == r["run_id"]
    feats = client.get(f"/api/layers/{out['layer_id']}/features").json()
    assert len(feats["features"]) == 18
    runs = client.get("/api/tool-runs").json()
    assert any(x["run_id"] == r["run_id"] and x["status"] == "succeeded" for x in runs)


def test_buffer_respects_selection_and_dissolve(client):
    client.put("/api/selection/manholes", json={"fids": [0, 1, 2], "mode": "new"})
    r = run(client, "analysis.buffer", input_layer="manholes", distance=300, units="feet", dissolve_option="all")
    assert r["status"] == "succeeded"
    assert r["result"]["counts"]["input_features"] == 3
    assert r["result"]["outputs"][0]["feature_count"] == 1


def test_buffer_rejects_geographic_and_geodesic(client):
    r = client.post("/api/tool-runs", json={"tool_id": "analysis.buffer", "wait": True,
                                            "params": {"input_layer": "level_sensors", "distance": 10}})
    assert r.status_code == 422
    r = run(client, "analysis.buffer", input_layer="manholes", distance=10, method="geodesic")
    assert r["status"] == "failed" and "Geodesic" in r["error"]
    r = client.post("/api/tool-runs", json={"tool_id": "analysis.buffer", "wait": True,
                                            "params": {"input_layer": "manholes", "distance": "abc"}})
    assert r.status_code == 422


def test_buffer_is_repeatable(client):
    a = run(client, "analysis.buffer", input_layer="gravity_mains", distance=25, units="meters")
    b = run(client, "analysis.buffer", input_layer="gravity_mains", distance=25, units="meters")
    ga = gpd.read_parquet(a["result"]["outputs"][0]["path"])
    gb = gpd.read_parquet(b["result"]["outputs"][0]["path"])
    assert len(ga) == len(gb) == 16
    assert all(shapely.equals_exact(x, y, 1e-9) for x, y in zip(ga.geometry, gb.geometry))


def test_clip_mains_by_basin(client):
    client.put("/api/selection/sewer_basins", json={"fids": [0], "mode": "new"})  # B-NORTH
    r = run(client, "analysis.clip", input_layer="gravity_mains", clip_layer="sewer_basins")
    assert r["status"] == "succeeded", r["messages"]
    c = r["result"]["counts"]
    out = gpd.read_parquet(r["result"]["outputs"][0]["path"])
    basin = gpd.read_parquet(client.get("/api/layers/sewer_basins/metadata").json()["path"]).geometry[0]
    assert (out.geometry.difference(basin.buffer(1e-6)).length < 1e-6).all()
    # P-0010 fully inside; P-0011 & P-0021 cut at y=200; P-0020 fully inside
    assert sorted(out["UFID"]) == ["P-0010", "P-0011", "P-0020", "P-0021"]
    assert c["partially_clipped"] == 2 and c["fully_inside"] == 2
    assert out.loc[out["UFID"] == "P-0021"].geometry.length.iloc[0] == pytest.approx(200, abs=1e-6)
    assert any("LENGTH_FT" in m["text"] for m in r["messages"])


def test_clip_with_invalid_clip_polygon_fail_mode(client):
    client.put("/api/selection/sewer_basins", json={"fids": [4], "mode": "new"})  # bowtie
    r = run(client, "analysis.clip", input_layer="manholes", clip_layer="sewer_basins", invalid_geometry="fail")
    assert r["status"] == "failed" and "invalid" in r["error"].lower()
    r = run(client, "analysis.clip", input_layer="manholes", clip_layer="sewer_basins", invalid_geometry="repair")
    assert r["status"] == "succeeded"


def test_define_projection_then_buffer_unknown_crs_layer(client):
    r = run(client, "management.define_projection", input_layer="sso_events", coordinate_system="EPSG:2278")
    assert r["status"] == "succeeded", r["messages"]
    lid = r["result"]["outputs"][0]["layer_id"]
    r2 = run(client, "analysis.buffer", input_layer=lid, distance=50, units="feet")
    assert r2["status"] == "succeeded"
    # wrong (geographic) definition is refused because coordinates are not degrees
    r3 = run(client, "management.define_projection", input_layer="sso_events", coordinate_system="EPSG:4326")
    assert r3["status"] == "failed"


def test_project_geographic_then_buffer(client):
    r = run(client, "management.project", input_layer="level_sensors", output_crs="EPSG:2278")
    assert r["status"] == "succeeded"
    lid = r["result"]["outputs"][0]["layer_id"]
    meta = client.get(f"/api/layers/{lid}/metadata").json()
    assert meta["crs"]["srs"] == "EPSG:2278"
    # Sensor LS-001 was placed 15 ft (x and y) from MH-003 in EPSG:2278: round trip within 0.01 ft
    s = gpd.read_parquet(meta["path"]).set_index("site_id").geometry["LS-001"]
    mh = gpd.read_parquet(client.get("/api/layers/manholes/metadata").json()["path"])
    m = mh.loc[mh["MH_NUMBER"] == "MH-003"].geometry.iloc[0]
    assert s.x - m.x == pytest.approx(15, abs=0.05) and s.y - m.y == pytest.approx(15, abs=0.05)
    assert run(client, "analysis.buffer", input_layer=lid, distance=100)["status"] == "succeeded"


@pytest.mark.parametrize("fmt", ["gpkg", "geoparquet", "geojson", "csv", "shapefile"])
def test_exports_roundtrip(client, tmp_path, fmt):
    r = client.get(f"/api/layers/gravity_mains/export?format={fmt}")
    if fmt == "shapefile":
        # mixed LineString/MultiLineString is fine for shapefile (same family)
        assert r.status_code == 200, r.text
    assert r.status_code == 200, r.text
    assert r.headers["x-hpw-feature-count"] == "16"
    ext = {"gpkg": ".gpkg", "geoparquet": ".parquet", "geojson": ".geojson", "csv": ".csv", "shapefile": ".zip"}[fmt]
    p = tmp_path / f"out{ext}"
    p.write_bytes(r.content)
    if fmt == "csv":
        df = pd.read_csv(p, comment="#")
        assert len(df) == 16 and "geometry_wkt" in df.columns and "UFID" in df.columns
        assert "EPSG:2278" in p.read_text().splitlines()[0]
    elif fmt == "geoparquet":
        g = gpd.read_parquet(p)
        assert len(g) == 16 and g.crs.to_epsg() == 2278
    elif fmt == "shapefile":
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            assert {n.split(".")[-1] for n in z.namelist()} >= {"shp", "shx", "dbf", "prj"}
        g = gpd.read_file(f"/vsizip/{p.as_posix()}")
        assert len(g) == 16
    else:
        g = gpd.read_file(p)
        assert len(g) == 16
        if fmt == "geojson":
            assert g.crs.to_epsg() == 4326
            assert "reprojected" in json.loads(r.headers["x-hpw-warnings"])[0]


def test_export_selected_only(client):
    client.put("/api/selection/manholes", json={"fids": [1, 2], "mode": "new"})
    r = client.get("/api/layers/manholes/export?format=csv&selected_only=true")
    assert r.headers["x-hpw-feature-count"] == "2"
    client.put("/api/selection/manholes", json={"fids": [], "mode": "clear"})
    assert client.get("/api/layers/manholes/export?format=csv&selected_only=true").status_code == 409


def test_import_upload_csv_and_geojson(client, fixtures_dir, tmp_path):
    with open(fixtures_dir / "level_sensors.csv", "rb") as f:
        r = client.post("/api/layers/import", files={"file": ("sensors_copy.csv", f, "text/csv")},
                        data={"label": "Sensors copy"})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["crs"]["status"] == "unknown"                      # CRS never guessed
    assert any("auto-detected" in w for w in info["warnings"])
    gj = tmp_path / "pts.geojson"
    gpd.GeoDataFrame({"ID": [1, 2]}, geometry=[shapely.Point(-95.37, 29.76), shapely.Point(-95.36, 29.75)],
                     crs="EPSG:4326").to_file(gj, driver="GeoJSON")
    with open(gj, "rb") as f:
        r = client.post("/api/layers/import", files={"file": ("pts.geojson", f, "application/geo+json")})
    assert r.status_code == 200 and r.json()["crs"]["srs"] == "EPSG:4326" and r.json()["primary_key"] == "ID"
    bad = client.post("/api/layers/import", files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 422


def test_table_sort_search_filter_paging(client):
    t = client.post("/api/layers/gravity_mains/table",
                    json={"sort": [{"field": "DIAMETER_IN", "desc": True}], "limit": 3}).json()
    assert [r["DIAMETER_IN"] for r in t["rows"]] == [30, 24, 18] and t["filtered"] == 16
    t = client.post("/api/layers/gravity_mains/table", json={"search": "vcp"}).json()
    assert t["filtered"] == 5
    t = client.post("/api/layers/gravity_mains/table", json={"where": "INSTALL_YR IS NULL"}).json()
    assert [r["UFID"] for r in t["rows"]] == ["P-0020"]
    t = client.post("/api/layers/gravity_mains/table", json={"offset": 15, "limit": 10}).json()
    assert len(t["rows"]) == 1
    assert client.post("/api/layers/gravity_mains/table", json={"where": "x = ;"}).status_code == 422


def test_statistics(client):
    s = client.get("/api/layers/gravity_mains/statistics/DIAMETER_IN").json()
    assert s["count"] == 16 and s["max"] == 30 and s["min"] == 6
    s = client.get("/api/layers/gravity_mains/statistics/MATERIAL").json()
    assert s["top_values"][0]["value"] == "PVC"


def test_geometry_selection_from_map(client):
    b = client.get("/api/layers/manholes/metadata").json()["profile"]["extent_4326"]
    poly = {"type": "Polygon", "coordinates": [[[b[0] - 1e-5, b[1] - 1e-5], [b[2] + 1e-5, b[1] - 1e-5],
                                                [b[2] + 1e-5, b[3] + 1e-5], [b[0] - 1e-5, b[3] + 1e-5],
                                                [b[0] - 1e-5, b[1] - 1e-5]]]}
    r = client.post("/api/selection/manholes/by-geometry", json={"geometry": poly})
    assert len(r.json()["fids"]) == 18
    assert client.get("/api/selection/manholes/extent").status_code == 200


def test_unknown_crs_cannot_be_drawn(client):
    r = client.get("/api/layers/sso_events/features")
    assert r.status_code == 409 and "Define Projection" in r.json()["detail"]


def test_projects_persist_state_and_selection(client):
    client.put("/api/selection/manholes", json={"fids": [3, 4], "mode": "new"})
    client.post("/api/projects", json={"name": "demo", "state": {"layers": [{"layer_id": "manholes", "visible": True}]}})
    client.put("/api/selection/manholes", json={"fids": [], "mode": "clear"})
    p = client.get("/api/projects/demo").json()
    assert p["state"]["layers"][0]["layer_id"] == "manholes"
    assert client.get("/api/selection/manholes").json()["fids"] == [3, 4]


def test_async_job_and_cancel(client):
    r = client.post("/api/tool-runs", json={"tool_id": "analysis.buffer",
                                            "params": {"input_layer": "manholes", "distance": 5}})
    assert r.status_code == 202
    rid = r.json()["run_id"]
    import time
    for _ in range(100):
        s = client.get(f"/api/tool-runs/{rid}").json()
        if s["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert s["status"] == "succeeded"
    assert client.post("/api/tool-runs/deadbeef/cancel").status_code == 404


def test_registry_survives_restart(settings, client):
    run(client, "analysis.buffer", input_layer="manholes", distance=10)
    from fastapi.testclient import TestClient

    from hpw_gis.api.main import create_app
    c2 = TestClient(create_app(settings))
    ls = layers(c2)
    assert any(l["tier"] == "gold" for l in ls.values())
    rep = c2.get("/api/health").json()["bootstrap"]
    assert all(x["status"] == "already_registered" for x in rep)
