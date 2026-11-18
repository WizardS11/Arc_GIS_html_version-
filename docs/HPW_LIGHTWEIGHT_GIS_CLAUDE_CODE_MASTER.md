# HPW Lightweight GIS Workbench
## Claude Code Master Specification — Documentation-Driven ArcGIS-Like GIS Platform

**Version:** 1.0  
**Prepared:** 2026-11-13  
**Primary implementation agent:** Claude Code  
**Optional investigation tool:** REA — Reverse Engineer Anything  
**Project type:** Local-first, browser-based GIS workbench with a reusable geospatial processing engine  
**Target:** Support Houston Public Works wastewater and related GIS datasets, without making ArcGIS Pro a runtime dependency.

---

## 0. Instructions for Claude Code — Read This First

You are the **lead GIS software architect, senior geospatial engineer, data engineer, and full-stack developer** for this project. Your assignment is to develop a **usable, lightweight GIS platform** using the **publicly documented behavior and user workflows of ArcGIS Pro as the functional reference**.

This is **not merely a map dashboard**. The platform must allow users to load and manage many GIS layers; explore and edit attributes; select spatial features; run genuine geospatial processing; create derived layers; analyze wastewater networks; and export reproducible results.

**The central requirement:** Implement each operation **once**, in a geometry-aware, schema-driven **universal tool registry**. Every compatible GIS layer should automatically be able to use that operation. Do **not** build a separate Buffer, Clip, Spatial Join, or Select-by-Location implementation for each individual data source.

### Non-negotiable functional goals

1. Use the official ArcGIS Pro documentation to **catalog** features, parameters, constraints, geoprocessing environments, and observable semantics. Implement independently using appropriate libraries.
2. Prioritize functional and computational equivalence over pixel-perfect cloning. Preserve recognizable GIS workflows without copying proprietary source code, artwork, or branding.
3. **ArcGIS installation, ArcGIS license, ArcPy, and REA must NOT be prerequisites** for the core application. REA and reference-output comparisons are optional tools for authorized investigations and validation.
4. Make supported GIS tools available to **all compatible registered layers**, present and future.
5. Guarantee **read-only source inputs by default**. Analysis writes a new, versioned derived dataset unless the user deliberately performs an editable operation.
6. Preserve any **existing project, dashboard, features, routes, APIs, styles, state, and working code**. Do not rewrite or remove unrelated features while implementing a requested change.
7. Write **working code, tests, documentation, and a runnable demonstration**. Do not stop at mockups, README plans, TODO buttons, or nonfunctional UI.
8. Work incrementally. Maintain a documented inventory of supported, partial, deferred, and unsupported capabilities. **Never claim full ArcGIS equivalence without evidence.**
9. If a reasonable implementation decision is unspecified, infer a safe engineering default, document the choice, and continue. Ask questions only when a missing decision creates material risk (e.g., destructive writes, confidential data exposure, ambiguous network direction).
10. Keep the application lightweight and usable on a Windows laptop with limited administrator rights and potentially restricted internet access.

### First action when starting in an existing repository

- Inspect the repository and any existing `CLAUDE.md`, `DATA_SOURCES.md`, `DOCUMENTATION_STANDARD.md`, `INSTALL_INSTRUCTIONS.md`, architecture documents, package manifests, and tests.
- Identify current GIS interfaces and reusable components. Keep existing features unchanged until a scoped modification is justified.
- Produce a brief repository audit and initial implementation plan; then **implement the first complete vertical slice**, not only the plan.
- If the repository is empty, scaffold the minimal working application described in §15.
- Record assumptions, dependencies, and blocked items; do not fabricate existing datasets, schema fields, services, licenses, or tool availability.

---

## 1. Purpose and Product Definition

### 1.1 Vision

Create an independently deployable **HPW GIS Workbench** offering a coherent ArcGIS-like workflow:

**Load layer → Inspect metadata → Display map → Select/filter → Choose tool → Validate parameters → Execute analysis → Inspect derived layer → Compare/export → Save workflow and provenance.**

The workbench is designed for a wastewater utility with gravity sewers, manholes, level sensors, flowmeters, parcels, basins, SSO locations, inspection and maintenance records, and other GIS-linked assets. The architecture must be **general GIS first** and **Houston wastewater specialization second**.

### 1.2 What this project is NOT

- Not a claim that the complete ArcGIS Pro desktop application can be recreated in one iteration.
- Not a replacement for specialized Esri enterprise functionality before independent feasibility and validation.
- Not a pixel-perfect copy of Esri's interface or an extraction of proprietary implementation code.
- Not an ArcPy front end. ArcPy or licensed ArcGIS geoprocessing services may be optional adapters, **never core requirements**.
- Not a static mock dashboard, screenshot clone, or collection of hardcoded per-layer scripts.

### 1.3 Scope policy

Maintain two separate measures:

1. **Coverage** — How much of the documented GIS capability catalog is implemented?
2. **Fidelity** — For each implemented tool, how closely does its documented behavior and validated output match the chosen reference?

A tool can be `NOT_STARTED`, `SPECIFIED`, `IMPLEMENTING`, `FUNCTIONAL_UNVALIDATED`, `VALIDATED`, `PARTIAL`, `DEFERRED`, or `UNSUPPORTED`. Do not represent `FUNCTIONAL_UNVALIDATED` as `VALIDATED`.

---

## 2. Reference Sources and Research Procedure

Use official and legally accessible documentation as the primary source of feature definitions. Verify the relevant documentation version and capture date before implementation.

| Source | URL | Purpose |
|---|---|---|
| ArcGIS Pro geoprocessing tool reference | https://pro.arcgis.com/en/pro-app/latest/tool-reference/main/arcgis-pro-tool-reference.htm | Toolboxes, toolsets, tool pages, parameters, environments, messages |
| Analysis toolbox | https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/an-overview-of-the-analysis-toolbox.htm | Extract, Overlay, Pairwise Overlay, Proximity, Statistics |
| Data Management toolbox | https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/an-overview-of-the-data-management-toolbox.htm | Fields, features, projections, joins, geodatabases, topology, raster data |
| Esri developer docs | https://developers.arcgis.com/javascript/latest/ | Web map workflows, layers, queries, editing and visualization reference |
| REA official repository | https://github.com/morluto/rea | Optional investigation tool and installation guidance |
| REA installation guide | https://github.com/morluto/rea/blob/main/docs/getting-started/installation.md | Agent connection and setup |

### 2.1 Documentation-to-implementation pipeline

For **each tool**:

1. Discover the official tool and its containing toolbox/toolset.
2. Read and summarize: summary, intended purpose, input/output parameters, defaults, permissible values, geometry restrictions, coordinate-system requirements, environment settings, warnings, error behavior, licensing notes, and relevant examples.
3. Record the **reference URL and retrieval date**. Link to the source; do not copy lengthy copyrighted documentation into the repository.
4. Define the equivalent behavior of our tool. Explicitly mark any semantic gaps or parameters we cannot reproduce.
5. Identify suitable independent implementation methods (GEOS/Shapely, GeoPandas, PyProj, GDAL, DuckDB Spatial, rasterio, NetworkX, etc.).
6. Implement a **pure, testable processing operation** that is independent of the UI.
7. Register it with the universal tool catalog (input types, parameters, executor, output types, validation rules).
8. Create its UI form automatically from the registry metadata where possible.
9. Add synthetic test cases and selected real-data validation samples; compare ArcGIS reference outputs **only when legally and operationally available**.
10. Record validated features, deviations, precision tolerances, runtime, known limitations, and examples.

Avoid broad, uncontrolled scraping of documentation. Catalog the toolbox tree first, then inspect individual tools in prioritized batches, obeying source access restrictions and terms of use.

### 2.2 Optional REA workflow

REA is **not a requirement** for documentation-driven development. Invoke it **only** if it is connected, supports the target, and the user is authorized to inspect the application/artifacts.

- Use REA to investigate permitted applications or JavaScript modules when a feature's interface or observable workflow is unclear.
- Consult **actual installed REA tool schemas**; do not invent tool names, arguments, or access to ArcGIS internals.
- REA findings are investigation evidence, **not proof of computational equivalence**.
- Do not bypass authentication, licensing, encryption, access controls, or other technical protections.
- Do not reverse engineer proprietary binaries or internal enterprise systems without explicit authorization and appropriate legal review.
- If REA is unavailable, proceed from official docs, public examples, test fixtures, and open-source libraries.

**Optional REA setup (review changes before approval):**

```bash
npx rea-agents setup
```

Select Claude Code as the target client, review proposed modifications, approve only intended changes, and restart Claude Code when prompted. Do not install or modify agent tooling automatically in this project.

---

## 3. System Architecture

### 3.1 Preferred architecture

```text
┌───────────────────────────────────────────────────────────────┐
│ WEB CLIENT: React + TypeScript + MapLibre GL JS                │
│ Map | Layer Catalog | Table | Query | Toolbox | Workflow | QA │
└─────────────────────────────┬─────────────────────────────────┘
                              │ REST / task status / result tiles
┌─────────────────────────────▼─────────────────────────────────┐
│ APPLICATION API: Python FastAPI                                │
│ Layer registry | Tool registry | Auth boundary | Job manager   │
│ Validation | Status/cancel | Result catalog | Provenance        │
└─────────────────────────────┬─────────────────────────────────┘
                              │ typed tool calls
┌─────────────────────────────▼─────────────────────────────────┐
│ UNIVERSAL GIS PROCESSING ENGINE                               │
│ GeoPandas/Shapely/GEOS | PyProj | GDAL/OGR | DuckDB Spatial    │
│ rasterio (optional) | NetworkX (optional domain engine)        │
└─────────────────────────────┬─────────────────────────────────┘
                              │ read sources / write derivatives
┌─────────────────────────────▼─────────────────────────────────┐
│ DATA AND PROVENANCE                                            │
│ Bronze immutable | Silver normalized | Gold results            │
│ GeoParquet | GeoPackage | CSV | Raster | optional PostGIS       │
│ Layer metadata | Tool runs | Workflow manifests | QA logs       │
└───────────────────────────────────────────────────────────────┘
```

### 3.2 Recommended technologies

| Area | Recommended default | Notes |
|---|---|---|
| Front end | React, TypeScript, Vite | Reuse a compatible existing front end if present |
| Map rendering | MapLibre GL JS | Avoid ArcGIS credential dependency; permit authorized alternative basemaps |
| Drawing and editing | Terra Draw or comparable supported library | Validate geometry and edit transaction behavior |
| Data table | TanStack Table | Column sort, search, filter, pin, visibility, virtualization, CSV export |
| API | FastAPI + Pydantic | Validate request and response schemas |
| Vector GIS | Shapely, GeoPandas, PyProj | Projection, spatial operations, geometry utilities |
| File IO | GDAL/OGR + GeoParquet + GeoPackage | Probe driver support at runtime; do not assume all drivers work |
| Large tables | DuckDB + spatial extension | Local columnar analytics; verify extension availability offline |
| Raster (later) | rasterio, NumPy, GDAL | Optional; do not force raster dependencies on phase 1 |
| Network analysis | NetworkX + purpose-built sewer graph rules | Trace by physical and attribute topology, not display order |
| Persistence | Local project folders + SQLite metadata | Optional PostgreSQL/PostGIS adapter later |
| QA | pytest, hypothesis where appropriate, frontend unit tests, Playwright | Include numerical geometry checks and end-to-end workflows |

### 3.3 Deployment and runtime rules

- **Core must run without ArcGIS Pro, ArcPy, proprietary Esri services, or a paid license.** Optional integrations are capability-gated.
- First deployment target: **Windows developer laptop** without requiring Docker, Kubernetes, cloud services, or administrator privileges.
- Support configurable local paths and offline operation for processing; map basemaps may require connectivity unless local tiles are configured.
- Avoid mandatory cloud upload, telemetry, public endpoints, or exposure of City datasets. Default server bind to `127.0.0.1`.
- Keep spatial algorithms on the backend when datasets are large; do not ship an entire city network to the browser by default.
- Use spatial indexes, bounding-box queries, level-of-detail rendering, streaming/tiling, background jobs, and pagination for large datasets.
- Persist workspaces and workflow manifests so projects survive reloads.

---

## 4. Layer Registry — Every Tool Must Work Across Compatible Layers

### 4.1 Required normalized layer metadata

Each layer must have a machine-readable descriptor:

```yaml
layer_id: gravity_mains
label: Gravity Mains
source:
  uri: ${DATA_ROOT}/sewer/gravity_mains.parquet
  format: geoparquet
  refresh_policy: manual
geometry:
  type: LineString           # Point | MultiPoint | LineString | MultiLineString | Polygon | MultiPolygon | Raster | Table
  crs: EPSG:XXXX             # Discover actual CRS; never guess
  geometry_column: geometry
identity:
  primary_key: UFID          # Verified unique, non-null key
  natural_keys: []
relationships:
  - local_field: US_MANHOLE
    target_layer: manholes
    target_field: MH_NUMBER
    kind: many_to_one
    validation: explicit
  - local_field: DS_MANHOLE
    target_layer: manholes
    target_field: MH_NUMBER
    kind: many_to_one
    validation: explicit
permissions:
  source_read_only: true
  allow_derived_outputs: true
  allow_source_edits: false
metadata:
  lineage_tier: bronze
  owner: configured_by_deployment
```

`EPSG:XXXX` is a **placeholder**, not a supported CRS. The application must refuse distance/area-sensitive processing until the actual coordinate reference is confirmed.

### 4.2 Initial layer families

| Layer family | Typical geometry | Candidate identity / relationship | Notes |
|---|---|---|---|
| Gravity sewer mains | Lines | `UFID`, upstream/downstream manhole references | Confirm schema and orientation; support topology |
| Manholes | Points | `UFID`, `MH_NUMBER` | Verify natural-key uniqueness and duplicates |
| Flowmeters | Points | Site/meter ID; connected pipe or MH when validated | Join time-series via stable meter ID |
| Level sensors | Points | `site_id` / `site_name`; MH UFID link table | Do not treat `site_name` as unique by default |
| Drainage / sewer basins | Polygons | Basin key from source schema | Containment, aggregation, clip |
| Parcels / HCAD | Polygons | Parcel or account key as provided | Potential one-to-many parcel/asset relations |
| SSO / 311 / O&M events | Points or tables | Event ID, asset foreign keys | Include temporal attributes |
| Inspections / pipe condition | Tables and linked geometry | Inspection ID, pipe UFID | Join by documented PK/FK only |
| Other future GIS layers | Any supported geometry | Dynamic schema metadata | No code changes for basic tool compatibility |

These are **candidate fields**, not claims that every local file has those columns. Inspect and map the real schemas during onboarding. Never silently join on ambiguous or non-unique IDs.

### 4.3 Onboarding flow

1. Detect file type, fields, geometry types, feature count, extent, null count, duplicates, CRS, source timestamp, and file encoding.
2. Identify a real PK or create a stable internal surrogate while retaining the source identity. Surface PK violations.
3. Preserve source fields verbatim; maintain optional normalized aliases separately.
4. Detect likely relationships and propose them; activate only after field-level validation.
5. Check for invalid/missing geometries, coordinate anomalies, mixed geometry, duplicate features, and CRS mismatch.
6. Make the layer available in map, attribute table, selection, and every compatible tool.
7. Record source→normalized→derived lineage; do not overwrite the original.

### 4.4 Supported input and export formats

- **Priority:** GeoParquet, GeoPackage, GeoJSON, zipped Shapefile, CSV with explicit coordinates or WKT/WKB, and supported raster formats later.
- **Conditional:** File geodatabase (`.gdb`) read/write depending on installed GDAL drivers; ArcGIS feature services only through authorized documented API access.
- **Export:** GeoParquet, GeoPackage, GeoJSON, CSV (with coordinate/geometry conventions), zipped Shapefile with warnings about field limits and type loss.
- Make output CRS, encoding, precision, column mapping, and geometry type explicit; never silently drop columns or change units.

---

## 5. Universal Geoprocessing Tool Contract

Every tool must implement the same registration and execution lifecycle.

### 5.1 Registry contract

```json
{
  "id": "analysis.buffer",
  "name": "Buffer",
  "category": "Proximity",
  "reference_documentation_url": "https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/buffer.htm",
  "geometry_inputs": ["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"],
  "inputs": [{"name": "input_layer", "type": "vector_layer", "required": true}],
  "parameters": [
    {"name": "distance", "type": "number", "required": true},
    {"name": "units", "type": "enum", "values": ["meters", "feet", "kilometers", "miles"]},
    {"name": "dissolve", "type": "enum", "values": ["none", "all", "by_field"]},
    {"name": "distance_mode", "type": "enum", "values": ["planar", "geodesic"]}
  ],
  "executor": "gis_tools.proximity.buffer",
  "output_type": "polygon_layer",
  "writes_source": false,
  "validation_required": true
}
```

**This JSON is illustrative.** Before implementing Buffer, inspect the actual reference parameters and semantics. Only expose behavior supported by the implementation; do not imply parity for unsupported end-cap, dissolve, negative distance, or geodesic options.

### 5.2 Standard execution lifecycle

```text
DISCOVER TOOL → SELECT COMPATIBLE LAYERS → ENTER PARAMETERS
   → VERIFY PK/GEOMETRY/CRS/UNITS/NULLS/PERMISSIONS
   → ESTIMATE COST → EXECUTE AS JOB → VALIDATE RESULT
   → REGISTER DERIVED LAYER → SHOW MAP + TABLE + QA
   → EXPORT / SAVE WORKFLOW / RE-RUN
```

Every execution result includes:

- `run_id`, `tool_id`, implementation version, execution timestamps, runtime duration.
- Input layer IDs, paths or controlled references, dataset version/hash, PK fields, source feature counts.
- Full parameters, CRS transformations, units, geodesic/planar method, numeric precision/tolerance.
- Output layer ID, format, CRS, schema, record count, path, optional preview, validation summary.
- Warning/error messages, invalid/omitted feature counts, null-handling behavior.
- Link to the original public tool reference and statement of any non-equivalent behavior.

### 5.3 Compatibility rules

- Tools declare supported geometry families and required attributes, never hardcoded layer names.
- Universal layer picker shows all **compatible** layers; incompatible layers are disabled with an explanation.
- Attribute-only tools accept non-spatial tables.
- Geometry transformations preserve stable source references via `source_layer_id`, `source_feature_id`, and `run_id` where feasible.
- If one input produces many outputs, generate independent output feature IDs and a lineage/mapping table. Never assume output IDs equal source IDs.
- Any user-facing processing action must execute real code or clearly state it is unavailable; **no fake success states or decorative buttons**.

---

## 6. Comprehensive Feature Inventory / Implementation Backlog

The long-term objective is **broad coverage of documented GIS capabilities**. Maintain a continuously updated catalog, not a blanket claim of “all ArcGIS features completed.” The initial categories and specific tools are below. Implement capability by capability based on usefulness and technical feasibility.

### 6.1 Core mapping and exploration — P0

- [ ] Layer explorer: groups, visibility, order, opacity, per-layer legend, metadata, feature counts.
- [ ] Basemaps: configurable providers, attribution, projection behavior, optional offline background tiles.
- [ ] Pan, zoom, zoom-to-extent, zoom-to-selection, bookmarks, coordinate display, scale bar.
- [ ] Map and table synchronized selection, clear/invert selection, rectangle/polygon/lasso selection where supported.
- [ ] Feature identify/popups with related records and editable field formatting.
- [ ] Labels, categorized/unique-value symbology, graduated colors, size-by-attribute, line styles, legends.
- [ ] Measure distance/area with explicit units and planar/geodesic method.
- [ ] Layer-specific attribute filter and global asset search.
- [ ] Save/open named projects containing layer state, styles, bookmarks, queries, and tool history.

### 6.2 Attribute, query, and data management — P0/P1

- [ ] Search, sort, filter, multi-column sort, type-aware filters, column hide/show/pin/reorder.
- [ ] Select by attributes with validated SQL-like query builder and safe parameterization.
- [ ] Statistics: count, sum, mean, median, min, max, standard deviation, distinct values, null counts.
- [ ] Add/calculate/rename/drop field on **derived copies**; preview schema changes.
- [ ] Attribute join, relate, one-to-one/one-to-many behavior and cardinality warnings.
- [ ] Find duplicates, null report, type conversion, field mapping, schema comparison.
- [ ] Export full/filtered/selected rows with explicit feature IDs and CRS.
- [ ] Merge/append datasets with schema compatibility report.
- [ ] Reproject/define CRS (two **different** operations), geometry repair, multipart/singlepart.
- [ ] Spatial and attribute indexing where supported.

### 6.3 Vector analysis — P0/P1

- [ ] Select by location: intersects, contains, within, touches, crosses, overlaps, within distance.
- [ ] Buffer: single/multiple distance, units, dissolve, geometry handling, planar/geodesic semantics.
- [ ] Clip, Intersect, Erase/Difference, Union, Identity/Update where appropriate.
- [ ] Pairwise equivalents, with explicit behavior/performance differences.
- [ ] Dissolve/aggregate by field, multipart output, statistics.
- [ ] Spatial Join: intersects, nearest, distance threshold, one-to-one / one-to-many and match count.
- [ ] Near / Generate Near Table, k-nearest features, distance calculation.
- [ ] Summarize Within, feature count and aggregation by polygon, proportion handling.
- [ ] Centroid vs point-on-surface, polygons-to-lines, lines-to-points, vertices-to-points.
- [ ] Split/merge features, erase by selection, overlay result attribute provenance.
- [ ] Geometry metrics: length, area, perimeter, centroid, point coordinates, bounds.
- [ ] Spatial aggregation for basins, parcels, sensors, pipes, and user-defined layers.

### 6.4 Editing and topology — P1/P2

- [ ] Create/edit/delete features only in explicitly editable layers or controlled copies.
- [ ] Vertex editing, snapping, split, merge, reshape, undo/redo and edit audit log.
- [ ] Geometry validity reports, overlaps/gaps/slivers, multipart anomalies, duplicate edges.
- [ ] Topology rules configured per layer pair; validate and highlight violations.
- [ ] Transactional save, conflict detection, snapshots, rollback and permission checks.
- [ ] Never silently “fix” network connectivity or move engineering assets.

### 6.5 Network / utility workflows — P1/P2

- [ ] Construct nodes/edges from explicit `US_MANHOLE`→`DS_MANHOLE` or verified endpoint topology.
- [ ] Upstream/downstream selection and trace; report branches, disconnected components, loops.
- [ ] Trace from selected manhole, pipe or sensor-linked asset to basin outlet/pump station.
- [ ] Identify orphan links, duplicate connections, reversed-flow candidates, missing invert, split/merge nodes.
- [ ] Shortest path and network-distance as a separate operation from gravity-flow trace.
- [ ] Asset relationship join through verified identifiers and spatial tolerance.
- [ ] Export selected network subgraph, contributing pipe IDs, total length, counts and validation messages.
- [ ] Advanced hydraulic interpretation is a separate **engineering module**, not an assumed feature of a basic geometric trace.

### 6.6 Advanced modules — P2/P3, feature-gated

- [ ] Rasters: import/render, raster calculator, zonal statistics, sampling, reclassify, slope/aspect as applicable.
- [ ] Spatial statistics: density, clustering, hot spots and interpolation where scientifically defensible.
- [ ] Time-aware map layers, temporal filters and animated history.
- [ ] ModelBuilder-like workflow graph with typed nodes, dependencies, validation and re-execution.
- [ ] Batch geoprocessing and scheduled **local** runs when requested.
- [ ] 3D/scene capabilities through a dedicated feasibility study.
- [ ] Enterprise/versioned geodatabase, Utility Network, and advanced extension parity only after separate architecture, licensing and data-model review.

---

## 7. GIS Processing Correctness Standards

Geospatial analysis is sensitive to geometry semantics and metadata. **Map appearance does not demonstrate that analysis is correct.**

### 7.1 Mandatory safeguards

- **CRS:** Preserve original CRS; never guess a missing CRS. Transform geometries deliberately. Keep map display CRS separate from measurement CRS.
- **Units:** Geographic degrees are not automatically meters or feet. Validate linear/angular units before buffering, area, lengths, or near calculations.
- **Geodesic versus planar:** Expose supported methods; if the reference requests an unsupported method, fail clearly rather than returning misleading output.
- **Geometry validity:** Detect empty, null, self-intersecting and invalid geometry. Document whether records were repaired, skipped or rejected.
- **Topology:** Handle exact shared nodes, snapping tolerance, near-coincident nodes, loops, multipart edges and disconnected networks explicitly.
- **Precision:** Make coordinate precision, tolerance and overlay sliver handling reproducible. Do not claim byte-for-byte equivalence across differing computational geometry engines.
- **Joins:** Validate join cardinality and key uniqueness; never silently multiply or drop pipe features.
- **Attributes:** Preserve source fields and types where possible; record null behavior, timezones, delimiters, string normalization and truncation.
- **No silent drops:** Report row counts at input, filtered, valid, processed, excluded and output stages.
- **Numerical safety:** Protect division by zero, overflow, non-finite measurements and empty aggregation sets.

### 7.2 Minimum quality checks per tool

1. Input schema and geometry compatibility.
2. All required parameters supplied and in range.
3. Validated CRS and units.
4. Deterministic sample with known result.
5. Output feature count and geometry type reasonable for tool.
6. Output geometry validity and coordinate ranges.
7. Stable provenance and identifiers.
8. Repeated execution with identical inputs produces equivalent outputs within documented tolerance.
9. Null, empty, invalid, multipart and mixed-CRS negative tests.
10. When ArcGIS benchmark output exists, compare matching features, geometry area/length/intersection-over-union, distances, attribute mappings and output counts.

### 7.3 Tool acceptance report

```text
Tool: analysis.spatial_join
Documentation reference: <URL and date>
Implementation: <module/function and version>
Input geometries: <allowed types>
Parameters implemented: <list>
Known differences: <list>
Tests: <unit, property-based, integration, UI>
ArcGIS comparison: not available | partial | completed
Validation metrics: feature count, key coverage, geometry difference,
                    null handling, cardinality, distance/area tolerance
Runtime: <dataset size / hardware / elapsed / peak memory>
Status: VALIDATED | PARTIAL | FUNCTIONAL_UNVALIDATED
```

---

## 8. Houston Wastewater-Specific Engineering Rules

These are **plug-in domain workflows**, using the same general GIS platform and layer registry.

### 8.1 Gravity sewer network

- The gravity network is a **directed graph** only if direction is supported by verified `US_MANHOLE` and `DS_MANHOLE` attributes or an approved engineering rule.
- GIS line digitization direction may not equal hydraulic direction; never infer gravity flow from shape vertex order alone.
- Validate manhole references, duplicate IDs, missing links, multiple downstream branches, gravity anomalies and loops.
- Track edge identifier (`UFID` when validated), source/destination node keys, pipe length, diameter, slope, invert elevations and capacity fields **only if present**.
- Trace results should include upstream/downstream feature IDs, cumulative lengths, connectivity issues and any excluded features.
- Hydraulic computations (e.g., Manning capacity, DWF, RDII, q/Q) belong to separate, explicitly validated calculators. A map-only network trace does **not** simulate hydraulics.
- If multiple flow splits/merges exist, do not invent a flow allocation rule in the GIS network engine.

### 8.2 Sensors, meters, parcels, and basins

- Join sensors to manholes/pipes through curated, tested link tables, not by a name similarity guess.
- Support sensor proximity, contributing basin membership, asset context, and spatial cross-filtering.
- Support pipe/parcel/basin overlay analysis while keeping area or length allocation rules explicit.
- Support time-series data as related tables keyed by stable sensor/meter IDs; do not copy raw time-series into map feature payloads.
- Allow user-defined inspections, maintenance and SSO points/tables without rewriting spatial tools.

### 8.3 Reusable wastewater analyses

- Select all gravity mains inside a basin.
- Buffer a sensor or manhole by a user-selected distance and identify nearby assets.
- Spatial join SSO events to pipes/basins with explicit distance and tie-resolution rules.
- Trace upstream pipes from a selected manhole and summarize length, diameter, upstream sensors and potential contributing parcels.
- Aggregate pipe metrics by basin, retaining weighted formulas and denominators in output metadata.
- Compare source-versus-derived pipe flow measures on verified pipe IDs without altering their underlying source tables.

---

## 9. Data Architecture and Lineage

Adopt an explicit **Bronze → Silver → Gold** approach.

| Tier | Meaning | Write policy | Examples |
|---|---|---|---|
| Bronze | Immutable copies / references to ingested source datasets | Read-only | Original mains, manholes, parcel and sensor files |
| Silver | Cleaned, normalized, validated GIS tables and link maps | Versioned transformations | Geometry repair report, validated PK/FK, standardized CRS |
| Gold | Tool outputs, derived spatial analytics, stakeholder-ready results | Reproducible from Silver | Buffer, clip, basin summary, upstream traces |

For every derived output, retain `run_id`, `tool_id`, input version(s), timestamp, parameter JSON, CRS metadata, row counts, warnings, and a source-to-output feature mapping when meaningful.

Do not require copying terabytes of source data into a new database. Support references to local files with stable checksums and a documented change-detection strategy.

### 9.1 Minimum relational contracts

- `layers.layer_id` — PK for registered GIS layers.
- `layer_versions.version_id` — PK; `layer_id` FK to `layers`.
- `feature_registry` — optional stable feature reference: (`layer_version_id`, `source_feature_id`).
- `relationships.relationship_id` — PK; explicit source/target layer+field pairs and cardinality.
- `tools.tool_id` — PK for processing operations.
- `tool_runs.run_id` — PK; `tool_id` FK; parameters, executor version, status, duration.
- `run_inputs` — (`run_id`, `layer_version_id`) FK associations.
- `run_outputs` — (`run_id`, `layer_version_id`) FK associations.
- `workflow_definitions.workflow_id` — PK; typed node graph specification and revision.

Persist source schema mappings and testable data-quality constraints rather than relying on implicit column names.

---

## 10. User Experience and Interface Requirements

### 10.1 Desktop-style web workspace

A clean, responsive interface with these **functional** panels:

- **Top toolbar:** Open project, add layers, save project, search, selection tools, measure, run history, export.
- **Left pane:** Layer manager, groups, visibility, drag-to-reorder, styling, legend and metadata.
- **Center:** Interactive map, basemap controls, zoom, scale, feature selection and live progress overlays.
- **Right pane:** Searchable geoprocessing toolbox, dynamic tool parameters, results, validation and processing messages.
- **Bottom pane:** Virtualized attribute table, sorting/filtering/search, column controls, selected features, CSV/GeoPackage/GeoParquet export.
- **Workflow view:** Optional node graph for multistep analysis with named inputs/outputs and run status.

### 10.2 User actions and expected behavior

- Clicking a mapped feature highlights the corresponding attribute-table row; table selection highlights the map.
- All tools have input layer selectors populated from compatible registered layers; user sees eligibility explanations.
- Tool parameters are prevalidated (required fields, units, geometry type) before launch.
- Long-running tasks display job status and cancellation; failed operations show actionable errors and leave source unchanged.
- A successful tool creates a new visible layer and an output table, with links to inspect/export and a reproducibility manifest.
- Every table must support search and sorting; each layer's data should be downloadable, subject to permissions.
- Layer controls, filters and output selections persist as part of a saved project.
- Color conventions are meaningful and accessible; do not imply severity with arbitrary hues.
- UI provides keyboard-accessible actions and does not require a mouse for basic data/table interactions.

---

## 11. API and Processing Contracts

Suggested endpoints; adapt to existing repository conventions rather than introducing duplicate services:

```text
GET    /api/health
GET    /api/layers
POST   /api/layers/import
GET    /api/layers/{layer_id}/metadata
GET    /api/layers/{layer_id}/features?bbox=...&limit=...
GET    /api/layers/{layer_id}/table?filter=...&sort=...&page=...
GET    /api/tools
GET    /api/tools/{tool_id}
POST   /api/tool-runs
GET    /api/tool-runs/{run_id}
POST   /api/tool-runs/{run_id}/cancel
GET    /api/tool-runs/{run_id}/result
GET    /api/projects
POST   /api/projects
GET    /api/workflows
POST   /api/workflows/validate
POST   /api/workflows/execute
```

Use typed Pydantic schemas. Validate user-specified paths, access, geometry inputs, projected units and resource limits server-side. Reject unsafe SQL strings and filesystem path traversal. Return structured errors, not empty datasets disguised as success. Restrict large queries by pagination, tiling, column selection and bounded resource usage.

---

## 12. Performance and Operational Design

Plan for many city GIS layers and a sewer network covering thousands of miles.

- Render the current map extent using tile/viewport queries instead of loading all features into the browser.
- Use spatial indexes (STRtree/R-tree), Parquet row-group pruning, and bounding boxes.
- Keep attribute tables paginated/virtualized; support server-side sort/filter for large tables.
- Separate UI and processing jobs; limit concurrent heavy jobs and peak memory.
- Expose operation status and errors, and support cooperative cancellation.
- Measure performance on representative **small, medium, and large** datasets and record hardware and resource consumption.
- Avoid needless dependency weight and large external services for a local-first deployment.
- Ensure all processing works without internet after dependencies are installed, except explicitly remote data sources or basemaps.

---

## 13. Security, Licensing, and Responsible Investigation

- Respect software licenses, Esri trademarks, and copyright. Implement independent equivalent features using documented behavior; do not reuse proprietary implementation code or graphics.
- Never bypass license enforcement, authentication, access restrictions or encryption.
- Use only City/organization data, applications and services that are approved for the project and the developer's access level.
- Do not transmit confidential utility data to third-party services, package telemetry, or public repositories without authorization.
- Do not bake actual passwords, API keys, access tokens, personal information or sensitive system paths into the repository.
- Depend on basemap and geocoding services only when terms and credentials permit; keep the application usable without them.
- Default all ingested source data to read-only. Require an explicit edit mode and controlled write path for any mutation.

---

## 14. Testing Strategy and Engineering Acceptance Gates

### 14.1 Testing pyramid

- **Unit tests:** Geometry predicates, parameters, field expressions, duplicate handling, coordinate transforms.
- **Property-based tests:** Invariants (e.g., clip output lies within clip polygon tolerance; dissolve geometry covers input union within tolerance).
- **Integration tests:** File import → tool execution → saved output → readback → provenance.
- **Domain tests:** Directed sewer tracing, missing nodes, loops, splits, merges, incorrect flow direction.
- **UI tests:** Import, selection sync, tool forms, progress, error messaging, attribute sorting and downloads.
- **Performance tests:** Representative city-scale subsets and full-layer workload samples, with measured memory and runtime.
- **Golden tests:** ArcGIS exported sample outputs **if available**, otherwise documented synthetic fixtures and independent GIS-library results.

### 14.2 A tool is accepted only when

- It is discoverable in the toolbox and its form is usable.
- It runs real processing and generates a correct persistent output (not only a map highlight).
- The output is visible on the map and in an attribute table.
- It supports all eligible input layers under the tool's published constraints.
- It passes validation tests and does not silently omit features.
- It exposes meaningful warnings and unsupported semantics.
- It produces exportable outputs and a provenance manifest.
- Existing features remain operational and regression tests pass.

### 14.3 Baseline QA datasets

Create a small **synthetic** test dataset with:

- Points, polylines, polygons and multipart features.
- Known overlaps, holes, invalid/self-intersecting polygons and zero/near-zero distances.
- Mixed null fields and keys, duplicated IDs and one-to-many joins.
- Simple and branched sewer graphs; disconnected edges and directed cycles.
- Explicit sample CRSs, including geographic and projected coordinates.

Use synthetic fixtures by default for automated tests; do not commit sensitive GIS datasets.

---

## 15. Delivery Roadmap: Implement, Do Not Merely Propose

### Phase 0 — Repository audit + feature catalog

**Outputs:**

1. `docs/ARCHITECTURE.md` — architecture and dependency decisions.
2. `docs/ARCGIS_FEATURE_CATALOG.csv` — tool ID, toolbox, reference URL, summary, supported geometry, priority, implementation status and validation status.
3. `docs/LAYER_REGISTRY.md` — known source layers, PK/FK, CRS, data quality and mapping decisions.
4. `docs/DEVELOPMENT_ROADMAP.md` — prioritized functional increments, dependencies, risks and acceptance tests.
5. Baseline build/test evidence for the existing application.

**Do not stop here.** Continue to the minimum working vertical slice in Phase 1.

### Phase 1 — Working GIS foundation (first usable vertical slice)

- Project starter with backend and frontend, respecting existing application structure.
- Import and register **at least one Point, one Line, and one Polygon synthetic layer**.
- Map them with layer visibility, style, identify, and synchronized attribute tables.
- Geometry/CRS/PK detection and validation warnings.
- Implement real `Select by Attributes`, `Select by Location`, `Buffer`, and `Clip`.
- Generate a new persistent layer for each geoprocessing result.
- Export GeoParquet or GeoPackage and CSV for suitable layers.
- Save processing history/provenance and run unit/integration/UI tests.

**Release gate:** An independent user can import a sample layer, run Buffer and Clip, inspect resulting geometry and attributes, and export a persisted output without ArcGIS.

### Phase 2 — General-purpose 2D GIS

- Spatial Join, Intersect, Dissolve, Erase, Union, Near, Summarize Within, Reproject, Calculate Field, and Merge.
- Tool forms generated from registry metadata and dynamic compatibility checks.
- Bulk import, robust table/filter tools, geometry repair, optional layer styling presets.
- Additional negative tests and performance benchmarks.

### Phase 3 — GIS editing, network, and workflow automation

- Controlled geometry editing, snapping, topology diagnostics.
- Upstream/downstream sewer trace and asset linkage.
- Batch tools, named workflow chains, saved/reproducible analysis projects.

### Phase 4 — Optional specialized tools

- Raster analysis, more sophisticated spatial statistics, time-aware views, advanced workflow editor.
- Evaluate specialized ArcGIS capabilities separately; do not bundle unsupported parity into the 2D GIS acceptance claim.

### Recommended prioritization

Within each phase, prioritize: **functional accuracy → universal reusability → validated output → performance → visual polish**. Where practical, polish the interaction while implementing the associated functional slice rather than postponing usability completely.

---

## 16. Claude Code Work Discipline — Protect Existing Functionality Without Restricting Creativity

1. **Understand intent before modifying code.** Read relevant source files, tests, interface contracts, and dependencies.
2. **Scope changes.** Preserve unrelated existing features, states, styles, workflows and data contracts. A request to add/modify Tool X does not authorize removing Tool Y.
3. **Creative implementation allowed.** You may introduce appropriate libraries, architecture improvements or UX refinements **inside the requested scope** when they demonstrably improve quality.
4. **Ask before destructive changes.** Deleting existing functionality, migrating existing data in place, changing authoritative engineering formulas or exposing confidential services requires user approval.
5. **Keep implementation substantive.** No UI-only stubs, dummy success responses, fake exports or silent fallback calculations. If functionality is not ready, label it clearly.
6. **Prefer measured evidence.** Validate with fixtures, real reference outputs when available, and regression tests rather than assuming correctness.
7. **Document trade-offs.** Name deviations from ArcGIS clearly; propose alternatives when exact behavior is not achievable without licensed dependencies.
8. **Avoid overengineering.** Use lightweight local components until real workload evidence justifies more infrastructure.
9. **Do not create separate duplicate implementations for each GIS layer.** Extend the registry, metadata or adapter instead.
10. **Report clearly what changed** after each increment: files modified, new features, output examples, tests, limitations, next actions.

---

## 17. Required Documentation Structure

For major modules and SOPs, organize engineering documentation as:

1. **Purpose** — user need and reference behavior.
2. **Inputs** — files/services, geometry, CRS, field mapping, explicit PK/FK and cardinality.
3. **Method / Processing Steps** — algorithms, spatial predicates, units, parameters, assumptions.
4. **Outputs** — schemas, derived data, saved paths, provenance and layer registry updates.
5. **Validation** — tests, row-count reconciliation, geometry checks, numerical comparisons, known deviations.
6. **Changelog** — implementation date, version, scope, regression outcome.

Suggested repository structure (adapt to an existing application rather than blindly recreating directories):

```text
project-root/
├── CLAUDE.md                           # Can link to this master spec
├── docs/
│   ├── HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md
│   ├── ARCHITECTURE.md
│   ├── ARCGIS_FEATURE_CATALOG.csv
│   ├── LAYER_REGISTRY.md
│   ├── TOOL_SPECS/
│   ├── VALIDATION_REPORTS/
│   ├── DEVELOPMENT_ROADMAP.md
│   └── CHANGELOG.md
├── frontend/
│   └── src/                             # Map, layers, tables, toolbox, workflows
├── backend/
│   ├── api/                             # REST, validation, job orchestration
│   ├── registry/                        # Layer and tool catalogs
│   ├── gis_tools/                       # Reusable geometry/attribute processors
│   ├── network/                         # Domain-specific topology and tracing
│   ├── storage/                         # IO and lineage
│   └── tests/
├── fixtures/                            # Synthetic, non-sensitive test GIS layers
├── config/                              # Layer descriptors and settings
└── workspaces/                          # Ignored/local derived layers and projects
```

Do not commit data secrets or production GIS exports; configure `.gitignore` appropriately.

---

## 18. First Claude Code Execution Prompt

> **Copy and paste the following into Claude Code after placing this file in your repository.**

```text
Read docs/HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md as the governing specification.
Also inspect existing CLAUDE.md, DATA_SOURCES.md, DOCUMENTATION_STANDARD.md,
INSTALL_INSTRUCTIONS.md, source code, and tests if those files exist.

Our objective is a production-oriented, lightweight, ArcGIS-like GIS workbench
for all compatible registered GIS layers. No ArcGIS Pro license, ArcPy,
REA, or cloud runtime should be required for core operations.

Use official ArcGIS Pro user/tool documentation as the functional reference,
not as code to copy. REA is optional for authorized inspection if available.
Build a universal geometry-aware tool registry and real Python geoprocessing
backend with an interactive HTML/React map, layer management, attribute
workspace, derived-layer results, exports, provenance, and validation.

First audit the current repository and preserve existing functionality.
Then implement a complete first vertical slice using synthetic Point, Line,
and Polygon datasets: import, visualize, inspect attributes, select features,
run Buffer and Clip, create output layers, inspect tables, and export results.
Include tool metadata, CRS/PK safeguards, tests, and a runnable local setup.

Do not stop at a plan or mockup. Do not edit or remove unrelated modules.
If source datasets are unavailable, use documented synthetic fixtures and
configurable layer descriptors; never invent production schema details.

Return: a concise architecture and change summary, files modified,
exact local run commands, test results, implemented-vs-deferred features,
processing-validation evidence, and the next prioritized increment.
```

---

## 19. Definition of Project Success

The project succeeds when a user can:

1. Register a new supported GIS layer by configuration or import, without adding per-layer code.
2. View and query it immediately in the common map and attribute table.
3. Discover the relevant GIS tools based on geometry, fields, and permissions.
4. Execute those operations with **correct geospatial processing**, clear warnings, and documented units/CRS behavior.
5. Save, inspect, export, and reproduce derived results while preserving original data.
6. Trace and analyze wastewater assets through a validated, optional domain-specific module.
7. Run the core workbench locally without ArcGIS software or an Esri runtime license.
8. Verify implemented tools through documented testing and an honest coverage/fidelity catalog.

**Core principle:** Build **one scalable GIS engine for all layers**, not isolated visual imitations of ArcGIS screens.

---

## 20. Project Changelog

| Date | Version | Change |
|---|---|---|
| 2026-11-13 | 1.0 | Initial Claude Code master specification; documentation-driven approach; optional REA; universal registry; GIS validation; Bronze/Silver/Gold lineage; phased implementation. |

