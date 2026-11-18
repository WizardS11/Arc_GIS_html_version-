"""SQLite metadata store: layers, versions, relationships, tools, runs, projects (spec §9.1)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS layers (
    layer_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    tier TEXT NOT NULL,
    geometry_family TEXT,
    crs TEXT,
    primary_key TEXT,
    source_uri TEXT,
    current_version_id TEXT,
    parent_run_id TEXT,
    descriptor_json TEXT,
    permissions_json TEXT,
    profile_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS layer_versions (
    version_id TEXT PRIMARY KEY,
    layer_id TEXT NOT NULL REFERENCES layers(layer_id),
    path TEXT NOT NULL,
    format TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    feature_count INTEGER NOT NULL,
    bronze_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationships (
    relationship_id TEXT PRIMARY KEY,
    layer_id TEXT NOT NULL REFERENCES layers(layer_id),
    local_field TEXT NOT NULL,
    target_layer TEXT NOT NULL,
    target_field TEXT NOT NULL,
    kind TEXT NOT NULL,
    validation_json TEXT
);
CREATE TABLE IF NOT EXISTS tools (
    tool_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    version TEXT NOT NULL,
    reference_url TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_runs (
    run_id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL REFERENCES tools(tool_id),
    tool_version TEXT NOT NULL,
    status TEXT NOT NULL,
    params_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_s REAL,
    messages_json TEXT,
    result_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS run_inputs (
    run_id TEXT NOT NULL REFERENCES tool_runs(run_id),
    layer_version_id TEXT NOT NULL REFERENCES layer_versions(version_id),
    role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_outputs (
    run_id TEXT NOT NULL REFERENCES tool_runs(run_id),
    layer_version_id TEXT NOT NULL REFERENCES layer_versions(version_id),
    role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_definitions (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    revision INTEGER NOT NULL,
    graph_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(v: Any) -> str:
    return json.dumps(v, default=str)


class MetadataStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ---- layers -------------------------------------------------------
    def upsert_layer(self, row: dict) -> None:
        cols = [
            "layer_id", "label", "tier", "geometry_family", "crs", "primary_key", "source_uri",
            "current_version_id", "parent_run_id", "descriptor_json", "permissions_json", "profile_json", "created_at",
        ]
        vals = tuple(_dumps(row[c]) if c.endswith("_json") else row.get(c) for c in cols)
        self.execute(
            f"INSERT OR REPLACE INTO layers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals
        )

    def add_version(self, row: dict) -> None:
        cols = ["version_id", "layer_id", "path", "format", "sha256", "feature_count", "bronze_path", "created_at"]
        self.execute(
            f"INSERT INTO layer_versions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(row.get(c) for c in cols),
        )

    def layers(self) -> list[dict]:
        rows = self.query(
            "SELECT l.*, v.path, v.format, v.sha256, v.feature_count, v.bronze_path FROM layers l "
            "LEFT JOIN layer_versions v ON v.version_id = l.current_version_id ORDER BY l.rowid"
        )
        for r in rows:
            for k in ("descriptor_json", "permissions_json", "profile_json"):
                r[k.removesuffix("_json")] = json.loads(r.pop(k) or "null")
        return rows

    def set_relationships(self, layer_id: str, rels: list[dict]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM relationships WHERE layer_id = ?", (layer_id,))
            for r in rels:
                self._conn.execute(
                    "INSERT INTO relationships VALUES (?,?,?,?,?,?,?)",
                    (r["relationship_id"], layer_id, r["local_field"], r["target_layer"], r["target_field"],
                     r["kind"], _dumps(r.get("validation"))),
                )
            self._conn.commit()

    def relationships(self, layer_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM relationships" + (" WHERE layer_id = ?" if layer_id else "")
        rows = self.query(sql, (layer_id,) if layer_id else ())
        for r in rows:
            r["validation"] = json.loads(r.pop("validation_json") or "null")
        return rows

    # ---- tools & runs -------------------------------------------------
    def upsert_tool(self, tool_id: str, name: str, category: str, version: str, url: str, status: str) -> None:
        self.execute("INSERT OR REPLACE INTO tools VALUES (?,?,?,?,?,?)", (tool_id, name, category, version, url, status))

    def insert_run(self, run_id: str, tool_id: str, version: str, params: dict) -> None:
        self.execute(
            "INSERT INTO tool_runs (run_id, tool_id, tool_version, status, params_json, submitted_at) VALUES (?,?,?,?,?,?)",
            (run_id, tool_id, version, "queued", _dumps(params), now_iso()),
        )

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets, vals = [], []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            vals.append(_dumps(v) if k.endswith("_json") else v)
        self.execute(f"UPDATE tool_runs SET {', '.join(sets)} WHERE run_id = ?", (*vals, run_id))

    def add_run_io(self, table: str, run_id: str, version_id: str, role: str) -> None:
        assert table in ("run_inputs", "run_outputs")
        self.execute(f"INSERT INTO {table} VALUES (?,?,?)", (run_id, version_id, role))

    def runs(self, limit: int = 200) -> list[dict]:
        rows = self.query("SELECT * FROM tool_runs ORDER BY submitted_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self._decode_run(r) for r in rows]

    def run(self, run_id: str) -> dict | None:
        rows = self.query("SELECT * FROM tool_runs WHERE run_id = ?", (run_id,))
        return self._decode_run(rows[0]) if rows else None

    @staticmethod
    def _decode_run(r: dict) -> dict:
        for k in ("params_json", "messages_json", "result_json"):
            r[k.removesuffix("_json")] = json.loads(r.pop(k) or "null")
        return r

    # ---- projects -----------------------------------------------------
    def save_project(self, name: str, state: dict) -> None:
        self.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)", (name, _dumps(state), now_iso()))

    def projects(self) -> list[dict]:
        return self.query("SELECT name, updated_at FROM projects ORDER BY updated_at DESC")

    def project(self, name: str) -> dict | None:
        rows = self.query("SELECT * FROM projects WHERE name = ?", (name,))
        if not rows:
            return None
        r = rows[0]
        r["state"] = json.loads(r.pop("state_json"))
        return r
