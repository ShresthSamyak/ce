"""Analysis of observed local browser signals; no unmeasured VM claims."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime


def _rows(db: sqlite3.Connection, table: str, session_id: str) -> list[dict]:
    # table is a private constant selected only by calls in this module.
    return [dict(row) for row in db.execute(
        f"SELECT * FROM {table} WHERE session_id=? ORDER BY server_timestamp, rowid", (session_id,)
    )]


def _event(row: dict) -> dict:
    return {
        "kind": "EVENT", "id": row["id"], "event_id": row["id"],
        "session_id": row["session_id"], "event_type": row["event_type"],
        "timestamp_client": row["client_timestamp"], "timestamp_server": row["server_timestamp"],
        "visibility_state": row["visibility_state"],
        "document_has_focus": bool(row["document_has_focus"]),
        "fullscreen": bool(row["fullscreen"]),
        "screen_width": row["screen_width"], "screen_height": row["screen_height"],
        "viewport_width": row["viewport_width"], "viewport_height": row["viewport_height"],
        "user_agent": row["user_agent"], "metadata": json.loads(row["metadata_json"]),
    }


def _heartbeat(row: dict) -> dict:
    return {
        "kind": "HEARTBEAT", "id": row["id"], "session_id": row["session_id"],
        "sequence": row["sequence"], "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"], "delta_ms": row["delta_ms"],
        "gap_level": row["gap_level"], "visibility_state": row["visibility_state"],
        "has_focus": bool(row["has_focus"]), "fullscreen": bool(row["fullscreen"]),
    }


def _marker(row: dict) -> dict:
    return {
        "kind": "MARKER", "id": row["id"], "session_id": row["session_id"],
        "label": row["label"], "timestamp_client": row["client_timestamp"],
        "timestamp_server": row["server_timestamp"],
    }


def build_timeline(db: sqlite3.Connection, session_id: str) -> list[dict]:
    """Chronological timeline using server receive times for cross-record ordering."""
    session = dict(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
    items = [
        {"kind": "SESSION", "event_type": "start", "timestamp_server": session["started_at"]},
        *(_event(row) for row in _rows(db, "events", session_id)),
        *(_heartbeat(row) for row in _rows(db, "heartbeats", session_id)),
        *(_marker(row) for row in _rows(db, "markers", session_id)),
    ]
    if session["ended_at"]:
        items.append({"kind": "SESSION", "event_type": "end", "timestamp_server": session["ended_at"]})
    return sorted(items, key=lambda item: item["timestamp_server"])


def _milliseconds_between(first: str, second: str) -> float:
    return (datetime.fromisoformat(second) - datetime.fromisoformat(first)).total_seconds() * 1000


def analyze_session(db: sqlite3.Connection, session_id: str) -> dict:
    """Compute only signals stored for this session, including ±3 s marker windows."""
    session = dict(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
    events = [_event(row) for row in _rows(db, "events", session_id)]
    heartbeats = [_heartbeat(row) for row in _rows(db, "heartbeats", session_id)]
    markers = [_marker(row) for row in _rows(db, "markers", session_id)]
    timeline = build_timeline(db, session_id)
    intervals = [float(hb["delta_ms"]) for hb in heartbeats if hb["delta_ms"] is not None]
    counts = Counter(event["event_type"] for event in events)
    ended = session["ended_at"] or datetime.now().astimezone().isoformat(timespec="milliseconds")

    correlations = []
    matrix = []
    for marker in markers:
        marker_time = marker["timestamp_server"]
        nearby_events = [event for event in events if abs(_milliseconds_between(marker_time, event["timestamp_server"])) <= 3000]
        nearby_heartbeats = [hb for hb in heartbeats if abs(_milliseconds_between(marker_time, hb["timestamp_server"])) <= 3000]
        anomalies = [hb for hb in nearby_heartbeats if hb["gap_level"] in {"WARNING", "LARGE GAP"}]
        signals = [
            {"event_type": event["event_type"], "timestamp_server": event["timestamp_server"],
             "visibility_state": event["visibility_state"], "fullscreen": event["fullscreen"],
             "metadata": event["metadata"]}
            for event in nearby_events
        ]
        signals.extend({
            "event_type": "heartbeat_gap", "timestamp_server": hb["timestamp_server"],
            "delta_ms": hb["delta_ms"], "gap_level": hb["gap_level"]
        } for hb in anomalies)
        visibility = [event["visibility_state"] for event in nearby_events if event["event_type"] == "visibilitychange"]
        fullscreen = [event for event in nearby_events if event["event_type"] == "fullscreenchange"]
        clipboard = [event["event_type"] for event in nearby_events if event["event_type"] in {"copy", "paste", "cut"}]
        relevant_events = [event for event in nearby_events if event["event_type"] in {
            "visibilitychange", "blur", "fullscreenchange", "copy", "paste", "cut"
        }]
        matrix_row = {
            "action": marker["label"], "marker_id": marker["id"],
            "visibilitychange": ", ".join(visibility) if visibility else "not observed",
            "blur": "observed" if any(event["event_type"] == "blur" for event in nearby_events) else "not observed",
            "fullscreenchange": "observed" if fullscreen else "not observed",
            "heartbeat_anomaly": ", ".join(hb["gap_level"] for hb in anomalies) if anomalies else "not observed",
            "clipboard_signal": ", ".join(clipboard) if clipboard else "not observed",
            "browser_observable": "listed signal observed" if relevant_events or anomalies else "no listed signal observed in ±3 s",
        }
        correlations.append({
            "marker": marker, "window_seconds": 3,
            "signals": sorted(signals, key=lambda item: item["timestamp_server"]),
            "observation": "Browser signals observed in ±3 s." if signals else "No listed browser signal observed in ±3 s."
        })
        matrix.append(matrix_row)

    return {
        "session": session,
        "summary": {
            "total_duration_ms": max(0, round(_milliseconds_between(session["started_at"], ended))),
            "focus_loss_count": counts["blur"],
            "visibility_hidden_count": sum(event["event_type"] == "visibilitychange" and event["visibility_state"] == "hidden" for event in events),
            "fullscreen_exit_count": sum(event["event_type"] == "fullscreenchange" and not event["fullscreen"] for event in events),
            "paste_count": counts["paste"],
            "longest_heartbeat_gap_ms": max(intervals, default=None),
            "average_heartbeat_interval_ms": round(sum(intervals) / len(intervals), 1) if intervals else None,
            "marker_count": len(markers),
            "event_count": len(events), "heartbeat_count": len(heartbeats),
        },
        "event_counts": dict(sorted(counts.items())),
        "timeline": timeline,
        "heartbeat_points": heartbeats,
        "correlations": correlations,
        "detection_matrix": matrix,
        "limitations": "Absence of a browser event does not imply absence of external activity. This simulation measures only signals accessible to the local browser page.",
    }
