# Layer Registry

**Date:** 2026-11-14 · Descriptors live in `config/layers.yaml` (spec §4.1); runtime metadata lives in the SQLite `layers` table.

> **No real HPW datasets have been provided yet.** Every layer below is a **synthetic QA fixture** (`backend/hpw_gis/fixtures.py`).
> The IDs and attributes are invented, and the coordinates are placed near downtown Houston only so the map lines up.
> No production schema details are claimed.

## Registered fixture layers

| layer_id | Geometry | CRS (verified) | Primary key | Relationships | Deliberate QA conditions (detected on import) |
|---|---|---|---|---|---|
| `manholes` | Point (18) | EPSG:2278, from GPKG | `UFID` (verified) | — | Natural key `MH_NUMBER`: 1 duplicate (`MH-021`) + 1 null → reported |
| `gravity_mains` | Line (16, 1 multipart) | EPSG:2278 | `UFID` | `US_MANHOLE`, `DS_MANHOLE` → `manholes.MH_NUMBER` (many_to_one) | Ambiguous target key (duplicate MH-021); orphan `MH-999`; directed cycle; disconnected pair; pipe digitized against flow; null `INSTALL_YR` |
| `sewer_basins` | Polygon (5) | EPSG:2278, from GeoParquet | `BASIN_ID` | — | Overlapping basins; polygon with a hole; multipart basin; invalid self-intersecting "bowtie" |
| `level_sensors` | Point (5), CSV lon/lat | EPSG:4326, **declared in descriptor** | `site_id` | `linked_mh_ufid` → `manholes.UFID` (valid) | `site_name` not unique; geographic CRS → distance tools gated until Project |
| `sso_events` | Point (6), zipped Shapefile | **UNKNOWN** (no `.prj`) | `EVENT_ID` | — | Not drawable and not usable by CRS-dependent tools until Define Projection |

## Onboarding rules (implemented)
1. Bronze: copy the original bytes and record their SHA-256. Silver: normalized GeoParquet with `_hpw_fid`.
2. CRS comes from the source. A descriptor CRS is applied **only** when the source has none. A mismatch between
   them is reported, and the source CRS is kept.
3. Primary key: use the declared PK if it is verified unique and non-null. Otherwise detect a unique hinted field
   (UFID, OBJECTID, ...), or fall back to the surrogate `_hpw_fid`. Every fallback is reported.
4. Relationships: validate field existence, target-key uniqueness and match coverage. They are recorded as
   `valid` or `warning`, and nothing is joined silently.
5. Profiling: geometry types, multipart, null/empty/invalid (with reasons), duplicate geometries/rows, field
   types, nulls and distinct counts, native and WGS84 extents.

## Adding a real HPW layer
Add a descriptor with `source.uri: ${DATA_ROOT}/...` and set the `HPW_DATA_ROOT` environment variable. Confirm
`geometry.crs` (leave it out if the file embeds a CRS), `identity.primary_key` and `relationships`, then restart.
Alternatively, upload the file through **Add data**. No code changes are needed. Keep production data out of the
repository; `workspaces/` and `data/` are git-ignored.

## City layer library (52 reference layers, on demand)
`scripts/import_city_layers.py` copies two collections from `D:\City_Project\Dashboard_requirement`:
* The 38 Houston map-library layers. Their EPSG:4326 display tiles are merged into `data/city_library/*.parquet`.
* The 14 flowmeter-25-basin GeoJSON layers, copied byte-for-byte into `data/flowmeter_25_basins/`.

The script also writes `config/city_layers.yaml`. In the app, **Add data › City layer library** registers a layer
when you ask for it. Layers are grouped as in the library and start hidden. Dense layers draw only from the library's
minimum zoom. `data/city_library/IMPORT_REPORT.json` lists counts, hashes and the epoch-ms columns that were
converted to datetimes. The library payloads are display copies in EPSG:4326, while the original GIS is EPSG:2278.
Use **Project** before distance work. The space-time dashboard does this automatically.

## Open questions for real data (to confirm with the data owner)
- The authoritative CRS of the HPW wastewater datasets: EPSG:2278 (NAD83 Texas South Central ftUS) or EPSG:6588
  (NAD83(2011))?
- Is `UFID` unique and non-null across gravity mains and manholes? Is `MH_NUMBER` unique?
- Do the `US_MANHOLE`/`DS_MANHOLE` attributes reflect verified flow direction?
