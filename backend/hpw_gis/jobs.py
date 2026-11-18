"""Job manager + run context: every tool executes as a tracked, cancellable job with provenance (spec §5.2)."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd

from . import __version__
from .registry.layers import LayerRegistry
from .registry.tools import ToolSpec
from .storage.io import FID
from .storage.metadata import MetadataStore, now_iso


class ToolError(RuntimeError):
    """Raised by tools for an actionable, user-facing failure. Source data is never modified."""


class Cancelled(RuntimeError):
    pass


class SelectionStore:
    """Current selection per layer (set of _hpw_fid), shared by map, table and tools."""

    def __init__(self) -> None:
        self._sel: dict[str, set[int]] = {}
        self._lock = threading.Lock()

    def get(self, layer_id: str) -> set[int]:
        with self._lock:
            return set(self._sel.get(layer_id, set()))

    def set(self, layer_id: str, fids: set[int] | list[int]) -> set[int]:
        with self._lock:
            self._sel[layer_id] = {int(f) for f in fids}
            return set(self._sel[layer_id])

    def all(self) -> dict[str, list[int]]:
        with self._lock:
            return {k: sorted(v) for k, v in self._sel.items() if v}

    def apply(self, layer_id: str, new: set[int], mode: str, all_fids: set[int]) -> set[int]:
        cur = self.get(layer_id)
        if mode == "new":
            res = new
        elif mode == "add":
            res = cur | new
        elif mode == "remove":
            res = cur - new
        elif mode == "subset":
            res = cur & new
        elif mode == "switch":
            res = all_fids - cur
        elif mode == "clear":
            res = set()
        else:
            raise ToolError(f"Unknown selection type '{mode}'")
        return self.set(layer_id, res)


SELECTION_TYPES = ["new", "add", "remove", "subset", "switch", "clear"]
SELECTION_TYPE_LABELS = {
    "new": "New selection", "add": "Add to current selection", "remove": "Remove from current selection",
    "subset": "Select subset from current selection", "switch": "Switch current selection",
    "clear": "Clear selection",
}


@dataclass
class Job:
    run_id: str
    tool_id: str
    params: dict
    status: str = "queued"
    messages: list[dict] = field(default_factory=list)
    progress: float = 0.0
    result: dict | None = None
    error: str | None = None
    submitted_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("run_id", "tool_id", "params", "status", "messages", "progress",
                                               "result", "error", "submitted_at", "started_at", "finished_at",
                                               "duration_s")}


class RunContext:
    def __init__(self, job: Job, spec: ToolSpec, registry: LayerRegistry, store: MetadataStore,
                 selection: SelectionStore):
        self.job = job
        self.spec = spec
        self.registry = registry
        self.store = store
        self.selection = selection
        self.run_id = job.run_id
        self.inputs: list[dict] = []
        self.outputs: list[dict] = []
        self.counts: dict[str, Any] = {}
        self.transformations: list[str] = []

    # messages ----------------------------------------------------------
    def message(self, text: str, level: str = "info") -> None:
        self.job.messages.append({"t": now_iso(), "level": level, "text": text})

    def warn(self, text: str) -> None:
        self.message(text, "warning")

    def progress(self, frac: float) -> None:
        self.job.progress = max(0.0, min(1.0, frac))
        self.check_cancel()

    def check_cancel(self) -> None:
        if self.job.cancel_event.is_set():
            raise Cancelled("Cancelled by user")

    # inputs -----------------------------------------------------------
    def input_gdf(self, layer_id: str, role: str, use_selection: bool = True) -> gpd.GeoDataFrame:
        info = self.registry.get(layer_id)
        gdf = self.registry.gdf(layer_id)
        sel = self.selection.get(layer_id) if use_selection else set()
        if sel:
            gdf = gdf[gdf[FID].isin(sel)]
            self.message(f"{info['label']}: using {len(gdf)} selected of {info['feature_count']} features.")
        self.inputs.append({
            "role": role, "layer_id": layer_id, "label": info["label"], "version_id": info["version_id"],
            "sha256": info["sha256"], "primary_key": info["primary_key"], "crs": (info["crs"] or {}).get("srs"),
            "source_feature_count": info["feature_count"], "used_feature_count": int(len(gdf)),
            "selection_applied": bool(sel),
        })
        self.store.add_run_io("run_inputs", self.run_id, info["version_id"], role)
        return gdf.copy()

    # outputs ----------------------------------------------------------
    def write_layer(self, gdf: gpd.GeoDataFrame, label: str, role: str = "output") -> dict:
        self.check_cancel()
        lineage = {"run_id": self.run_id, "tool_id": self.spec.id, "inputs": self.inputs,
                   "params": self.job.params}
        info = self.registry.register_derived(gdf, label=label, run_id=self.run_id, tool_id=self.spec.id,
                                              lineage=lineage)
        self.store.add_run_io("run_outputs", self.run_id, info["version_id"], role)
        self.outputs.append({"role": role, "layer_id": info["layer_id"], "label": info["label"],
                             "version_id": info["version_id"], "feature_count": info["feature_count"],
                             "crs": (info["crs"] or {}).get("srs"), "path": info["path"],
                             "geometry_family": info["geometry_family"],
                             "fields": [f["name"] for f in info["profile"]["fields"]]})
        self.message(f"Created layer '{info['label']}' ({info['feature_count']} features).")
        for w in info["warnings"]:
            self.warn(f"Output QA: {w}")
        return info


class JobManager:
    def __init__(self, registry: LayerRegistry, store: MetadataStore, selection: SelectionStore, workers: int = 2):
        self.registry = registry
        self.store = store
        self.selection = selection
        self.jobs: dict[str, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hpw-job")

    def submit(self, spec: ToolSpec, params: dict) -> Job:
        run_id = uuid.uuid4().hex
        job = Job(run_id=run_id, tool_id=spec.id, params=params)
        self.jobs[run_id] = job
        self.store.insert_run(run_id, spec.id, spec.version, params)
        self.pool.submit(self._run, job, spec)
        return job

    def run_sync(self, spec: ToolSpec, params: dict) -> Job:
        run_id = uuid.uuid4().hex
        job = Job(run_id=run_id, tool_id=spec.id, params=params)
        self.jobs[run_id] = job
        self.store.insert_run(run_id, spec.id, spec.version, params)
        self._run(job, spec)
        return job

    def cancel(self, run_id: str) -> Job | None:
        job = self.jobs.get(run_id)
        if job and job.status in ("queued", "running"):
            job.cancel_event.set()
            if job.status == "queued":
                job.status = "cancelled"
        return job

    def get(self, run_id: str) -> dict | None:
        if run_id in self.jobs:
            return self.jobs[run_id].public()
        return self.store.run(run_id)

    def _run(self, job: Job, spec: ToolSpec) -> None:
        if job.cancel_event.is_set():
            job.status = "cancelled"
            self.store.update_run(job.run_id, status="cancelled", finished_at=now_iso())
            return
        ctx = RunContext(job, spec, self.registry, self.store, self.selection)
        job.status = "running"
        job.started_at = now_iso()
        t0 = time.perf_counter()
        self.store.update_run(job.run_id, status="running", started_at=job.started_at)
        ctx.message(f"Start: {spec.name} ({spec.id} v{spec.version})")
        try:
            result = spec.executor(ctx, **job.params) or {}
            job.status = "succeeded"
            job.progress = 1.0
        except Cancelled as e:
            job.status = "cancelled"
            job.error = str(e)
            ctx.warn("Run cancelled; no outputs were registered after cancellation and sources are unchanged.")
            result = {}
        except ToolError as e:
            job.status = "failed"
            job.error = str(e)
            ctx.message(str(e), "error")
            result = {}
        except Exception as e:  # unexpected - keep the traceback in the run record
            job.status = "failed"
            job.error = f"{type(e).__name__}: {e}"
            ctx.message(job.error, "error")
            ctx.message(traceback.format_exc(limit=6), "debug")
            result = {}
        job.duration_s = round(time.perf_counter() - t0, 4)
        job.finished_at = now_iso()
        ctx.message(f"{job.status.capitalize()} in {job.duration_s:.3f} s")
        manifest = {
            "run_id": job.run_id, "tool_id": spec.id, "tool_name": spec.name, "implementation_version": spec.version,
            "engine_version": __version__, "status": job.status, "submitted_at": job.submitted_at,
            "started_at": job.started_at, "finished_at": job.finished_at, "duration_s": job.duration_s,
            "parameters": job.params, "inputs": ctx.inputs, "outputs": ctx.outputs, "counts": ctx.counts,
            "transformations": ctx.transformations, "result": result, "messages": job.messages,
            "reference_documentation_url": spec.reference_url, "reference_retrieved": spec.reference_retrieved,
            "known_differences": spec.known_differences, "validation_status": spec.status,
        }
        job.result = manifest
        if ctx.outputs or job.status == "succeeded":
            mdir = self.registry.settings.tier_dir("gold") / job.run_id
            mdir.mkdir(parents=True, exist_ok=True)
            (mdir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        self.store.update_run(job.run_id, status=job.status, finished_at=job.finished_at, duration_s=job.duration_s,
                              messages_json=job.messages, result_json=manifest, error=job.error)
