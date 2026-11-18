# Development Roadmap

Priority order within each phase: **functional accuracy → universal reusability → validated output → performance → polish**.

## Phase 0 — Audit + catalog ✅ (2026-11-14)
- The repository was empty apart from the master spec, so the app was scaffolded per spec §15.
- Environment: Windows 11 on ARM64. x64 Python 3.12 installed per-user (ARM wheels for GDAL/pyarrow are
  missing). Node 26.
- Deliverables: `ARCHITECTURE.md`, `ARCGIS_FEATURE_CATALOG.csv`, `LAYER_REGISTRY.md`, this roadmap.

## Phase 1 — Working GIS foundation ✅ (release gate met on synthetic data)
Point, Line and Polygon fixtures (plus CSV and no-CRS shapefile) · import/registration with profiling · map with
visibility, style, identify and selection sync · attribute table · Select by Attributes / by Location · Buffer ·
Clip · Project · Define Projection · Export Features · persistent Gold outputs · export to 5 formats · provenance
manifests · run history · projects · 68 automated tests.

**Release gate evidence:** `VALIDATION_REPORTS/phase1_validation.md`.

## Phase 2 — General-purpose 2D GIS (next)
1. **Spatial Join** (intersects / within distance / nearest; one-to-one with match count, one-to-many) with
   explicit tie rules → SSO-to-pipe analysis.
2. **Dissolve**, **Summarize Within** (count, length, area-weighted sums), **Near / Generate Near Table**.
3. **Intersect / Erase / Union**, with attribute provenance (`FID_<input>` columns).
4. **Calculate Field / Calculate Geometry Attributes** on derived copies; **Merge** with a schema report; **Add Join**
   with cardinality warnings.
5. **Repair Geometry**, **Multipart To Singlepart**, **Feature To Point**.
6. UI: unique-value/graduated symbology and labels, measure tool, bookmarks, polygon/lasso selection, column
   pin/reorder.
7. Performance: vector tiles (MVT) or DuckDB Spatial for layers over 100k features. Benchmarks on small, medium
   and large layers.
8. Playwright UI tests: import → buffer → clip → export.

Acceptance per tool: spec §14.2 plus an acceptance report in `VALIDATION_REPORTS/`.

## Phase 3 — Network, editing, workflows
Upstream/downstream gravity trace from verified US/DS attributes (NetworkX). The fixtures already include
branches, a cycle, an orphan, a disconnected pair and a reversed pipe. Network QA reports. Controlled editing of
copies with an audit log. Named workflow chains (the `workflow_definitions` table exists).

## Phase 4 — Optional
Raster, spatial statistics, time-aware layers, workflow graph editor. Optional ArcGIS reference-output
comparisons where licensed outputs are available.

## Risks / blocked items
| Item | Impact | Mitigation |
|---|---|---|
| No real HPW datasets or schemas yet | Cannot validate on production data | Descriptor-driven onboarding; synthetic fixtures model the known schema candidates |
| No ArcGIS reference outputs | Every tool stays FUNCTIONAL_UNVALIDATED | Known-answer and property tests; add golden comparisons when samples are supplied |
| OSM basemap needs internet | Blank background offline | "None (offline)" basemap; local tile option in Phase 2 |
| Geodesic buffer/distance not implemented | Geographic layers must be projected first | Clear refusal + Project tool |
