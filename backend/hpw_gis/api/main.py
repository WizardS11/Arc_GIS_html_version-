"""FastAPI application (spec §11). Binds to 127.0.0.1 by default; no telemetry, no cloud calls."""
from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import shapely
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from .. import gis_tools  # noqa: F401  (registers tools)
from ..config import Settings
from ..gis_tools.expressions import ExpressionError, evaluate
from ..gis_tools.selection import spatial_match
from ..jobs import SELECTION_TYPES, JobManager, SelectionStore
from ..registry.catalog import LibraryCatalog
from ..registry.layers import LayerError, LayerRegistry
from ..registry.tools import TOOLS, ToolValidationError, tool_with_compatibility, validate_params
from ..storage.io import EXPORT_FORMATS, FID, CsvOptions, FormatError, available_drivers, export_vector
from ..storage.metadata import MetadataStore


# ----------------------------------------------------------------------------- schemas
class SortSpec(BaseModel):
    field: str
    desc: bool = False


class TableQuery(BaseModel):
    offset: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=1000)
    sort: list[SortSpec] = []
    search: str | None = None
    where: str | None = None
    selected_only: bool = False
    fields: list[str] | None = None


class SelectionBody(BaseModel):
    fids: list[int]
    mode: Literal["new", "add", "remove", "subset", "switch", "clear"] = "new"


class GeometrySelectBody(BaseModel):
    geometry: dict  # GeoJSON geometry in EPSG:4326
    mode: Literal["new", "add", "remove", "subset", "switch", "clear"] = "new"
    relation: str = "intersect"


class ToolRunBody(BaseModel):
    tool_id: str
    params: dict[str, Any] = {}
    wait: bool = False


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    state: dict[str, Any]


def _clean_records(df: pd.DataFrame) -> list[dict]:
    out = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, float) and not math.isfinite(v):
                r[k] = None
            elif isinstance(v, (np.integer,)):
                r[k] = int(v)
            elif isinstance(v, (np.floating,)):
                r[k] = None if not math.isfinite(v) else float(v)
            elif isinstance(v, (pd.Timestamp,)):
                r[k] = v.isoformat()
    return out


def _json(data: Any, status: int = 200) -> Response:
    return Response(json.dumps(data, default=str, allow_nan=False), status_code=status, media_type="application/json")


# ----------------------------------------------------------------------------- app
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.workspace.mkdir(parents=True, exist_ok=True)
    store = MetadataStore(settings.db_path)
    registry = LayerRegistry(settings, store)
    selection = SelectionStore()
    jobs = JobManager(registry, store, selection, workers=settings.job_workers)
    for t in TOOLS.values():
        store.upsert_tool(t.id, t.name, t.category, t.version, t.reference_url, t.status)

    app = FastAPI(title="HPW Lightweight GIS Workbench", version=__version__)
    app.state.settings, app.state.registry, app.state.jobs, app.state.selection = settings, registry, jobs, selection
    app.state.bootstrap_report = bootstrap(settings, registry) if settings.bootstrap_layers else []
    library = LibraryCatalog(settings, registry)
    app.state.library = library

    @app.exception_handler(LayerError)
    async def _layer_err(_: Request, e: LayerError):
        return JSONResponse({"error": "layer_error", "detail": str(e)}, status_code=404 if "not registered" in str(e) else 409)

    @app.exception_handler(FormatError)
    async def _fmt_err(_: Request, e: FormatError):
        return JSONResponse({"error": "format_error", "detail": str(e)}, status_code=422)

    # ---------------------------------------------------------------- health
    @app.get("/api/health")
    def health():
        drivers = available_drivers()
        return {"status": "ok", "version": __version__, "workspace": str(settings.workspace),
                "layers": len(registry.list()), "tools": len(TOOLS),
                "gdal_drivers": {k: drivers.get(k) for k in ("GPKG", "GeoJSON", "ESRI Shapefile", "OpenFileGDB",
                                                             "FlatGeobuf", "CSV")},
                "bootstrap": app.state.bootstrap_report}

    # ---------------------------------------------------------------- layers
    @app.get("/api/layers")
    def list_layers():
        sel = selection.all()
        out = []
        for l in registry.list():
            l = dict(l)
            l.pop("profile")
            l["selected_count"] = len(sel.get(l["layer_id"], []))
            out.append(l)
        return _json(out)

    @app.get("/api/layers/{layer_id}/metadata")
    def layer_metadata(layer_id: str):
        return _json(registry.get(layer_id))

    @app.post("/api/layers/import")
    async def import_layer(file: UploadFile = File(...), label: str | None = Form(None),
                           layer_id: str | None = Form(None), crs: str | None = Form(None),
                           x_field: str | None = Form(None), y_field: str | None = Form(None),
                           wkt_field: str | None = Form(None), primary_key: str | None = Form(None)):
        name = Path(file.filename or "upload").name
        if not re.match(r"^[\w\-. ()]+$", name):
            raise HTTPException(422, "Unsafe file name")
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / name
            with open(dest, "wb") as f:
                shutil.copyfileobj(file.file, f)
            descriptor: dict[str, Any] = {}
            if crs:
                descriptor["geometry"] = {"crs": crs}
            if primary_key:
                descriptor["identity"] = {"primary_key": primary_key}
            csv = CsvOptions(x_field=x_field or None, y_field=y_field or None, wkt_field=wkt_field or None,
                             crs=crs or None)
            try:
                info = registry.import_source(dest, layer_id=layer_id or None, label=label or Path(name).stem,
                                              descriptor=descriptor, csv_options=csv)
            except (LayerError, FormatError) as e:
                raise HTTPException(422, str(e))
            except Exception as e:
                raise HTTPException(422, f"Could not read {name}: {type(e).__name__}: {e}")
        return _json(info)

    @app.get("/api/layers/{layer_id}/features")
    def features(layer_id: str, bbox: str | None = None, limit: int | None = None, where: str | None = None):
        info = registry.get(layer_id)
        if info["geometry_family"] == "Table":
            raise HTTPException(409, "Non-spatial table: no features to draw")
        g = registry.gdf_4326(layer_id)
        if where:
            try:
                mask, _ = evaluate(pd.DataFrame(g.drop(columns=[g.geometry.name])), where)
            except ExpressionError as e:
                raise HTTPException(422, f"Invalid filter expression: {e}")
            g = g[np.asarray(mask, dtype=bool)]
        limit = min(limit or settings.max_features_per_request, settings.max_features_per_request)
        if bbox:
            try:
                b = [float(v) for v in bbox.split(",")]
                assert len(b) == 4
            except Exception:
                raise HTTPException(422, "bbox must be minx,miny,maxx,maxy in EPSG:4326")
            idx = g.sindex.query(shapely.box(*b), predicate="intersects")
            g = g.iloc[np.sort(idx)]
        total = len(g)
        g = g.iloc[:limit]
        g = g[g.geometry.notna()]
        props = _clean_records(pd.DataFrame(g.drop(columns=[g.geometry.name])))
        geoms = shapely.to_geojson(g.geometry.values)
        feats = [{"type": "Feature", "id": p[FID], "properties": p, "geometry": json.loads(gj)}
                 for p, gj in zip(props, geoms)]
        return _json({"type": "FeatureCollection", "features": feats, "total_in_bbox": total,
                      "truncated": total > limit})

    @app.post("/api/layers/{layer_id}/table")
    def table(layer_id: str, q: TableQuery):
        info = registry.get(layer_id)
        g = registry.gdf(layer_id)
        df = pd.DataFrame(g.drop(columns=[g.geometry.name]))
        total = len(df)
        if q.selected_only:
            df = df[df[FID].isin(selection.get(layer_id))]
        if q.where:
            try:
                mask, _ = evaluate(df, q.where)
            except ExpressionError as e:
                raise HTTPException(422, f"Invalid filter expression: {e}")
            df = df[mask]
        if q.search:
            s = q.search.lower()
            m = np.zeros(len(df), dtype=bool)
            for c in df.columns:
                m |= df[c].astype(str).str.lower().str.contains(s, regex=False, na=False).to_numpy()
            df = df[m]
        if q.sort:
            for s_ in q.sort:
                if s_.field not in df.columns:
                    raise HTTPException(422, f"Unknown sort field {s_.field}")
            df = df.sort_values([s.field for s in q.sort], ascending=[not s.desc for s in q.sort],
                                na_position="last", kind="mergesort")
        filtered = len(df)
        page = df.iloc[q.offset:q.offset + q.limit]
        if q.fields:
            page = page[[FID] + [f for f in q.fields if f in page.columns and f != FID]]
        return _json({"layer_id": layer_id, "total": total, "filtered": filtered, "offset": q.offset,
                      "rows": _clean_records(page), "columns": [f for f in info["profile"]["fields"]],
                      "primary_key": info["primary_key"]})

    @app.get("/api/layers/{layer_id}/statistics/{field}")
    def field_stats(layer_id: str, field: str):
        g = registry.gdf(layer_id)
        if field not in g.columns or field == g.geometry.name:
            raise HTTPException(404, f"Field {field} not found")
        s = g[field]
        sel = selection.get(layer_id)
        if sel:
            s = s[g[FID].isin(sel)]
        out: dict[str, Any] = {"field": field, "count": int(s.notna().sum()), "nulls": int(s.isna().sum()),
                               "distinct": int(s.nunique(dropna=True)), "scope": "selected" if sel else "all"}
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and s.notna().any():
            v = s.dropna().astype(float)
            out.update({"sum": v.sum(), "mean": v.mean(), "median": v.median(), "min": v.min(), "max": v.max(),
                        "std": v.std(ddof=1) if len(v) > 1 else None})
        else:
            out["top_values"] = [{"value": k, "count": int(c)} for k, c in s.value_counts().head(10).items()]
        return _json(_clean_records(pd.DataFrame([out]))[0])

    @app.get("/api/layers/{layer_id}/export")
    def export(layer_id: str, format: str = "gpkg", selected_only: bool = False):
        info = registry.get(layer_id)
        g = registry.gdf(layer_id)
        if selected_only:
            sel = selection.get(layer_id)
            if not sel:
                raise HTTPException(409, "No features are selected")
            g = g[g[FID].isin(sel)]
        if format not in EXPORT_FORMATS:
            raise HTTPException(422, f"format must be one of {list(EXPORT_FORMATS)}")
        data, warnings = export_vector(g, format, layer_id + ("_selected" if selected_only else ""))
        fname = f"{layer_id}{'_selected' if selected_only else ''}{EXPORT_FORMATS[format]['ext']}"
        headers = {"Content-Disposition": f'attachment; filename="{fname}"',
                   "X-HPW-Warnings": json.dumps(warnings), "X-HPW-Feature-Count": str(len(g)),
                   "X-HPW-CRS": (info["crs"] or {}).get("srs") or "unknown",
                   "Access-Control-Expose-Headers": "X-HPW-Warnings, X-HPW-Feature-Count, X-HPW-CRS"}
        return Response(data, media_type=EXPORT_FORMATS[format]["media"], headers=headers)

    # ---------------------------------------------------------------- city layer library
    @app.get("/api/library")
    def library_list():
        return _json(library.list())

    @app.post("/api/library/{layer_id}/add")
    def library_add(layer_id: str):
        try:
            return _json(library.add(layer_id), status=202)
        except KeyError:
            raise HTTPException(404, f"{layer_id} is not in the city layer library")

    # ---------------------------------------------------------------- selection
    @app.get("/api/selection")
    def all_selection():
        return selection.all()

    @app.get("/api/selection/{layer_id}")
    def get_selection(layer_id: str):
        registry.get(layer_id)
        return {"layer_id": layer_id, "fids": sorted(selection.get(layer_id))}

    @app.put("/api/selection/{layer_id}")
    def put_selection(layer_id: str, body: SelectionBody):
        g = registry.gdf(layer_id)
        all_fids = set(int(x) for x in g[FID])
        bad = set(body.fids) - all_fids
        if bad:
            raise HTTPException(422, f"Unknown feature ids: {sorted(bad)[:10]}")
        res = selection.apply(layer_id, set(body.fids), body.mode, all_fids)
        return {"layer_id": layer_id, "fids": sorted(res)}

    @app.post("/api/selection/{layer_id}/by-geometry")
    def select_by_geometry(layer_id: str, body: GeometrySelectBody):
        import geopandas as gpd
        g = registry.gdf_4326(layer_id)
        try:
            geom = shapely.from_geojson(json.dumps(body.geometry))
        except Exception:
            raise HTTPException(422, "Invalid GeoJSON geometry")
        sel_gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
        mask = spatial_match(g, sel_gdf, body.relation, None)
        all_fids = set(int(x) for x in g[FID])
        res = selection.apply(layer_id, set(int(x) for x in g.loc[mask, FID]), body.mode, all_fids)
        return {"layer_id": layer_id, "fids": sorted(res)}

    @app.get("/api/selection/{layer_id}/extent")
    def selection_extent(layer_id: str):
        g = registry.gdf_4326(layer_id)
        sel = selection.get(layer_id)
        if not sel:
            raise HTTPException(409, "No selection")
        b = g[g[FID].isin(sel)].total_bounds
        return {"bbox": [float(v) for v in b]}

    # ---------------------------------------------------------------- tools
    @app.get("/api/tools")
    def tools():
        layers = registry.list()
        return _json([tool_with_compatibility(t, layers) for t in TOOLS.values()])

    @app.get("/api/tools/{tool_id}")
    def tool(tool_id: str):
        if tool_id not in TOOLS:
            raise HTTPException(404, f"Unknown tool {tool_id}")
        return _json(tool_with_compatibility(TOOLS[tool_id], registry.list()))

    @app.post("/api/tool-runs")
    def run_tool(body: ToolRunBody):
        spec = TOOLS.get(body.tool_id)
        if not spec:
            raise HTTPException(404, f"Unknown tool {body.tool_id}")
        try:
            params = validate_params(spec, body.params, registry.get)
        except ToolValidationError as e:
            return _json({"error": "validation_error", "detail": e.errors}, status=422)
        job = jobs.run_sync(spec, params) if body.wait else jobs.submit(spec, params)
        return _json(job.public(), status=200 if body.wait else 202)

    @app.get("/api/tool-runs")
    def runs(limit: int = 100):
        return _json(store.runs(limit))

    @app.get("/api/tool-runs/{run_id}")
    def get_run(run_id: str):
        r = jobs.get(run_id)
        if not r:
            raise HTTPException(404, "Unknown run")
        return _json(r)

    @app.post("/api/tool-runs/{run_id}/cancel")
    def cancel_run(run_id: str):
        j = jobs.cancel(run_id)
        if not j:
            raise HTTPException(404, "Unknown or finished run")
        return _json(j.public())

    @app.get("/api/tool-runs/{run_id}/result")
    def run_result(run_id: str):
        p = settings.tier_dir("gold") / run_id / "manifest.json"
        if not re.match(r"^[0-9a-f]{32}$", run_id) or not p.exists():
            raise HTTPException(404, "No manifest for this run")
        return FileResponse(p, media_type="application/json", filename=f"manifest_{run_id}.json")

    # ---------------------------------------------------------------- projects
    @app.get("/api/projects")
    def projects():
        return store.projects()

    @app.post("/api/projects")
    def save_project(body: ProjectBody):
        state = dict(body.state)
        state["selection"] = selection.all()
        store.save_project(body.name, state)
        return {"name": body.name, "saved": True}

    @app.get("/api/projects/{name}")
    def open_project(name: str):
        p = store.project(name)
        if not p:
            raise HTTPException(404, "Unknown project")
        for lid, fids in (p["state"].get("selection") or {}).items():
            if registry.exists(lid):
                selection.set(lid, fids)
        return _json(p)

    @app.get("/api/catalog/selection-types")
    def selection_types():
        return SELECTION_TYPES

    # ---------------------------------------------------------------- static UI
    if settings.ui_dir.exists():
        app.mount("/", StaticFiles(directory=settings.ui_dir, html=True), name="ui")
    else:
        @app.get("/")
        def no_ui():
            return {"message": "API running, but the UI folder (web/) was not found. "
                               "Restore web/ or set HPW_UI_DIR.", "docs": "/docs"}

    return app


def bootstrap(settings: Settings, registry: LayerRegistry) -> list[dict]:
    """Register descriptor-configured layers that are not yet in the registry. Never overwrites."""
    report: list[dict] = []
    cfg = settings.config_dir / "layers.yaml"
    if not cfg.exists():
        return report
    descriptors = (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("layers") or []
    if any("${FIXTURES}" in (d.get("source") or {}).get("uri", "") for d in descriptors) and \
            not (settings.fixtures_dir / "manholes.gpkg").exists():
        from ..fixtures import build
        build(settings.fixtures_dir)
        report.append({"layer_id": "*", "status": "fixtures_generated"})
    new_ids = []
    for d in descriptors:
        lid = d["layer_id"]
        if registry.exists(lid):
            report.append({"layer_id": lid, "status": "already_registered"})
            continue
        path = settings.expand(d["source"]["uri"])
        if not path.exists():
            report.append({"layer_id": lid, "status": "missing_source", "path": str(path)})
            continue
        csv = d.get("csv") or {}
        try:
            registry.import_source(path, layer_id=lid, label=d.get("label"), descriptor=d,
                                   csv_options=CsvOptions(crs=(d.get("geometry") or {}).get("crs"), **csv))
            new_ids.append(lid)
            report.append({"layer_id": lid, "status": "registered"})
        except Exception as e:  # keep going; report the failure
            report.append({"layer_id": lid, "status": "error", "detail": f"{type(e).__name__}: {e}"})
    for d in descriptors:
        if d["layer_id"] in new_ids and d.get("relationships"):
            registry.validate_relationships(d["layer_id"])
    return report


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
