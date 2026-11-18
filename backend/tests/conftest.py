import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402

from hpw_gis.api.main import create_app  # noqa: E402
from hpw_gis.config import PROJECT_ROOT, Settings  # noqa: E402
from hpw_gis.fixtures import build  # noqa: E402


@pytest.fixture(scope="session")
def fixtures_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("fixtures")
    build(d)
    return d


@pytest.fixture()
def settings(tmp_path, fixtures_dir) -> Settings:
    return Settings(workspace=tmp_path / "ws", config_dir=PROJECT_ROOT / "config", fixtures_dir=fixtures_dir,
                    ui_dir=tmp_path / "no_ui")


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    return TestClient(app)


def run(client, tool_id, **params):
    r = client.post("/api/tool-runs", json={"tool_id": tool_id, "params": params, "wait": True})
    assert r.status_code in (200, 422), r.text
    return r.json()
