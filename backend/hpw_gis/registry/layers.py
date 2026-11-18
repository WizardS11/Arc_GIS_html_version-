"""Layer registry: onboarding, profiling, versioning, Bronze/Silver/Gold lineage (spec §4, §9)."""
from __future__ import annotations

import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import CRS

from ..config import Settings
from ..storage.io import FID, CsvOptions, read_vector, sha256_path, write_parquet
from ..storage.metadata import MetadataStore, now_iso

PK_NAME_HINTS = ["UFID", "OBJECTID", "GLOBALID", "FID", "ID", "MH_NUMBER", "SITE_ID", "BASIN_ID", "EVENT_ID"]
LAYER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class LayerError(ValueError):
    pass


def geometry_family(types: set[str]) -> str:
    fams = set()
    for t in types:
        if t in ("Point", "MultiPoint"):
            fams.add("Point")
        elif t in ("LineString", "MultiLineString", "LinearRing"):
            fams.add("Line")
        elif t in ("Polygon", "MultiPolygon"):
            fams.add("Polygon")
        else:
            fams.add("Other")
    if not fams:
        return "Table"
    return fams.pop() if len(fams) == 1 else "Mixed"


def field_type(dtype: Any) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "double"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "date"
    if pd.api.types.is_string_dtype(dtype) or dtype == object:
        return "string"
    return "other"


def crs_info(crs: CRS | None) -> dict:
    if crs is None:
        return {"status": "unknown", "srs": None, "name": None, "is_geographic": None, "is_projected": None,
                "linear_unit": None, "unit_to_meters": None}
    auth = crs.to_authority()
    unit_name, factor = None, None
    if crs.is_projected and crs.axis_info:
        unit_name = crs.axis_info[0].unit_name
        factor = crs.axis_info[0].unit_conversion_factor
    return {
        "status": "known",
        "srs": f"{auth[0]}:{auth[1]}" if auth else crs.to_wkt(),
        "name": crs.name,
        "is_geographic": bool(crs.is_geographic),
        "is_projected": bool(crs.is_projected),
        "linear_unit": unit_name,
        "unit_to_meters": factor,
    }


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "layer"
    if not s[0].isalpha():
        s = "l_" + s
    return s[:50]


@dataclass
class LayerHandle:
    info: dict
    gdf: gpd.GeoDataFrame


class LayerRegistry:
    def __init__(self, settings: Settings, store: MetadataStore):
        self.settings = settings
        self.store = store
        self._cache: dict[str, gpd.GeoDataFrame] = {}
        self._cache_4326: dict[str, gpd.GeoDataFrame] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ queries
    def list(self) -> list[dict]:
        return [self._public(r) for r in self.store.layers()]

    def get(self, layer_id: str) -> dict:
        for r in self.store.layers():
            if r["layer_id"] == layer_id:
                return self._public(r)
        raise LayerError(f"Layer '{layer_id}' is not registered")

    def exists(self, layer_id: str) -> bool:
        return any(r["layer_id"] == layer_id for r in self.store.layers())

    def _public(self, r: dict) -> dict:
        prof = r.get("profile") or {}
        desc = r.get("descriptor") or {}
        return {
            "group": desc.get("group"),
            "display": desc.get("display") or {},
            "collection": (desc.get("metadata") or {}).get("collection"),
            "layer_id": r["layer_id"],
            "label": r["label"],
            "tier": r["tier"],
            "geometry_family": r["geometry_family"],
            "crs": prof.get("crs"),
            "primary_key": r["primary_key"],
            "feature_count": r.get("feature_count"),
            "version_id": r["current_version_id"],
            "sha256": r.get("sha256"),
            "path": r.get("path"),
            "bronze_path": r.get("bronze_path"),
            "source_uri": r["source_uri"],
            "source_format": (r.get("descriptor") or {}).get("source", {}).get("format"),
            "parent_run_id": r["parent_run_id"],
            "permissions": r["permissions"],
            "profile": prof,
            "warnings": prof.get("warnings", []),
            "created_at": r["created_at"],
            "relationships": self.store.relationships(r["layer_id"]),
        }

    def gdf(self, layer_id: str) -> gpd.GeoDataFrame:
        info = self.get(layer_id)
        key = info["version_id"]
        with self._lock:
            if key not in self._cache:
                self._cache[key] = gpd.read_parquet(info["path"])
            return self._cache[key]

    def gdf_4326(self, layer_id: str) -> gpd.GeoDataFrame:
        info = self.get(layer_id)
        key = info["version_id"]
        with self._lock:
            if key not in self._cache_4326:
                g = self.gdf(layer_id)
                if g.crs is None:
                    raise LayerError(f"Layer '{info['label']}' has an UNKNOWN coordinate system and cannot be drawn "
                                     "on the map. Run 'Define Projection' with the confirmed CRS.")
                out = g if g.crs.equals("EPSG:4326") else g.to_crs("EPSG:4326")
                out.sindex  # build spatial index
                self._cache_4326[key] = out
            return self._cache_4326[key]

    # --------------------------------------------------------------- onboarding
    def _new_layer_id(self, wanted: str) -> str:
        base = slugify(wanted)
        lid, n = base, 2
        while self.exists(lid):
            lid, n = f"{base}_{n}", n + 1
        return lid

    def import_source(self, path: Path, *, layer_id: str | None = None, label: str | None = None,
                      descriptor: dict | None = None, csv_options: CsvOptions | None = None,
                      source_layer: str | None = None) -> dict:
        """Onboard a source dataset: Bronze copy -> profile -> Silver GeoParquet -> register."""
        descriptor = dict(descriptor or {})
        path = Path(path)
        if not path.exists():
            raise LayerError(f"Source not found: {path}")
        if layer_id and not LAYER_ID_RE.match(layer_id):
            raise LayerError("layer_id must be lowercase letters, digits and underscores, starting with a letter")
        if layer_id and self.exists(layer_id):
            raise LayerError(f"Layer '{layer_id}' already exists")
        label = label or descriptor.get("label") or path.stem
        layer_id = layer_id or self._new_layer_id(label)
        version_id = f"{layer_id}@{uuid.uuid4().hex[:8]}"

        rr = read_vector(path, csv_options=csv_options, layer=source_layer)
        gdf = rr.gdf
        warnings = list(rr.warnings)

        declared_crs = (descriptor.get("geometry") or {}).get("crs")
        if declared_crs and "XXXX" not in str(declared_crs):
            dcrs = CRS.from_user_input(declared_crs)
            if gdf.crs is None:
                gdf = gdf.set_crs(dcrs)
                warnings.append(f"CRS assigned from layer descriptor: {declared_crs}.")
            elif not gdf.crs.equals(dcrs):
                warnings.append(f"Descriptor declares {declared_crs} but source reports {gdf.crs.to_string()}; "
                                "the SOURCE CRS is kept. Resolve this discrepancy before analysis.")

        # Bronze: immutable copy of the original bytes.
        bronze_dir = self.settings.tier_dir("bronze") / version_id.replace("@", "_")
        bronze_dir.mkdir(parents=True, exist_ok=True)
        bronze_path = bronze_dir / path.name
        if path.is_dir():
            shutil.copytree(path, bronze_path)
        else:
            shutil.copy2(path, bronze_path)
        source_sha = sha256_path(path)

        gdf, profile = self.profile(gdf, primary_key=(descriptor.get("identity") or {}).get("primary_key"))
        for nk in (descriptor.get("identity") or {}).get("natural_keys") or []:
            if nk not in gdf.columns:
                warnings.append(f"Declared natural key '{nk}' does not exist.")
                continue
            s = gdf[nk]
            dups = sorted(map(str, s[s.duplicated(keep=False) & s.notna()].unique()))
            if dups or s.isna().any():
                warnings.append(f"Natural key '{nk}' is not unique: {len(dups)} duplicated value(s) "
                                f"{dups[:5]}, {int(s.isna().sum())} null. Joins on it are ambiguous.")
        profile["warnings"] = warnings + profile["warnings"]
        profile["source_sha256"] = source_sha
        profile["source_format"] = rr.format
        profile["encoding"] = rr.encoding

        silver_path = self.settings.tier_dir("silver") / f"{version_id.replace('@', '_')}.parquet"
        write_parquet(gdf, silver_path)

        perms = {"source_read_only": True, "allow_derived_outputs": True, "allow_source_edits": False}
        perms.update(descriptor.get("permissions") or {})
        perms["source_read_only"] = True  # Phase 1: sources are never mutated
        descriptor.setdefault("source", {})
        descriptor["source"].setdefault("uri", str(path))
        descriptor["source"]["format"] = rr.format
        self.store.upsert_layer({
            "layer_id": layer_id, "label": label, "tier": "silver",
            "geometry_family": profile["geometry_family"], "crs": profile["crs"]["srs"],
            "primary_key": profile["primary_key"]["field"], "source_uri": str(path),
            "current_version_id": version_id, "parent_run_id": None, "descriptor_json": descriptor,
            "permissions_json": perms, "profile_json": profile, "created_at": now_iso(),
        })
        self.store.add_version({
            "version_id": version_id, "layer_id": layer_id, "path": str(silver_path), "format": "geoparquet",
            "sha256": sha256_path(silver_path), "feature_count": len(gdf), "bronze_path": str(bronze_path),
            "created_at": now_iso(),
        })
        return self.get(layer_id)

    def register_derived(self, gdf: gpd.GeoDataFrame, *, label: str, run_id: str, tool_id: str,
                         lineage: dict) -> dict:
        existing = {r["label"] for r in self.store.layers()}
        base, n = label, 2
        while label in existing:  # keep labels distinguishable in Contents (e.g. "... Buffer (2)")
            label, n = f"{base} ({n})", n + 1
        layer_id = self._new_layer_id(label)
        version_id = f"{layer_id}@{run_id[:8]}"
        gdf = gdf.reset_index(drop=True)
        if FID in gdf.columns:
            gdf = gdf.drop(columns=[FID])
        gdf.insert(0, FID, np.arange(len(gdf), dtype="int64"))
        gdf, profile = self.profile(gdf, primary_key=FID)
        profile["lineage"] = lineage
        gold_path = self.settings.tier_dir("gold") / run_id / f"{layer_id}.parquet"
        write_parquet(gdf, gold_path)
        self.store.upsert_layer({
            "layer_id": layer_id, "label": label, "tier": "gold",
            "geometry_family": profile["geometry_family"], "crs": profile["crs"]["srs"],
            "primary_key": FID, "source_uri": f"run:{run_id}", "current_version_id": version_id,
            "parent_run_id": run_id, "descriptor_json": {"source": {"format": "geoparquet", "tool_id": tool_id}},
            "permissions_json": {"source_read_only": True, "allow_derived_outputs": True, "allow_source_edits": False},
            "profile_json": profile, "created_at": now_iso(),
        })
        self.store.add_version({
            "version_id": version_id, "layer_id": layer_id, "path": str(gold_path), "format": "geoparquet",
            "sha256": sha256_path(gold_path), "feature_count": len(gdf), "bronze_path": None, "created_at": now_iso(),
        })
        return self.get(layer_id)

    # ----------------------------------------------------------------- profile
    def profile(self, gdf: gpd.GeoDataFrame, primary_key: str | None = None) -> tuple[gpd.GeoDataFrame, dict]:
        warnings: list[str] = []
        gdf = gdf.reset_index(drop=True)
        if FID not in gdf.columns:
            gdf.insert(0, FID, np.arange(len(gdf), dtype="int64"))
        geom = gdf.geometry
        gname = geom.name
        null_geom = int(geom.isna().sum())
        nonnull = geom[geom.notna()]
        empty = int(nonnull.is_empty.sum())
        valid_mask = shapely.is_valid(nonnull.values)
        invalid_idx = np.where(~valid_mask)[0]
        invalid_examples = [
            {"fid": int(gdf.loc[nonnull.index[i], FID]), "reason": shapely.is_valid_reason(nonnull.values[i])}
            for i in invalid_idx[:10]
        ]
        types = nonnull[~nonnull.is_empty].geom_type.value_counts().to_dict()
        family = geometry_family(set(types))
        if family == "Mixed":
            warnings.append(f"Mixed geometry types {sorted(types)}: some tools will refuse this layer.")
        multipart = int(sum(v for k, v in types.items() if k.startswith("Multi")))
        dup_geom = 0
        if len(nonnull):
            wkb = pd.Series(shapely.to_wkb(nonnull.values, hex=True))
            dup_geom = int(wkb.duplicated(keep=False).sum())
        if null_geom and family != "Table":
            warnings.append(f"{null_geom} features have null geometry.")
        if empty:
            warnings.append(f"{empty} features have empty geometry.")
        if len(invalid_idx):
            warnings.append(f"{len(invalid_idx)} features have invalid geometry (e.g. {invalid_examples[0]['reason']}).")
        if dup_geom:
            warnings.append(f"{dup_geom} features share an identical geometry with another feature.")

        ci = crs_info(gdf.crs)
        if ci["status"] == "unknown" and family != "Table":
            warnings.append("Coordinate reference system is UNKNOWN: distance/area tools and map display are disabled "
                            "until 'Define Projection' is run with the confirmed CRS.")
        elif ci["is_geographic"]:
            warnings.append("Geographic CRS (degrees): distance and area tools require projecting to a "
                            "projected CRS first.")

        extent = extent_4326 = None
        if len(nonnull) and not nonnull.is_empty.all():
            b = [float(v) for v in nonnull.total_bounds]
            extent = b
            if gdf.crs is not None:
                b4 = gpd.GeoSeries(nonnull.values, crs=gdf.crs).to_crs("EPSG:4326").total_bounds
                extent_4326 = [float(v) for v in b4]
                if ci["is_geographic"] and (abs(b[0]) > 180 or abs(b[2]) > 180 or abs(b[1]) > 90 or abs(b[3]) > 90):
                    warnings.append("Coordinates fall outside valid longitude/latitude ranges for the declared "
                                    "geographic CRS - the CRS is probably wrong.")

        fields = []
        for c in gdf.columns:
            if c == gname:
                continue
            s = gdf[c]
            nulls = int(s.isna().sum())
            try:
                distinct = int(s.nunique(dropna=True))
            except TypeError:
                distinct = None
            fields.append({
                "name": str(c), "type": field_type(s.dtype), "dtype": str(s.dtype), "null_count": nulls,
                "distinct_count": distinct, "unique": bool(distinct == len(s) and nulls == 0) if distinct is not None else False,
                "internal": c == FID,
            })

        pk = self._choose_pk(gdf, fields, primary_key, warnings)
        dup_rows = int(pd.DataFrame(gdf.drop(columns=[FID, gname])).astype(str).duplicated().sum()) if len(gdf.columns) > 2 else 0
        if dup_rows:
            warnings.append(f"{dup_rows} rows duplicate another row's attributes exactly.")

        profile = {
            "feature_count": int(len(gdf)),
            "geometry_column": gname,
            "geometry_family": family,
            "geometry_types": {k: int(v) for k, v in types.items()},
            "multipart_count": multipart,
            "null_geometry_count": null_geom,
            "empty_geometry_count": empty,
            "invalid_geometry_count": int(len(invalid_idx)),
            "invalid_examples": invalid_examples,
            "duplicate_geometry_count": dup_geom,
            "duplicate_attribute_rows": dup_rows,
            "crs": ci,
            "extent": extent,
            "extent_4326": extent_4326,
            "fields": fields,
            "primary_key": pk,
            "warnings": warnings,
            "profiled_at": now_iso(),
        }
        return gdf, profile

    @staticmethod
    def _choose_pk(gdf: gpd.GeoDataFrame, fields: list[dict], requested: str | None, warnings: list[str]) -> dict:
        by_name = {f["name"]: f for f in fields}
        candidates = [f["name"] for f in fields if f["unique"] and not f["internal"]]
        if requested and requested != FID:
            f = by_name.get(requested)
            if f is None:
                warnings.append(f"Declared primary key '{requested}' does not exist; using surrogate {FID}.")
            elif not f["unique"]:
                dups = int(gdf[requested].duplicated(keep=False).sum())
                warnings.append(f"Declared primary key '{requested}' is NOT unique/non-null ({dups} duplicated, "
                                f"{f['null_count']} null); using surrogate {FID}. Source key retained as an attribute.")
            else:
                return {"field": requested, "source": "declared", "verified": True, "candidates": candidates}
        elif requested == FID:
            return {"field": FID, "source": "surrogate", "verified": True, "candidates": candidates}
        else:
            upper = {c.upper(): c for c in candidates}
            for hint in PK_NAME_HINTS:
                if hint in upper:
                    return {"field": upper[hint], "source": "detected", "verified": True, "candidates": candidates}
            for hint in PK_NAME_HINTS:
                f = next((x for x in fields if x["name"].upper() == hint), None)
                if f and not f["unique"]:
                    warnings.append(f"Field '{f['name']}' looks like a key but is not unique/non-null; not used as PK.")
        return {"field": FID, "source": "surrogate", "verified": True, "candidates": candidates}

    # ------------------------------------------------------------ relationships
    def validate_relationships(self, layer_id: str) -> list[dict]:
        info = self.get(layer_id)
        rels = (self.store.query("SELECT descriptor_json FROM layers WHERE layer_id=?", (layer_id,)))
        import json
        descriptor = json.loads(rels[0]["descriptor_json"] or "{}") if rels else {}
        out = []
        for i, r in enumerate(descriptor.get("relationships") or []):
            v: dict[str, Any] = {"status": "invalid", "messages": []}
            local = self.gdf(layer_id)
            if r["local_field"] not in local.columns:
                v["messages"].append(f"Local field '{r['local_field']}' missing.")
            elif not self.exists(r["target_layer"]):
                v["messages"].append(f"Target layer '{r['target_layer']}' not registered.")
            else:
                tgt = self.gdf(r["target_layer"])
                if r["target_field"] not in tgt.columns:
                    v["messages"].append(f"Target field '{r['target_field']}' missing.")
                else:
                    lv = local[r["local_field"]]
                    tv = tgt[r["target_field"]]
                    tdups = int(tv.dropna().duplicated().sum())
                    matched = int(lv.dropna().isin(set(tv.dropna())).sum())
                    v.update({
                        "local_non_null": int(lv.notna().sum()), "local_null": int(lv.isna().sum()),
                        "matched": matched, "unmatched": int(lv.notna().sum()) - matched,
                        "target_duplicate_keys": tdups,
                    })
                    if tdups and r.get("kind", "many_to_one").endswith("to_one"):
                        v["messages"].append(f"Target key '{r['target_field']}' has {tdups} duplicate values: "
                                             "joins through it are ambiguous.")
                    if v["unmatched"]:
                        v["messages"].append(f"{v['unmatched']} local values have no match in target.")
                    v["status"] = "valid" if not v["messages"] else "warning"
            out.append({"relationship_id": f"{layer_id}.{r['local_field']}->{r['target_layer']}.{r['target_field']}",
                        "local_field": r["local_field"], "target_layer": r["target_layer"],
                        "target_field": r["target_field"], "kind": r.get("kind", "many_to_one"), "validation": v})
        self.store.set_relationships(layer_id, out)
        _ = info
        return out
