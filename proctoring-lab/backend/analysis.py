"""Analysis of recorded local browser signals. No VM outcome is presumed."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

WINDOW_SECONDS = 3
RELEVANT_EVENTS = {
    "blur", "focus", "visibilitychange", "fullscreenchange",
    "fullscreen_error", "online", "offline", "fetch_failure",
    "copy", "paste", "cut",
}


def _rows(db: sqlite3.Connection, table: str, session_id: str) -> list[dict[str, Any]]:
    """Read one of this module's fixed tables in server receipt order."""
    if table not in {"events", "heartbeats", "markers", "submissions"}:
        raise ValueError("Unknown analysis table")
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return []  # Older databases predate the submissions table.
    return [
        dict(row) for row in db.execute(
            f"SELECT * FROM {table} WHERE session_id=? ORDER BY server_timestamp, rowid",
            (session_id,),
        )
    ]


def _event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "EVENT", "id": row["id"], "event_id": row["id"],
        "session_id": row["session_id"], "event_type": row["event_type"],
        "sequence": row.get("sequence"), "performance_ms": row.get("performance_ms"),
        "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"],
        "visibility_state": row["visibility_state"],
        "document_has_focus": bool(row["document_has_focus"]),
        "fullscreen": bool(row["fullscreen"]),
        "screen_width": row["screen_width"], "screen_height": row["screen_height"],
        "viewport_width": row["viewport_width"], "viewport_height": row["viewport_height"],
        "user_agent": row["user_agent"],
        "metadata": json.loads(row["metadata_json"]),
    }


def _heartbeat(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "HEARTBEAT", "id": row["id"], "session_id": row["session_id"],
        "sequence": row["sequence"], "performance_ms": row.get("performance_ms"),
        "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"], "delta_ms": row["delta_ms"],
        "gap_level": row["gap_level"], "visibility_state": row["visibility_state"],
        "has_focus": bool(row["has_focus"]), "fullscreen": bool(row["fullscreen"]),
    }


def _marker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "MARKER", "id": row["id"], "session_id": row["session_id"],
        "label": row["label"], "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"],
    }


def _submission(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "SUBMISSION", "id": row["id"], "session_id": row["session_id"],
        "submission_number": row["submission_number"],
        "question_id": row["question_id"], "language": row["language"],
        "action": row["action"], "code_length": row["code_length"],
        "result": row["result"], "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"],
    }


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _milliseconds_between(first: str, second: str) -> float:
    return (_moment(second) - _moment(first)).total_seconds() * 1000


def _chronological(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # The server timestamp is authoritative across separate request streams.
    # Sequence is meaningful within a stream; ties across streams cannot prove
    # the order in which browser actions occurred.
    return sorted(
        items,
        key=lambda item: (
            _moment(item["timestamp_server"]),
            item.get("sequence") if item.get("sequence") is not None else -1,
            item.get("id", ""),
        ),
    )


def build_timeline(db: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    """Return all stored observations in chronological server receipt order."""
    row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("Session not found")
    session = dict(row)
    items = [
        {"kind": "SESSION", "event_type": "start", "timestamp_server": session["started_at"]},
        *(_event(item) for item in _rows(db, "events", session_id)),
        *(_heartbeat(item) for item in _rows(db, "heartbeats", session_id)),
        *(_marker(item) for item in _rows(db, "markers", session_id)),
        *(_submission(item) for item in _rows(db, "submissions", session_id)),
    ]
    if session["ended_at"]:
        items.append({"kind": "SESSION", "event_type": "end", "timestamp_server": session["ended_at"]})
    return _chronological(items)


def _editor_distribution(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"SMALL_CHANGE": 0, "MEDIUM_CHANGE": 0, "LARGE_CHANGE": 0}
    for event in events:
        if event["event_type"] != "editor_change":
            continue
        metadata = event["metadata"]
        size = metadata.get("change_size")
        if size not in counts:
            delta = abs(int(metadata.get("delta_length", 0)))
            size = "SMALL_CHANGE" if delta < 30 else "MEDIUM_CHANGE" if delta <= 150 else "LARGE_CHANGE"
        counts[size] += 1
    return counts


def _signal_state(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event["event_type"],
        "timestamp_server": event["timestamp_server"],
        "timestamp_client": event["timestamp_client"],
        "sequence": event.get("sequence"),
        "performance_ms": event.get("performance_ms"),
        "visibility_state": event["visibility_state"],
        "has_focus": event["document_has_focus"],
        "fullscreen": event["fullscreen"],
        "metadata": event["metadata"],
    }


def _marker_observation(
    marker: dict[str, Any],
    events: list[dict[str, Any]],
    heartbeats: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    when = marker["timestamp_server"]
    nearby_events = [
        event for event in events
        if abs(_milliseconds_between(when, event["timestamp_server"])) <= WINDOW_SECONDS * 1000
    ]
    nearby_heartbeats = [
        hb for hb in heartbeats
        if abs(_milliseconds_between(when, hb["timestamp_server"])) <= WINDOW_SECONDS * 1000
    ]
    relevant = [event for event in nearby_events if event["event_type"] in RELEVANT_EVENTS]
    anomalies = [hb for hb in nearby_heartbeats if hb["gap_level"] in {"WARNING", "LARGE GAP", "LARGE_GAP"}]
    signals = [_signal_state(event) for event in relevant]
    signals.extend({
        "event_type": "heartbeat_gap", "timestamp_server": hb["timestamp_server"],
        "delta_ms": hb["delta_ms"], "gap_level": hb["gap_level"],
        "visibility_state": hb["visibility_state"], "has_focus": hb["has_focus"],
        "fullscreen": hb["fullscreen"],
    } for hb in anomalies)
    signals = _chronological(signals)

    hidden = any(event["event_type"] == "visibilitychange" and event["visibility_state"] == "hidden" for event in relevant)
    blur = any(event["event_type"] == "blur" for event in relevant)
    fullscreen_exit = any(
        event["event_type"] == "fullscreenchange" and not event["fullscreen"]
        for event in relevant
    )
    network = any(event["event_type"] in {"online", "offline"} for event in relevant)
    fetch_failure = any(event["event_type"] == "fetch_failure" for event in relevant)
    max_interval = max((float(hb["delta_ms"]) for hb in nearby_heartbeats if hb["delta_ms"] is not None), default=None)
    visibility = [
        event["visibility_state"] for event in relevant
        if event["event_type"] == "visibilitychange"
    ]
    clipboard = [event["event_type"] for event in relevant if event["event_type"] in {"copy", "paste", "cut"}]
    latest_state: dict[str, Any] | None = None
    state_items = [
        {"timestamp_server": event["timestamp_server"], "visibility_state": event["visibility_state"],
         "has_focus": event["document_has_focus"], "fullscreen": event["fullscreen"]}
        for event in nearby_events
    ] + [
        {"timestamp_server": hb["timestamp_server"], "visibility_state": hb["visibility_state"],
         "has_focus": hb["has_focus"], "fullscreen": hb["fullscreen"]}
        for hb in nearby_heartbeats
    ]
    if state_items:
        latest_state = _chronological(state_items)[-1]
        latest_state = {key: latest_state[key] for key in ("visibility_state", "has_focus", "fullscreen")}
    observed = {
        "window_blur": blur,
        "document_hidden": hidden,
        "fullscreen_exit": fullscreen_exit,
        "heartbeat_gap_ms": max_interval,
        "heartbeat_anomaly": bool(anomalies),
        "network_change": network,
        "fetch_failure": fetch_failure,
        "clipboard_signal": bool(clipboard),
        "browser_state_snapshot": latest_state,
    }
    matrix_row = {
        "action": marker["label"], "marker_id": marker["id"],
        "window_blur": "observed" if blur else "not observed",
        "document_hidden": "observed" if hidden else "not observed",
        "fullscreen_exit": "observed" if fullscreen_exit else "not observed",
        "heartbeat_gap_ms": max_interval,
        "network_change": "observed" if network else "not observed",
        "fetch_failure": "observed" if fetch_failure else "not observed",
        # Retain the original API keys for existing report consumers.
        "visibilitychange": ", ".join(visibility) if visibility else "not observed",
        "blur": "observed" if blur else "not observed",
        "fullscreenchange": "observed" if any(event["event_type"] == "fullscreenchange" for event in relevant) else "not observed",
        "heartbeat_anomaly": ", ".join(hb["gap_level"] for hb in anomalies) if anomalies else "not observed",
        "clipboard_signal": ", ".join(clipboard) if clipboard else "not observed",
        "browser_observable": "listed signal observed" if relevant or anomalies else "no listed transition or anomaly observed in ±3 s",
    }
    correlation = {
        "marker": marker, "window_seconds": WINDOW_SECONDS,
        "signals": signals, "observed": observed,
        "heartbeat_intervals_ms": [hb["delta_ms"] for hb in nearby_heartbeats if hb["delta_ms"] is not None],
        "observation": "Browser transitions or anomalies observed in ±3 s." if signals else "No listed transition or heartbeat anomaly observed in ±3 s.",
    }
    return correlation, matrix_row


def analyze_session(db: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Summarize only stored events and manual markers from this session."""
    row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("Session not found")
    session = dict(row)
    events = [_event(item) for item in _rows(db, "events", session_id)]
    heartbeats = [_heartbeat(item) for item in _rows(db, "heartbeats", session_id)]
    markers = [_marker(item) for item in _rows(db, "markers", session_id)]
    submissions = [_submission(item) for item in _rows(db, "submissions", session_id)]
    counts = Counter(event["event_type"] for event in events)
    intervals = [float(hb["delta_ms"]) for hb in heartbeats if hb["delta_ms"] is not None]
    ended = session["ended_at"] or datetime.now().astimezone().isoformat(timespec="milliseconds")
    correlations = []
    matrix = []
    for marker in markers:
        correlation, matrix_row = _marker_observation(marker, events, heartbeats)
        correlations.append(correlation)
        matrix.append(matrix_row)
    editor_distribution = _editor_distribution(events)
    return {
        "session": session,
        "summary": {
            "total_duration_ms": max(0, round(_milliseconds_between(session["started_at"], ended))),
            "focus_loss_count": counts["blur"],
            "visibility_hidden_count": sum(
                event["event_type"] == "visibilitychange" and event["visibility_state"] == "hidden"
                for event in events
            ),
            "fullscreen_exit_count": sum(
                event["event_type"] == "fullscreenchange" and not event["fullscreen"]
                for event in events
            ),
            "fullscreen_error_count": counts["fullscreen_error"],
            "paste_count": counts["paste"],
            "network_change_count": counts["online"] + counts["offline"],
            "network_offline_count": counts["offline"],
            "fetch_failure_count": counts["fetch_failure"],
            "editor_change_count": counts["editor_change"],
            "editor_change_distribution": editor_distribution,
            "submission_count": sum(item["action"] == "submit" for item in submissions),
            "run_count": sum(item["action"] == "run" for item in submissions),
            "longest_heartbeat_gap_ms": max(intervals, default=None),
            "average_heartbeat_interval_ms": round(sum(intervals) / len(intervals), 1) if intervals else None,
            "marker_count": len(markers), "event_count": len(events),
            "heartbeat_count": len(heartbeats),
        },
        "event_counts": dict(sorted(counts.items())),
        "timeline": build_timeline(db, session_id),
        "heartbeat_points": heartbeats,
        "submissions": submissions,
        "correlations": correlations,
        "detection_matrix": matrix,
        "timeline_ordering_note": (
            "Timeline order uses server receipt timestamps. Browser performance time "
            "and event sequence provide finer within-page context; records with equal "
            "server timestamps from different streams have unresolved relative order."
        ),
        "limitations": (
            "Absence of a browser event does not imply absence of external activity. "
            "This simulation measures only signals accessible to the local browser page."
        ),
    }
