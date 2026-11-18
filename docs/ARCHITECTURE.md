# Architecture

**Version:** 0.1.0 · **Date:** 2026-11-14 · **Status:** Phase 1 vertical slice implemented

## 1. Purpose
This is a local, ArcGIS-like GIS workbench. A single universal processing engine serves every registered layer.
Spec: `HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md` §3.

## 2. Components

```text
Browser (HTML/CSS/JS + MapLibre 5)   ──REST──► FastAPI (127.0.0.1) ──► Universal engine ──► Data + provenance
 Toolbar · Contents · Map · Table ·            Layer registry            GeoPandas/Shapely/      workspaces/default/
 Geoprocessing · History · Dialogs             Tool registry + validate  GEOS · PyProj ·           hpw_gis.sqlite
                                               Job manager (threads)     pyogrio/GDAL · pyarrow    data/bronze|silver|gold
                                               Selection store
```

| Module | Responsibility |
|---|---|
| `storage/io.py` | Format detection, GDAL driver probing, read (incl. CSV X/Y/WKT, zipped shapefile), export to 5 formats |
| `storage/metadata.py` | SQLite tables from spec §9.1: `layers`, `layer_versions`, `relationships`, `tools`, `tool_runs`, `run_inputs`, `run_outputs`, `projects`, `workflow_definitions` |
| `registry/layers.py` | Onboarding (Bronze copy → profile → Silver GeoParquet), PK detection/verification, relationship validation, derived (Gold) registration, cached frames + EPSG:4326 display copies with spatial index |
| `registry/tools.py` | `ToolSpec`/`Param` contract, compatibility rules, server-side parameter validation |
| `jobs.py` | Job manager (ThreadPool, cooperative cancel), `RunContext` (inputs honouring selection, messages, counts, output registration), manifest writer, selection store and selection modes |
| `gis_tools/*` | Pure geometry functions + thin executors; registered at import |
| `api/main.py` | REST endpoints (spec §11), descriptor bootstrap, static UI hosting |

## 3. Key decisions
| Decision | Choice | Reason |
|---|---|---|
| Processing engine | GeoPandas 1.2 / Shapely 2.2 (GEOS) / PyProj 3.8 | Mature, vectorized, offline; no Esri dependency |
| File IO | pyogrio (bundled GDAL) + pyarrow | GPKG, Shapefile, FileGDB (OpenFileGDB), GeoJSON, FlatGeobuf, GeoParquet; drivers probed at runtime (`/api/health`) |
| Internal storage | GeoParquet per layer version + SQLite metadata | No database server; columnar and fast; works on a laptop without admin rights |
| Feature identity | `_hpw_fid` surrogate on every version; declared PK verified (unique and non-null) or reported | Stable selection and lineage without trusting source keys |
| Selection | Server-side per-layer set; tools use it by default (`use_selection`) | Matches ArcGIS "tools honour selection"; recorded in provenance |
| Map transport | GeoJSON by viewport bbox, capped at 20,000 features per layer per request with a truncation warning | Simple and correct for Phase 1; vector tiles are planned for city-scale layers |
| Distance semantics | Planar only; distance tools refuse geographic or unknown CRS | Spec §7.1: fail clearly rather than give misleading output |
| Table | Custom server-paginated table (instead of TanStack) | Fewer dependencies; server does the sort/filter/search |
| Frontend | Plain HTML/CSS/JS ES modules in `web/` (`main, state, api, ui, map, contents, table, geoprocessing, dialogs`); MapLibre 5.6 stored locally in `web/vendor/` (BSD-3); no framework or build | User preference; simplest to deploy on locked-down laptops; works offline |
| Python on ARM | x64 Python under emulation | ARM64 wheels for pyogrio and pyarrow are unavailable |

## 4. Data flow of a tool run
`POST /api/tool-runs` → `validate_params` (types, enum values, layer compatibility, field existence/type) → job is
queued → executor reads inputs through `ctx.input_gdf` (selection, version, SHA recorded) → pure geometry
function → `ctx.write_layer` registers a Gold layer (new id, new `_hpw_fid`, `ORIG_FID` lineage column) →
`manifest.json` + `tool_runs` row (parameters, inputs, outputs, counts, transformations, messages, known
differences, reference URL).

## 5. Security
- Server binds to `127.0.0.1`; no telemetry; the only outbound requests are OSM basemap tiles in the browser, and
  "None (offline)" turns them off.
- Uploads use sanitized file names in a temporary directory, and no user-supplied server paths are accepted.
  Filter expressions go through a parser, never `eval` or SQL. Run IDs are validated before file access.

## 6. Known limitations
- In-memory caches: a very large layer (millions of features) needs vector tiles/DuckDB (roadmap Phase 2).
- Selection state is process-wide (single user), but it is persisted by saving a project.
- No authentication: single-user local deployment.

## 7. Changelog
See `CHANGELOG.md`.
