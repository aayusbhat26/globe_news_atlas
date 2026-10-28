"""Search keeps its array contract but reports the true total via a header."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.snapshot_service import snapshot_service


def _fts_index(root, rows):
    database = root / "search_index.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE events_fts USING fts5(
                event_id UNINDEXED, title, body, summary, countries, location,
                outlet, category UNINDEXED, updated_at UNINDEXED,
                importance UNINDEXED, lat UNINDEXED, lng UNINDEXED,
                status UNINDEXED, outlet_count UNINDEXED, url UNINDEXED
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO events_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture()
def search_env(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot_service, "root", tmp_path)
    snapshot_service._cache.clear()
    snapshot_service._mtimes.clear()
    yield tmp_path
    snapshot_service._cache.clear()
    snapshot_service._mtimes.clear()


def test_search_header_reports_fts_total_and_preserves_order(search_env):
    stamp = datetime.now(timezone.utc).isoformat()
    _fts_index(
        search_env,
        [
            (
                "evt-low",
                "Low importance story",
                "regional alpha report",
                "Summary",
                "India",
                "India",
                "Outlet A",
                "politics",
                stamp,
                0.2,
                20.0,
                77.0,
                "developing",
                2,
                "https://example.com/low",
            ),
            (
                "evt-high",
                "High importance story",
                "regional alpha report",
                "Summary",
                "India",
                "India",
                "Outlet B",
                "politics",
                stamp,
                0.9,
                20.0,
                77.0,
                "breaking",
                5,
                "https://example.com/high",
            ),
        ],
    )
    client = TestClient(app)
    response = client.get("/v1/search", params={"q": "", "window": "24h", "limit": 1})
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["id"] == "evt-high"

    filtered = client.get(
        "/v1/search", params={"q": "regional", "window": "24h", "limit": 1}
    )
    assert filtered.status_code == 200
    assert filtered.headers["x-total-count"] == "2"


def test_search_header_reports_snapshot_fallback_total(search_env, monkeypatch):
    snapshot = {
        "available": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "events": [
            {
                "id": "evt-a",
                "t": "Alpha one",
                "sum": "alpha",
                "cat": "politics",
                "imp": 0.2,
                "st": "developing",
                "oc": 1,
                "loc": "India",
                "at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "evt-b",
                "t": "Alpha two",
                "sum": "alpha",
                "cat": "politics",
                "imp": 0.9,
                "st": "breaking",
                "oc": 3,
                "loc": "India",
                "at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "evt-c",
                "t": "Alpha three",
                "sum": "alpha",
                "cat": "politics",
                "imp": 0.5,
                "st": "developing",
                "oc": 2,
                "loc": "India",
                "at": datetime.now(timezone.utc).isoformat(),
            },
        ],
        "arcs": [],
    }
    monkeypatch.setattr(snapshot_service, "get_snapshot", lambda window: snapshot)

    client = TestClient(app)
    response = client.get("/v1/search", params={"q": "alpha", "window": "24h", "limit": 2})
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "3"
    payload = response.json()
    assert [item["id"] for item in payload] == ["evt-b", "evt-c"]
