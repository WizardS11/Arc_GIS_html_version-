"""City layer library: catalog of copied reference layers (config/city_layers.yaml), registered on demand.

The catalog is produced by scripts/import_city_layers.py. Adding a layer runs the normal onboarding
(Bronze copy -> profile -> Silver GeoParquet) in a background thread, because the largest layers
(parcels, finished floor elevations) take minutes.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

from ..config import Settings
from .layers import LayerRegistry

CATALOG_FILE = "city_layers.yaml"


class LibraryCatalog:
    def __init__(self, settings: Settings, registry: LayerRegistry):
        self.settings = settings
        self.registry = registry
        self._status: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hpw-library")
        self._entries: list[dict] | None = None
        self._mtime = None

    def _load(self) -> list[dict]:
        p = self.settings.config_dir / CATALOG_FILE
        if not p.exists():
            return []
        m = p.stat().st_mtime
        if self._entries is None or m != self._mtime:
            self._entries = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("layers") or []
            self._mtime = m
        return self._entries

    def entry(self, layer_id: str) -> dict | None:
        return next((e for e in self._load() if e["layer_id"] == layer_id), None)

    def list(self) -> list[dict]:
        out = []
        registered = {r["layer_id"] for r in self.registry.store.query("SELECT layer_id FROM layers")}
        for e in self._load():
            path = self.settings.expand(e["source"]["uri"])
            st = dict(self._status.get(e["layer_id"]) or {})
            if e["layer_id"] in registered:
                st = {"status": "registered"}
            elif not st:
                st = {"status": "available" if path.exists() else "missing"}
            size = path.stat().st_size if path.exists() else None
            out.append({
                "layer_id": e["layer_id"], "label": e["label"], "group": e.get("group"),
                "geometry": (e.get("geometry") or {}).get("type"), "display": e.get("display") or {},
                "metadata": e.get("metadata") or {}, "bytes": size, **st,
            })
        return out

    def add(self, layer_id: str) -> dict:
        e = self.entry(layer_id)
        if e is None:
            raise KeyError(layer_id)
        if self.registry.exists(layer_id):
            return {"layer_id": layer_id, "status": "registered"}
        path = self.settings.expand(e["source"]["uri"])
        if not path.exists():
            return {"layer_id": layer_id, "status": "missing",
                    "detail": f"{path} not found - run scripts/import_city_layers.py"}
        with self._lock:
            cur = self._status.get(layer_id, {}).get("status")
            if cur in ("queued", "importing"):
                return {"layer_id": layer_id, "status": cur}
            self._status[layer_id] = {"status": "queued"}
        self._pool.submit(self._import, e, path)
        return {"layer_id": layer_id, "status": "queued"}

    def _import(self, e: dict, path) -> None:
        lid = e["layer_id"]
        self._status[lid] = {"status": "importing", "started": time.time()}
        try:
            self.registry.import_source(path, layer_id=lid, label=e["label"], descriptor=dict(e))
            self._status[lid] = {"status": "registered"}
        except Exception as ex:  # reported in the catalog
            self._status[lid] = {"status": "error", "detail": f"{type(ex).__name__}: {ex}"}
