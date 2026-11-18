# HPW Lightweight GIS Workbench

A local-first, browser-based GIS workbench with a reusable geoprocessing engine. It uses the **publicly documented
behaviour of ArcGIS Pro as a functional reference** and does **not** need ArcGIS Pro, ArcPy, an Esri license, REA
or any cloud service.

Governing specification: [`docs/HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md`](docs/HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md).

## Quick start (Windows, no admin rights)

```powershell
# one-time (creates .venv, installs Python deps, generates synthetic fixtures). No Node/npm needed.
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

# run (API + UI on http://127.0.0.1:8000, local only)
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1

# tests (pytest + JS syntax check when Node is present)
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Requirements: **Python 3.11+ only**. The UI (`web/`) is plain HTML/CSS/JavaScript with MapLibre stored
locally, so there is no build step and it works offline. Always open the app at **http://127.0.0.1:8000/**:
opening `web/index.html` straight from disk can't reach the engine, and the page says so. On **Windows-on-ARM** use **x64 Python**: the ARM64 Python
does not have pyogrio/GDAL or pyarrow wheels. x64 Python runs under emulation (`setup.ps1` picks it if installed).

UI development: edit files in `web/` and refresh the browser (no build). API docs (OpenAPI): http://127.0.0.1:8000/docs

## What works now (Phase 1 vertical slice)

- **Layer registry:** register a layer from a config descriptor (`config/layers.yaml`) or by uploading a file
  (GeoPackage, GeoParquet, GeoJSON, zipped Shapefile, CSV with X/Y or WKT, FlatGeobuf). On import the workbench
  profiles each layer: geometry types, CRS, primary key, invalid/null/empty/duplicate geometry, field nulls and
  uniqueness, and declared relationships. CRS is **never guessed**.
- **Bronze → Silver → Gold lineage:** an immutable copy of the source, a normalized GeoParquet, and versioned
  derived outputs, each with SHA-256 and a provenance manifest.
- **Interface:** ribbon (Map / Analysis / Data / View), Contents, map, attribute table, Geoprocessing pane and
  status bar. Light/dark themes, resizable and closable panes, global search (Ctrl+K), and shortcuts (E explore,
  S select, Esc).
- **Map:** MapLibre with viewport (bbox) feature loading, popups, a legend, click/rectangle selection, zoom to
  layer/selection, scale bars and a 1:N scale readout. Drag-to-reorder layers, color swatches and transparency.
  Basemaps: Streets, Light gray, Dark gray (OSM, online) or None (offline).
- **Attribute table:** server-side paging, multi-sort, search, SQL-like filter, selected-only view, column
  show/hide, field statistics and keyboard navigation. Selection stays synced with the map.
- **Universal toolbox:** forms are generated from registry metadata. Every compatible layer is offered
  automatically, and ineligible layers are listed with the reason.
  - Select Layer By Attribute · Select Layer By Location (11 relationships) · Buffer · Clip · Project ·
    Define Projection · Export Features
- **Jobs:** background execution with status, cancellation, messages, row-count reconciliation, and a run
  history with re-run.
- **Export:** GeoPackage, GeoParquet, GeoJSON (WGS84), CSV (+WKT, CRS header) and zipped Shapefile (with
  field-name and type warnings), for all features or only the selected ones.
- **Projects:** save/open layer order, styles, open tables, map view and selections.

The tool status is **FUNCTIONAL_UNVALIDATED** for every tool: they are tested against synthetic known answers,
but nothing has been compared with ArcGIS reference outputs yet. See
[`docs/ARCGIS_FEATURE_CATALOG.csv`](docs/ARCGIS_FEATURE_CATALOG.csv) and
[`docs/VALIDATION_REPORTS/`](docs/VALIDATION_REPORTS/).

## Repository layout

```text
backend/hpw_gis/        api/ (FastAPI) · registry/ (layers, tools) · gis_tools/ (processing) · storage/ (IO, SQLite)
                        jobs.py (job manager, selection, provenance) · fixtures.py (synthetic QA data)
backend/tests/          unit, property-style, integration and negative tests
web/                    UI: index.html, css/app.css, js/*.js (ES modules), vendor/maplibre (no build)
config/layers.yaml      layer descriptors (no per-layer code)
fixtures/               generated synthetic layers (NOT production data)
workspaces/             local runtime data: SQLite metadata + bronze/silver/gold (git-ignored)
docs/                   architecture, catalog, registry, roadmap, tool specs, validation reports
```
