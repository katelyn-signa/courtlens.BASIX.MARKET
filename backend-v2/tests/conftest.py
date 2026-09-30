import hashlib
import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.config import Settings
from app.db.base import Base
from app.main import create_app
from app.orchestration.registry import AgentRegistry, build_default_registry

_counter = itertools.count(1)


def make_settings(tmp_path, **overrides) -> Settings:
    values = dict(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", auto_migrate=False,
        storage_dir=str(tmp_path / "storage"), enable_demo_agents=True,
        agent_timeout_seconds=5.0, agent_max_attempts=2, agent_retry_delay_seconds=0.0,
        api_key=None, log_level="DEBUG")
    values.update(overrides)
    return Settings(_env_file=None, **values)


class Env:
    """Bundle of app + client + helpers for one isolated test database."""

    def __init__(self, app, client):
        self.app, self.client = app, client
        self.registry: AgentRegistry = app.state.registry

    def session(self) -> Session:
        return self.app.state.session_factory()

    def case(self, **kw) -> dict:
        body = {"title": "Synthetic case", "fir_number": f"FIR-{next(_counter)}"}
        body.update(kw)
        r = self.client.post("/api/v1/cases", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def doc(self, case_id: str, filename: str = "fir.pdf", content: str | None = None) -> dict:
        content = content or f"synthetic-{next(_counter)}"
        body = {"filename": filename, "mime_type": "application/pdf", "size_bytes": len(content),
                "checksum_sha256": hashlib.sha256(content.encode()).hexdigest()}
        r = self.client.post(f"/api/v1/cases/{case_id}/documents", json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()

    def run(self, case_id: str, **body):
        return self.client.post(f"/api/v1/cases/{case_id}/analysis-runs", json=body)


@pytest.fixture
def make_env(tmp_path):
    clients: list[TestClient] = []

    def _make(registry: AgentRegistry | None = None, **overrides) -> Env:
        settings = make_settings(tmp_path, **overrides)
        app = create_app(settings, registry=registry)
        Base.metadata.create_all(app.state.engine)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return Env(app, client)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def env(make_env) -> Env:
    return make_env()


@pytest.fixture
def empty_registry() -> AgentRegistry:
    return AgentRegistry()
