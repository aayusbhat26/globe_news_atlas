import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.store import auth_store
from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ok", "degraded"}
    assert data["status"] == ("ok" if data["ready"] else "degraded")
    assert isinstance(data["ready"], bool)
    assert "data_age_seconds" in data
    assert "version" in data
    assert "data" in data
    head = client.head("/health")
    assert head.status_code == 200
    assert head.content == b""


def test_get_snapshot_default():
    response = client.get("/v1/snapshot?window=24h")
    assert response.status_code == 200
    data = response.json()
    assert data["w"] == "24h"
    assert isinstance(data["events"], list)
    assert isinstance(data["arcs"], list)
    assert "available" in data
    if data["events"]:
        event = data["events"][0]
        for field in ("id", "lat", "lng", "cat", "imp", "t", "st", "sum", "loc"):
            assert field in event


def test_cache_headers_distinguish_live_and_static_data():
    snapshot = client.get("/v1/snapshot?window=24h")
    assert snapshot.status_code == 200
    assert snapshot.headers["cache-control"] == f"public, max-age={settings.snapshot_refresh_seconds}"
    assert client.get("/health").headers["cache-control"] == "no-store"
    assert client.get("/v1/outlets").headers["cache-control"] == "no-store"


def test_snapshot_rejects_unknown_window():
    response = client.get("/v1/snapshot?window=90d")
    assert response.status_code == 422


def test_unknown_event_returns_404():
    assert client.get("/v1/events/does-not-exist/card").status_code == 404
    assert client.get("/v1/events/does-not-exist").status_code == 404


def test_event_card_and_detail_match_snapshot():
    snapshot = client.get("/v1/snapshot?window=24h").json()
    if not snapshot["events"]:
        pytest.skip("No pipeline data available yet")
    event_id = snapshot["events"][0]["id"]

    card = client.get(f"/v1/events/{event_id}/card")
    assert card.status_code == 200
    assert card.json()["id"] == event_id
    assert "spectrum" in card.json()

    detail = client.get(f"/v1/events/{event_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == event_id
    assert isinstance(body["coverage"], list)
    assert isinstance(body["timeline"], list)
    assert isinstance(body["sources"], list)
    assert isinstance(body.get("excerpt"), str)
    assert "spectrum" in body


def test_search_events():
    response = client.get("/v1/search?q=&window=30d&limit=5")
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    assert len(results) <= 5


def test_country_brief_is_ranked_and_capped():
    snapshot = client.get("/v1/snapshot?window=24h").json()
    if not snapshot["events"]:
        pytest.skip("No pipeline data available yet")

    country = ""
    for event in snapshot["events"]:
        detail = client.get(f"/v1/events/{event['id']}").json()
        if detail.get("countries"):
            country = detail["countries"][0]
            break
    if not country:
        pytest.skip("No country-tagged events available yet")

    response = client.get("/v1/countries/brief", params={"name": country, "window": "24h"})
    assert response.status_code == 200
    body = response.json()
    assert body["country"] == country
    assert body["total_events"] >= 1
    assert [section["key"] for section in body["sections"]] == [
        "all",
        "brief",
        "protest",
        "conflict",
        "technology",
    ]
    all_section = body["sections"][0]
    assert all_section["count"] == body["total_events"]
    for section in body["sections"]:
        assert len(section["events"]) <= 10
        assert section["count"] >= len(section["events"])
    assert set(body["counts"]) == {"protest", "conflict", "technology"}


def test_country_brief_handles_unknown_country():
    response = client.get("/v1/countries/brief", params={"name": "Atlantis", "window": "24h"})
    assert response.status_code == 200
    body = response.json()
    assert body["country"] == "Atlantis"
    assert body["total_events"] == 0
    assert len(body["sections"]) == 5
    assert client.get("/v1/countries/brief?name=India&window=90d").status_code == 422


def test_country_brief_widening_window_never_reduces_counts():
    snapshot = client.get("/v1/snapshot?window=24h").json()
    if not snapshot["events"]:
        pytest.skip("No pipeline data available yet")
    country = ""
    for event in snapshot["events"]:
        detail = client.get(f"/v1/events/{event['id']}").json()
        if detail.get("countries"):
            country = detail["countries"][0]
            break
    if not country:
        pytest.skip("No country-tagged events available yet")

    daily = client.get("/v1/countries/brief", params={"name": country, "window": "24h"}).json()
    weekly = client.get("/v1/countries/brief", params={"name": country, "window": "7d"}).json()
    assert weekly["total_events"] >= daily["total_events"]
    assert weekly["brief_events"] >= daily["brief_events"]
    assert len(weekly["sections"][0]["events"]) <= 10


def test_get_outlets():
    response = client.get("/v1/outlets")
    assert response.status_code == 200
    outlets = response.json()
    assert isinstance(outlets, list)
    assert any(o["id"] == "reuters" for o in outlets)


def _isolated_feedback_db(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_db_backend", "sqlite")
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "auth.db"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    auth_store.reset_runtime_state()


def test_feedback_report_is_persisted_in_auth_database(monkeypatch, tmp_path):
    _isolated_feedback_db(monkeypatch, tmp_path)
    response = client.post(
        "/v1/feedback",
        json={
            "event_id": "evt-test",
            "category": "wrong_location",
            "details": "Coordinates point to the wrong city.",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "recorded"

    with auth_store.connection() as conn:
        row = conn.execute(
            "SELECT id, event_id, category, details FROM feedback WHERE id = ?",
            (body["id"],),
        ).fetchone()
    assert row is not None
    assert row["event_id"] == "evt-test"
    assert row["category"] == "wrong_location"
    assert "wrong city" in row["details"]


def test_feedback_falls_back_to_file_when_database_is_unavailable(
    monkeypatch, tmp_path
):
    _isolated_feedback_db(monkeypatch, tmp_path)

    def unavailable(*args, **kwargs):
        raise RuntimeError("account database down")

    monkeypatch.setattr(auth_store, "save_feedback", unavailable)
    response = client.post(
        "/v1/feedback",
        json={
            "event_id": "evt-fallback",
            "category": "wrong_summary",
            "details": "The summary is missing context.",
        },
    )
    assert response.status_code == 201
    body = response.json()

    report_file = tmp_path / "feedback" / "reports.jsonl"
    assert report_file.exists()
    record = json.loads(report_file.read_text(encoding="utf-8").splitlines()[0])
    assert record["event_id"] == "evt-fallback"
    assert record["category"] == "wrong_summary"
    assert record["id"] == body["id"]


def test_feedback_rejects_unknown_category():
    response = client.post(
        "/v1/feedback",
        json={"event_id": "evt-test", "category": "not-a-category", "details": ""},
    )
    assert response.status_code == 422


def test_empty_serving_store(monkeypatch, tmp_path):
    from app.services.snapshot_service import snapshot_service

    monkeypatch.setattr(snapshot_service, "root", tmp_path)
    snapshot_service._cache.clear()
    snapshot_service._mtimes.clear()
    data = snapshot_service.get_snapshot("24h")
    assert data["events"] == []
    assert data["available"] is False
    assert snapshot_service.get_detail("missing") is None


def test_search_uses_full_text_index(monkeypatch, tmp_path):
    database = tmp_path / "search_index.sqlite3"
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
        connection.execute(
            """
            INSERT INTO events_fts VALUES (
                'evt-fts-1', 'Regional execution case', ?, 'Short summary only.',
                'Saudi Arabia, Bangladesh', 'Saudi Arabia', 'Example News',
                'politics', ?, 0.6, 24.7, 46.7, 'developing', 4,
                'https://example.com/story'
            )
            """,
            (
                "Consular officials described a distinctive evidentiary detail.",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    from app.services.snapshot_service import snapshot_service
    from app.services.search_service import search_service

    monkeypatch.setattr(snapshot_service, "root", tmp_path)
    results = search_service.search_events("distinctive", window="24h", limit=5)
    assert len(results) == 1
    result = results[0]
    assert result.id == "evt-fts-1"
    assert result.summary == "Short summary only."
    assert "distinctive" not in result.summary


def test_event_detail_exposes_source_accounting_and_via_google_news(monkeypatch):
    from app.services.snapshot_service import snapshot_service

    detail = {
        "id": "evt-sources",
        "title": "Source accounting",
        "status": "breaking",
        "category": "politics",
        "severity": "low",
        "summary": "A payload with capped sources.",
        "sources_total": 12,
        "sources_shown": 1,
        "sources": [
            {
                "url": "https://example.com/story",
                "outlet_name": "Example News",
                "alignment": "centre",
                "via_google_news": True,
                "pipeline_extra": "preserved",
            }
        ],
        "spectrum": {"left": 0, "centre": 1, "right": 0, "unrated": 0},
        "coverage": [],
    }
    monkeypatch.setattr(snapshot_service, "get_detail", lambda event_id: detail)

    response = client.get("/v1/events/evt-sources")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources_total"] == 12
    assert body["sources_shown"] == 1
    assert body["sources"][0]["via_google_news"] is True
    assert body["sources"][0]["pipeline_extra"] == "preserved"


def test_event_detail_without_optional_source_fields_still_validates(monkeypatch):
    from app.services.snapshot_service import snapshot_service

    detail = {
        "id": "evt-plain",
        "title": "Plain payload",
        "status": "developing",
        "category": "politics",
        "summary": "No new fields.",
        "sources": [{"url": "https://example.com/a", "outlet_name": "Example"}],
        "spectrum": {"left": 1, "centre": 0, "right": 0, "unrated": 0},
        "coverage": [],
    }
    monkeypatch.setattr(snapshot_service, "get_detail", lambda event_id: detail)

    body = client.get("/v1/events/evt-plain").json()
    assert body["sources_total"] is None
    assert body["sources_shown"] is None
    assert body["sources"][0]["via_google_news"] is None


def test_fallback_framing_notes_are_grammatical():
    from app.services.event_service import event_service

    detail = event_service._fallback_detail(
        {
            "id": "evt-framing",
            "t": "Framing note",
            "sp": {"left": 1, "centre": 2, "right": 0, "unrated": 3},
            "oc": 6,
        },
        "24h",
    )
    notes = [column.framing_note for column in detail.coverage]
    assert "1 left-rated outlet reported this event." in notes
    assert "2 centre-rated outlets reported this event." in notes
    assert "3 unrated outlets reported this event." in notes
    assert all("outlet(s)" not in note and "unrated-rated" not in note for note in notes)


def test_pipeline_framing_notes_are_normalized(monkeypatch):
    from app.services.snapshot_service import snapshot_service

    detail = {
        "id": "evt-framing-pipeline",
        "title": "Framing normalization",
        "status": "developing",
        "category": "politics",
        "summary": "Old pipeline notes.",
        "coverage": [
            {
                "camp": "unrated",
                "outlet_count": 1,
                "article_count": 1,
                "framing_note": "1 unrated-rated outlet(s) reported this event.",
            },
            {
                "camp": "centre",
                "outlet_count": 3,
                "article_count": 4,
                "framing_note": "3 centre-rated outlet(s) reported this event.",
            },
        ],
        "spectrum": {"left": 0, "centre": 3, "right": 0, "unrated": 1},
        "sources": [],
    }
    monkeypatch.setattr(snapshot_service, "get_detail", lambda event_id: detail)

    body = client.get("/v1/events/evt-framing-pipeline").json()
    notes = [column["framing_note"] for column in body["coverage"]]
    assert notes == [
        "1 unrated outlet reported this event.",
        "3 centre-rated outlets reported this event.",
    ]
