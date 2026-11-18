# CLAUDE.md

Governing spec: `docs/HPW_LIGHTWEIGHT_GIS_CLAUDE_CODE_MASTER.md` (the original is in `00_Reference_document/`).

## Commands
- Tests: `powershell -ExecutionPolicy Bypass -File scripts\test.ps1` (pytest + `node --check` on web/js)
- UI = `web/`: plain HTML/CSS/ES modules, no build. The user wants the HTML version only, so don't
  introduce a framework (React etc.), npm dependencies or a build step. MapLibre is stored in `web/vendor/`.
- Run: `powershell -ExecutionPolicy Bypass -File scripts\run.ps1` → http://127.0.0.1:8000 (or double-click `Start-Workbench.bat`)
- `.venv` is **x64 Python 3.12** (this machine is Windows-on-ARM; ARM Python lacks GDAL/pyarrow wheels).

## Rules that matter here
- Add a tool = one module in `backend/hpw_gis/gis_tools/` calling `register(ToolSpec(...))` + tests. Never per-layer code.
  Tools declare geometry families and `crs_requirement`; the UI form and compatibility come from that metadata.
- Pure geometry functions (no I/O) + a thin executor `(ctx, **params)` that uses `ctx.input_gdf` / `ctx.write_layer`.
  Raise `ToolError` for user-facing failures. Record counts in `ctx.counts`, deviations in `known_differences`.
- Sources are read-only. Outputs are always new Gold layers. Never guess a CRS; refuse distance work on
  geographic/unknown CRS.
- `_hpw_fid` is the internal stable feature id for selection; source fields are never renamed.
- Status values follow spec §1.3. Do not mark VALIDATED without a reference comparison in `docs/VALIDATION_REPORTS/`.
- Update `docs/ARCGIS_FEATURE_CATALOG.csv` and `docs/CHANGELOG.md` with each increment.
