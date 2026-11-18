"""Pure-function geometry tests with known answers + property-style invariants (spec §7.2, §14.1)."""
import math

import geopandas as gpd
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point, Polygon, box

from hpw_gis.gis_tools.overlay import clip_geometries
from hpw_gis.gis_tools.proximity import buffer_geometries
from hpw_gis.gis_tools.selection import spatial_match


def test_point_buffer_area_known_result():
    g = buffer_geometries(np.array([Point(0, 0)]), np.array([100.0]))[0]
    assert g.area == pytest.approx(math.pi * 100 ** 2, rel=0.002)  # 16 quad segs: inscribed 64-gon is 0.16% low
    assert g.area < math.pi * 100 ** 2


def test_line_buffer_flat_vs_round():
    line = np.array([LineString([(0, 0), (100, 0)])])
    flat = buffer_geometries(line, np.array([10.0]), "flat")[0]
    rnd = buffer_geometries(line, np.array([10.0]), "round")[0]
    assert flat.area == pytest.approx(100 * 20)
    assert rnd.area == pytest.approx(100 * 20 + math.pi * 100, rel=0.01)


def test_negative_polygon_buffer_shrinks_and_can_vanish():
    sq = np.array([box(0, 0, 100, 100), box(0, 0, 10, 10)])
    out = buffer_geometries(sq, np.array([-10.0, -10.0]))
    assert out[0].area == pytest.approx(80 * 80)
    assert out[1].is_empty


def test_clip_line_known_length():
    lines = np.array([LineString([(-50, 50), (150, 50)]), LineString([(200, 0), (300, 0)])])
    res = clip_geometries(lines, box(0, 0, 100, 100), 1)
    assert res[0].length == pytest.approx(100)
    assert res[1] is None


def test_clip_drops_lower_dimension_contact():
    # polygon sharing only an edge with the clip polygon -> no polygonal overlap -> excluded
    res = clip_geometries(np.array([box(100, 0, 200, 100)]), box(0, 0, 100, 100), 2)
    assert res[0] is None


@pytest.mark.parametrize("seed", range(5))
def test_clip_property_output_within_clip(seed):
    rng = np.random.default_rng(seed)
    polys = np.array([shapely.Point(rng.uniform(-50, 150), rng.uniform(-50, 150)).buffer(rng.uniform(5, 40))
                      for _ in range(25)])
    mask = Polygon([(0, 0), (100, 0), (120, 80), (40, 120), (-10, 60)])
    res = clip_geometries(polys, mask, 2)
    for src, g in zip(polys, res):
        if g is None:
            assert src.intersection(mask).area < 1e-9
            continue
        assert g.difference(mask.buffer(1e-6)).area < 1e-6      # within clip polygon (tolerance)
        assert g.area == pytest.approx(src.intersection(mask).area, rel=1e-9)
        assert g.area <= src.area + 1e-9


def _gdf(geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs="EPSG:2278")


@pytest.mark.parametrize("relation,expected", [
    ("intersect", [0, 1, 2, 3]),
    ("contains", []),
    ("within", [0, 1, 3]),            # boundary point (1) is covered_by -> within (ArcGIS WITHIN)
    ("completely_within", [0, 3]),    # boundary contact excluded
    ("boundary_touches", [1, 2]),
    ("have_their_center_in", [0, 1, 3]),
])
def test_spatial_relationships_points_vs_polygon(relation, expected):
    pts = _gdf([Point(50, 50), Point(100, 50), LineString([(100, 0), (150, 0)]), Point(10, 10), Point(500, 500)])
    poly = _gdf([box(0, 0, 100, 100)])
    got = list(np.where(spatial_match(pts, poly, relation, None))[0])
    assert got == expected


def test_within_a_distance():
    pts = _gdf([Point(0, 0), Point(105, 0), Point(111, 0)])
    sel = _gdf([Point(0, 0).buffer(0.0001).centroid])
    sel = _gdf([LineString([(0, 0), (0, 10)])])
    got = list(np.where(spatial_match(pts, sel, "within_a_distance", 110.0))[0])
    assert got == [0, 1]


def test_contains_polygon_in_polygon():
    big = _gdf([box(0, 0, 100, 100), box(200, 200, 210, 210)])
    small = _gdf([box(10, 10, 20, 20)])
    assert list(np.where(spatial_match(big, small, "contains", None))[0]) == [0]
    assert list(np.where(spatial_match(big, small, "completely_contains", None))[0]) == [0]
    edge = _gdf([box(0, 0, 20, 20)])
    assert list(np.where(spatial_match(big, edge, "completely_contains", None))[0]) == []
    assert list(np.where(spatial_match(big, edge, "contains", None))[0]) == [0]
