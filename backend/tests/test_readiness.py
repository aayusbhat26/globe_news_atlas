"""Health/liveness and readiness behaviour for serving data and the auth DB."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.store import auth_store
from app.config import settings
from app.main import app
from app.services.snapshot_service import snapshot_service


@pytest.fixture()
def serving_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_db_backend", "sqlite")
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "auth.db"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "snapshot_max_age_seconds", 3600)
    auth_store.reset_runtime_state()
    serving = tmp_path / "serving"
    serving.mkdir()
    monkeypatch.setattr(snapshot_service, "root", serving)
    snapshot_service._cache.clear()
    snapshot_service._mtimes.clear()
    yield serving
    snapshot_service._cache.clear()
    snapshot_service._mtimes.clear()
    auth_store.reset_runtime_state()


def _write_snapshot(root, generated_at: datetime) -> None:
    stamp = generated_at.isoformat()
    (root / "world_24h.json").write_text(
        json.dumps(
            {
                "ts": stamp,
                "w": "24h",
                "n": {"e": 0, "a": 0},
                "events": [],
                "arcs": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps({"run_id": "test-run", "generated_at": stamp}),
        encoding="utf-8",
    )


def test_health_and_ready_without_data(serving_env):
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "degraded"
    assert body["ready"] is False
    assert body["data_age_seconds"] is None
    assert health.headers["cache-control"] == "no-store"

    ready = client.get("/ready")
    assert ready.status_code == 503
    payload = ready.json()
    assert payload["status"] == "not_ready"
    assert payload["snapshot_ready"] is False
    assert payload["auth_db_ready"] is True
    assert ready.headers["cache-control"] == "no-store"


def test_health_and_ready_with_fresh_snapshot(serving_env):
    _write_snapshot(serving_env, datetime.now(timezone.utc) - timedelta(seconds=30))
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert 0 <= body["data_age_seconds"] < 120

    ready = client.get("/ready")
    assert ready.status_code == 200
    payload = ready.json()
    assert payload["status"] == "ready"
    assert payload["snapshot_ready"] is True
    assert payload["auth_db_ready"] is True


def test_ready_rejects_stale_snapshot(serving_env):
    _write_snapshot(serving_env, datetime.now(timezone.utc) - timedelta(hours=5))
    client = TestClient(app)

    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["snapshot_ready"] is False
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["data_age_seconds"] > 3600


def test_ready_fails_when_auth_database_is_down(serving_env, monkeypatch):
    _write_snapshot(serving_env, datetime.now(timezone.utc))
    monkeypatch.setattr(auth_store, "ping", lambda: False)
    client = TestClient(app)

    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["auth_db_ready"] is False

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["ready"] is False


def test_health_head_still_works(serving_env):
    client = TestClient(app)
    response = client.head("/health")
    assert response.status_code == 200
    assert response.content == b""
