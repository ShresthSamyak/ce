"""End-to-end checks against an isolated SQLite database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.database import connection


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROCTORING_LAB_DB", str(tmp_path / "lab.sqlite3"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    with TestClient(main.app) as test_client:
        yield test_client


def start(client: TestClient) -> str:
    response = client.post("/api/session/start", json={
        "user_agent": "TestBrowser/1", "platform": "TestOS",
        "screen_width": 1920, "screen_height": 1080,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def event_payload(session_id: str, event_type: str = "visibilitychange", **changes):
    payload = {
        "event_id": str(uuid4()), "session_id": session_id, "event_type": event_type,
        "timestamp_client": BASE.isoformat(), "visibility_state": "hidden",
        "document_has_focus": False, "fullscreen": False,
        "screen_width": 1920, "screen_height": 1080,
        "viewport_width": 1500, "viewport_height": 850,
        "user_agent": "TestBrowser/1", "metadata": {},
    }
    payload.update(changes)
    return payload


def test_session_creation_and_event_persistence(client: TestClient):
    session_id = start(client)
    event = client.post("/api/events", json=event_payload(session_id))
    assert event.status_code == 201, event.text
    assert event.json()["timestamp_server"]
    with connection() as db:
        row = db.execute("SELECT * FROM events WHERE session_id=?", (session_id,)).fetchone()
        assert row["event_type"] == "visibilitychange"
        assert row["visibility_state"] == "hidden"
    response = client.get(f"/api/session/{session_id}")
    assert response.json()["counts"]["events"] == 1


def test_heartbeat_delta_and_thresholds(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    session_id = start(client)
    times = iter((BASE, BASE + timedelta(seconds=2), BASE + timedelta(seconds=6), BASE + timedelta(seconds=15)))
    monkeypatch.setattr(main, "utc_now", lambda: next(times).isoformat(timespec="milliseconds"))
    observed = []
    for sequence in range(4):
        response = client.post("/api/heartbeat", json={
            "session_id": session_id, "sequence": sequence,
            "client_timestamp": BASE.isoformat(), "visibility_state": "visible",
            "has_focus": True, "fullscreen": False,
        })
        assert response.status_code == 201, response.text
        observed.append(response.json())
    assert [item["gap_level"] for item in observed] == ["FIRST", "NORMAL", "WARNING", "LARGE GAP"]
    assert [item["delta_ms"] for item in observed] == [None, 2000.0, 4000.0, 9000.0]
    assert client.get(f"/api/session/{session_id}/analysis").json()["summary"]["longest_heartbeat_gap_ms"] == 9000.0


def test_timeline_ordering_and_marker_correlation(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    session_id = start(client)
    times = iter((BASE + timedelta(seconds=2), BASE + timedelta(seconds=3), BASE + timedelta(seconds=5)))
    monkeypatch.setattr(main, "utc_now", lambda: next(times).isoformat(timespec="milliseconds"))
    assert client.post("/api/events", json=event_payload(session_id, event_type="blur")).status_code == 201
    marker = client.post("/api/marker", json={
        "session_id": session_id, "label": "Switched browser tab",
        "timestamp_client": BASE.isoformat(),
    })
    assert marker.status_code == 201
    assert client.post("/api/events", json=event_payload(session_id, event_type="visibilitychange")).status_code == 201
    timeline = client.get(f"/api/session/{session_id}/timeline").json()["items"]
    assert [item["timestamp_server"] for item in timeline] == sorted(item["timestamp_server"] for item in timeline)
    analysis = client.get(f"/api/session/{session_id}/analysis").json()
    correlation = analysis["correlations"][0]
    assert {signal["event_type"] for signal in correlation["signals"]} == {"blur", "visibilitychange"}
    assert analysis["detection_matrix"][0]["visibilitychange"] == "hidden"
    assert analysis["detection_matrix"][0]["blur"] == "observed"


def test_report_generation_escapes_marker_and_only_measured_rows(client: TestClient):
    session_id = start(client)
    marker = client.post("/api/marker", json={
        "session_id": session_id, "label": "<script>alert(1)</script>",
        "timestamp_client": BASE.isoformat(),
    })
    assert marker.status_code == 201
    response = client.get(f"/api/session/{session_id}/report")
    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "Absence of a browser event does not imply absence of external activity" in response.text
    report_file = Path(main.PROJECT_ROOT) / "reports" / f"session_{session_id}.html"
    assert report_file.exists()
    assert client.get(f"/api/session/{session_id}/analysis").json()["detection_matrix"][0]["action"] == "<script>alert(1)</script>"


def test_rejects_sensitive_metadata_and_ended_session(client: TestClient):
    session_id = start(client)
    bad_key = client.post("/api/events", json=event_payload(session_id, "keydown", metadata={"key": "Secret"}))
    assert bad_key.status_code == 422
    bad_clipboard = client.post("/api/events", json=event_payload(session_id, "paste", metadata={"text": "Secret"}))
    assert bad_clipboard.status_code == 422
    bad_modifier = client.post("/api/events", json=event_payload(session_id, "keydown", metadata={"keyCategory": "character", "ctrl": "secret"}))
    assert bad_modifier.status_code == 422
    too_large = client.post("/api/events", content="x" * 8193, headers={"content-type": "application/json"})
    assert too_large.status_code == 413
    assert client.post("/api/session/end", json={"session_id": session_id}).status_code == 200
    assert client.post("/api/events", json=event_payload(session_id)).status_code == 409
    assert client.get("/api/session/not-a-uuid/analysis").status_code == 422


def test_matrix_ignores_marker_typing_as_action_signal(client: TestClient):
    session_id = start(client)
    assert client.post("/api/events", json=event_payload(session_id, "keydown", metadata={
        "keyCategory": "character", "ctrl": False, "alt": False,
        "shift": False, "meta": False, "repeat": False,
    })).status_code == 201
    assert client.post("/api/marker", json={
        "session_id": session_id, "label": "VMware minimized",
        "timestamp_client": BASE.isoformat(),
    }).status_code == 201
    matrix = client.get(f"/api/session/{session_id}/analysis").json()["detection_matrix"]
    assert matrix[0]["browser_observable"] == "no listed signal observed in ±3 s"


def test_frontend_is_served(client: TestClient):
    assert client.get("/").status_code == 200
    assert client.get("/styles.css").status_code == 200
    assert client.get("/monitor.js").status_code == 200
