"""Exercise the running localhost server without executing submitted code.

The script creates one clearly labeled synthetic session in the local database.
It does not make claims about real tab, desktop, or VMware behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = "http://127.0.0.1:8000"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request(path: str, payload: dict | None = None) -> tuple[int, bytes]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    call = Request(BASE_URL + path, data=body, headers=headers)
    with urlopen(call, timeout=10) as response:
        return response.status, response.read()


def json_request(path: str, payload: dict | None = None) -> dict:
    status, body = request(path, payload)
    assert status in {200, 201}, (path, status, body[:200])
    return json.loads(body)


def main() -> None:
    for path in ("/", "/static/styles.css", "/static/monitor.js", "/favicon.ico"):
        status, _ = request(path)
        assert status == 200, (path, status)

    session = json_request("/api/session/start", {
        "user_agent": "ProctoringLabSmoke/1", "platform": "Synthetic local test",
        "screen_width": 1280, "screen_height": 720,
        "viewport_width": 1100, "viewport_height": 650,
        "language": "en-US", "timezone": "UTC", "duration_minutes": 30,
    })
    session_id = session["id"]
    event = json_request("/api/events", {
        "event_id": str(uuid4()), "session_id": session_id,
        "event_type": "blur", "sequence": 1, "performance_ms": 1234.125,
        "timestamp_client": now(), "visibility_state": "visible",
        "document_has_focus": False, "fullscreen": False,
        "screen_width": 1280, "screen_height": 720,
        "viewport_width": 1100, "viewport_height": 650,
        "user_agent": "ProctoringLabSmoke/1", "metadata": {},
    })
    assert event["event_type"] == "blur"
    for sequence in (1, 2):
        heartbeat = json_request("/api/heartbeat", {
            "session_id": session_id, "sequence": sequence,
            "client_timestamp": now(), "performance_ms": 2000.0 * sequence,
            "visibility_state": "visible", "has_focus": False,
            "fullscreen": False,
        })
    assert heartbeat["delta_ms"] is not None
    json_request("/api/marker", {
        "session_id": session_id, "label": "Automated local API smoke test",
        "timestamp_client": now(),
    })
    submission = json_request("/api/submission", {
        "session_id": session_id, "question_id": "q1", "language": "Python",
        "action": "run", "code_length": 0, "timestamp_client": now(),
    })
    assert submission["mocked"] is True
    json_request("/api/session/end", {"session_id": session_id})
    details = json_request(f"/api/session/{session_id}")
    timeline = json_request(f"/api/session/{session_id}/timeline")
    analysis = json_request(f"/api/session/{session_id}/analysis")
    report_status, report = request(f"/api/session/{session_id}/report")
    export = json_request(f"/api/session/{session_id}/export/json")
    csv_status, csv_body = request(f"/api/session/{session_id}/export/csv")
    assert details["counts"]["events"] == 1
    assert details["counts"]["heartbeats"] == 2
    assert len(timeline["items"]) >= 6
    assert analysis["summary"]["focus_loss_count"] == 1
    assert len(analysis["detection_matrix"]) == 1
    assert report_status == 200 and b"Executive summary" in report
    assert export["events"][0]["event_type"] == "blur"
    assert csv_status == 200 and b"EVENT" in csv_body
    print(f"PASS localhost API, persistence, heartbeat, analysis, report, exports: {session_id}")
    print("Synthetic API data only; no browser or VM behavior was measured by this script.")


if __name__ == "__main__":
    main()
