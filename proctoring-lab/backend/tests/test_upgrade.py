"""Checks for the richer local assessment and backward-compatible storage."""

from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.database import connection, initialize_database


NOW = datetime(2026, 9, 14, tzinfo=timezone.utc).isoformat()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROCTORING_LAB_DB", str(tmp_path / "lab.sqlite3"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    with TestClient(main.app) as test_client:
        yield test_client


def start(client: TestClient) -> str:
    response = client.post("/api/session/start", json={
        "user_agent": "LocalTest/1", "platform": "Windows",
        "screen_width": 1920, "screen_height": 1080,
        "viewport_width": 1440, "viewport_height": 820,
        "language": "en-US", "hardware_concurrency": 8,
        "device_memory": 16, "timezone": "Asia/Kolkata",
        "duration_minutes": 45,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def event(session_id: str, event_type: str, sequence: int, **changes) -> dict:
    payload = {
        "event_id": str(uuid4()), "session_id": session_id,
        "event_type": event_type, "sequence": sequence,
        "performance_ms": 15000.125 + sequence,
        "timestamp_client": NOW, "visibility_state": "visible",
        "document_has_focus": True, "fullscreen": True,
        "screen_width": 1920, "screen_height": 1080,
        "viewport_width": 1440, "viewport_height": 820,
        "user_agent": "LocalTest/1", "metadata": {},
    }
    payload.update(changes)
    return payload


def test_rich_environment_and_measured_signal_analysis(client: TestClient):
    session_id = start(client)
    session = client.get(f"/api/session/{session_id}").json()
    assert session["duration_minutes"] == 45
    assert session["timezone"] == "Asia/Kolkata"
    assert session["hardware_concurrency"] == 8

    observations = [
        event(session_id, "blur", 1, document_has_focus=False),
        event(session_id, "visibilitychange", 2, visibility_state="hidden", document_has_focus=False),
        event(session_id, "fullscreenchange", 3, fullscreen=False),
        event(session_id, "offline", 4),
        event(session_id, "editor_change", 5, metadata={
            "old_length": 50, "new_length": 251,
            "delta_length": 201, "change_size": "LARGE_CHANGE",
        }),
    ]
    for payload in observations:
        response = client.post("/api/events", json=payload)
        assert response.status_code == 201, response.text
    assert response.json()["performance_ms"] == pytest.approx(15005.125)

    marker = client.post("/api/marker", json={
        "session_id": session_id, "label": "Guest OS Alt-Tab",
        "timestamp_client": NOW,
    })
    assert marker.status_code == 201, marker.text
    analysis = client.get(f"/api/session/{session_id}/analysis").json()
    summary = analysis["summary"]
    assert summary["focus_loss_count"] == 1
    assert summary["visibility_hidden_count"] == 1
    assert summary["fullscreen_exit_count"] == 1
    assert summary["network_offline_count"] == 1
    assert summary["editor_change_distribution"]["LARGE_CHANGE"] == 1
    observed = analysis["correlations"][0]["observed"]
    assert observed["window_blur"] is True
    assert observed["document_hidden"] is True
    assert observed["fullscreen_exit"] is True
    assert observed["network_change"] is True
    assert analysis["detection_matrix"][0]["action"] == "Guest OS Alt-Tab"
    timeline = client.get(f"/api/session/{session_id}/timeline").json()["items"]
    assert [item["timestamp_server"] for item in timeline] == sorted(
        item["timestamp_server"] for item in timeline
    )


def test_mock_submissions_exports_and_report(client: TestClient):
    session_id = start(client)
    payload = {
        "session_id": session_id, "question_id": "q2",
        "language": "Python", "action": "submit",
        "code_length": 137, "timestamp_client": NOW,
    }
    submission = client.post("/api/submission", json=payload)
    assert submission.status_code == 201, submission.text
    assert submission.json()["mocked"] is True
    assert submission.json()["submission_number"] == 1
    assert "source" not in submission.json()
    assert client.post("/api/submission", json={**payload, "code": "print('secret')"}).status_code == 422
    history = client.get(f"/api/session/{session_id}/submissions").json()["items"]
    assert len(history) == 1 and history[0]["question_id"] == "q2"

    json_response = client.get(f"/api/session/{session_id}/export/json")
    assert json_response.status_code == 200
    assert "attachment" in json_response.headers["content-disposition"]
    exported = json_response.json()
    assert exported["session"]["id"] == session_id
    assert len(exported["submissions"]) == 1
    csv_response = client.get(f"/api/session/{session_id}/export/csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert any(row["kind"] == "SUBMISSION" for row in rows)

    report = client.get(f"/api/session/{session_id}/report")
    assert report.status_code == 200
    assert "Submission" in report.text
    assert "Mock" in report.text or "mock" in report.text
    assert (Path(main.PROJECT_ROOT) / "reports" / f"session_{session_id}.html").is_file()


def test_rejects_editor_contents_and_preserves_legacy_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_file = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("PROCTORING_LAB_DB", str(database_file))
    legacy_id = str(uuid4())
    with closing(sqlite3.connect(database_file)) as db:
        db.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
                ended_at TEXT, user_agent TEXT NOT NULL, platform TEXT NOT NULL,
                screen_width INTEGER NOT NULL, screen_height INTEGER NOT NULL);
            CREATE TABLE events (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                event_type TEXT NOT NULL, client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL, visibility_state TEXT NOT NULL,
                document_has_focus INTEGER NOT NULL, fullscreen INTEGER NOT NULL,
                screen_width INTEGER NOT NULL, screen_height INTEGER NOT NULL,
                viewport_width INTEGER NOT NULL, viewport_height INTEGER NOT NULL,
                user_agent TEXT NOT NULL, metadata_json TEXT NOT NULL);
            CREATE TABLE heartbeats (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL, delta_ms REAL, gap_level TEXT NOT NULL,
                visibility_state TEXT NOT NULL, has_focus INTEGER NOT NULL,
                fullscreen INTEGER NOT NULL, UNIQUE(session_id, sequence));
            CREATE TABLE markers (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                label TEXT NOT NULL, client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL);
        """)
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)", (
            legacy_id, NOW, None, "OldBrowser", "OldOS", 1280, 720,
        ))
        db.commit()
    initialize_database()
    with connection() as db:
        assert db.execute("SELECT id FROM sessions WHERE id=?", (legacy_id,)).fetchone() is not None
        assert "performance_ms" in {row["name"] for row in db.execute("PRAGMA table_info(events)")}
        assert "duration_minutes" in {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
        assert db.execute("SELECT name FROM sqlite_master WHERE name='submissions'").fetchone() is not None
