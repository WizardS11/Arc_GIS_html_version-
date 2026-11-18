# Phase 1 Validation Report

**Date:** 2026-11-14 · **Engine:** hpw_gis 0.1.0 · Shapely 2.2.0 (GEOS) · PyProj 3.8.0 · GeoPandas 1.2.0 · pyogrio 0.13.0
**Hardware:** Windows 11 ARM64 laptop, x64 Python 3.12.10 running under emulation
**ArcGIS comparison:** **not available.** No reference outputs were supplied, so every tool is `FUNCTIONAL_UNVALIDATED` or `PARTIAL`.

## Automated tests: 68 passed (`backend/tests`, ~10 s)
| Suite | Count | What it proves |
|---|---|---|
| `test_expressions.py` | 22 | SQL subset semantics, SQL three-valued NULL logic, quoting, rejection of injection/invalid syntax |
| `test_geometry_ops.py` | 16 | Known answers: point buffer area (64-gon is 0.16% under πr²), flat vs round line buffer, negative polygon buffer, clip line length; property: clip output ⊆ clip polygon and equals the GEOS intersection area (5 random seeds × 25 polygons); 6 relationship predicates incl. boundary cases |
| `test_workflow_api.py` | 30 | Bootstrap + profiling detects every planted QA defect; compatibility reasons; selection modes; Buffer/Clip/Project/Define Projection end to end with persisted output, readback, manifest, source hash unchanged; repeatability (two runs give geometries equal within 1e-9); export round trips in 5 formats; import upload; table paging/sort/search/filter; statistics; map geometry selection; projects; async jobs; restart persistence |

## Tool acceptance reports

```text
Tool: analysis.buffer
Documentation reference: https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/buffer.htm (2026-11-14)
Implementation: hpw_gis/gis_tools/proximity.py buffer_geometries / buffer, v0.1.0
Input geometries: Point, Line, Polygon (projected CRS required)
Parameters implemented: distance | distance_field, units (m, km, ft, US ft, yd, mi), line_end_type (round/flat),
                        dissolve (none/all/list + fields), method (planar), invalid geometry (repair/skip/fail)
Known differences: no geodesic; no side type; 16 segments per quarter circle; dissolve-all gives one multipart
Tests: unit (area, caps, negative), integration (fixture manholes, US-ft CRS conversion, selection, dissolve), repeatability
Validation metrics: 18/18 features out; mean area within 0.5% of π·r² (r converted ft→ftUS); no source mutation
Runtime: 18 points, 0.055 s
Status: PARTIAL (FUNCTIONAL_UNVALIDATED for implemented parameters)
```

```text
Tool: analysis.clip
Documentation reference: https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/clip.htm (2026-11-14)
Implementation: hpw_gis/gis_tools/overlay.py clip_geometries / clip, v0.1.0
Input geometries: Point, Line, Polygon input; Polygon clip features
Parameters implemented: input, clip features (selection honoured, unioned), invalid geometry handling
Known differences: polygon clip features only; no XY tolerance
Tests: property (output within clip, area equals intersection), known lengths, lower-dimension contact exclusion,
       invalid-clip fail/repair, fixture mains vs B-NORTH
Validation metrics: 16 in → 2 fully inside + 2 cut + 12 outside = 4 out; P-0021 clipped length 200.000 ft exactly
Runtime: 16 lines, 0.043 s
Status: FUNCTIONAL_UNVALIDATED
```

```text
Tool: management.select_layer_by_attribute / select_layer_by_location
Documentation reference: see catalog (2026-11-14)
Known differences: SQL subset, case-sensitive LIKE; exact GEOS predicates without XY tolerance; 11 relationships
Validation metrics: DIAMETER_IN >= 12 → 6; subset MATERIAL='RCP' → 3; switch → 13; pipes intersecting B-NORTH →
                    P-0010, P-0011, P-0020, P-0021
Status: FUNCTIONAL_UNVALIDATED / PARTIAL
```

```text
Tool: management.project / define_projection
Validation metrics: EPSG:4326 → EPSG:2278 round trip of a sensor placed +15 ft from MH-003 returns +15 ft ± 0.05 ft;
                    Define Projection EPSG:4326 on foot-based coordinates is refused (out of degree range)
Status: FUNCTIONAL_UNVALIDATED
```

## Phase 1 release gate (spec §15)
> An independent user can import a sample layer, run Buffer and Clip, inspect resulting geometry and attributes,
> and export a persisted output without ArcGIS.

**Met on synthetic data.** Verified through the API tests above and by driving the built UI in headless Edge:
Buffer (manholes, 150 ft) → 18 polygons shown on the map and in the table; Select By Attribute (`BASIN_ID =
'B-NORTH'`) → 1 selected; Clip (mains by selected basin) → 4 features with the `LENGTH_FT` not-recalculated
warning. Export is covered by the round-trip tests. Ineligible layers were listed with reasons (geographic CRS,
unknown CRS).
