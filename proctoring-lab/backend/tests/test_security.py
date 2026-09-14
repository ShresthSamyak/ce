"""Regression checks for local-only API write guards."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def test_api_rejects_foreign_host_origin_and_non_json_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCTORING_LAB_DB", str(tmp_path / "security.sqlite3"))
    payload = {
        "user_agent": "SecurityTest/1", "platform": "TestOS",
        "screen_width": 1024, "screen_height": 768,
    }
    with TestClient(app) as client:
        assert client.post(
            "/api/session/start", json=payload,
            headers={"Origin": "http://testserver"},
        ).status_code == 201
        assert client.post(
            "/api/session/start", json=payload,
            headers={"Origin": "https://foreign.example"},
        ).status_code == 403
        assert client.post(
            "/api/session/start", json=payload,
            headers={"Host": "rebound.example"},
        ).status_code == 400
        assert client.post(
            "/api/session/start", content="{}",
            headers={"Content-Type": "text/plain"},
        ).status_code == 415
