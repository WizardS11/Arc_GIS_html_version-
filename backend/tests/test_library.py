"""City layer library catalog: listing, on-demand registration, metadata pass-through, feature filter."""
import shutil
import time

import geopandas as gpd
import yaml
from fastapi.testclient import TestClient
from shapely.geometry import Point

from hpw_gis.api.main import create_app
from hpw_gis.config import PROJECT_ROOT, Settings


def test_library_add_registers_layer_with_group_and_style(tmp_path, fixtures_dir):
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copy(PROJECT_ROOT / "config" / "layers.yaml", cfg / "layers.yaml")
    src = tmp_path / "lift.parquet"
    gpd.GeoDataFrame({"UFID": [1, 2, 3], "NAME": ["a", "b", "c"]},
                     geometry=[Point(-95.36, 29.76), Point(-95.37, 29.77), Point(-95.38, 29.78)],
                     crs="EPSG:4326").to_parquet(src)
    (cfg / "city_layers.yaml").write_text(yaml.safe_dump({"layers": [
        {"layer_id": "city_lift_stations", "label": "Lift Stations", "group": "Existing wastewater network (GIS)",
         "source": {"uri": str(src), "format": "geoparquet"}, "geometry": {"type": "Point"},
         "display": {"color": "#123456", "min_zoom": 0}, "metadata": {"collection": "Houston map library"}},
        {"layer_id": "city_missing", "label": "Missing", "group": "X",
         "source": {"uri": str(tmp_path / "nope.parquet"), "format": "geoparquet"}},
    ]}), encoding="utf-8")
    c = TestClient(create_app(Settings(workspace=tmp_path / "ws", config_dir=cfg, fixtures_dir=fixtures_dir,
                                       ui_dir=tmp_path / "no_ui")))
    lib = {e["layer_id"]: e for e in c.get("/api/library").json()}
    assert lib["city_lift_stations"]["status"] == "available" and lib["city_missing"]["status"] == "missing"
    assert c.post("/api/library/city_missing/add").json()["status"] == "missing"
    assert c.post("/api/library/nope/add").status_code == 404

    assert c.post("/api/library/city_lift_stations/add").status_code == 202
    for _ in range(100):
        st = {e["layer_id"]: e for e in c.get("/api/library").json()}["city_lift_stations"]["status"]
        if st in ("registered", "error"):
            break
        time.sleep(0.05)
    assert st == "registered"
    lyr = c.get("/api/layers/city_lift_stations/metadata").json()
    assert lyr["group"] == "Existing wastewater network (GIS)" and lyr["display"]["color"] == "#123456"
    assert lyr["collection"] == "Houston map library" and lyr["permissions"]["source_read_only"]
    assert lyr["feature_count"] == 3 and lyr["primary_key"] == "UFID"

    fc = c.get("/api/layers/city_lift_stations/features", params={"where": "UFID >= 2"}).json()
    assert sorted(f["properties"]["UFID"] for f in fc["features"]) == [2, 3]
    assert c.get("/api/layers/city_lift_stations/features", params={"where": "UFID >>> 2"}).status_code == 422
