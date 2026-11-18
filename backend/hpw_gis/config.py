"""Runtime settings. Everything is local-first and path-configurable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    workspace: Path = field(
        default_factory=lambda: Path(os.environ.get("HPW_WORKSPACE", PROJECT_ROOT / "workspaces" / "default"))
    )
    config_dir: Path = field(default_factory=lambda: Path(os.environ.get("HPW_CONFIG", PROJECT_ROOT / "config")))
    fixtures_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "fixtures")
    # Plain HTML/CSS/JS UI (no build step). Override the folder with HPW_UI_DIR.
    ui_dir: Path = field(default_factory=lambda: Path(os.environ.get("HPW_UI_DIR", PROJECT_ROOT / "web")))
    max_features_per_request: int = 20000
    max_table_page: int = 1000
    job_workers: int = 2
    bootstrap_layers: bool = True

    @property
    def db_path(self) -> Path:
        return self.workspace / "hpw_gis.sqlite"

    def tier_dir(self, tier: str) -> Path:
        p = self.workspace / "data" / tier
        p.mkdir(parents=True, exist_ok=True)
        return p

    def expand(self, uri: str) -> Path:
        """Expand ${FIXTURES}, ${DATA_ROOT}, ${PROJECT_ROOT} placeholders in descriptor URIs."""
        values = {
            "FIXTURES": str(self.fixtures_dir),
            "PROJECT_ROOT": str(PROJECT_ROOT),
            "DATA_ROOT": os.environ.get("HPW_DATA_ROOT", str(PROJECT_ROOT / "data")),
        }
        for k, v in values.items():
            uri = uri.replace("${" + k + "}", v)
        return Path(uri)
