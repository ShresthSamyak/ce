"""Local-only assessment simulation API and frontend server."""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .analysis import analyze_session, build_timeline
from .database import PROJECT_ROOT, connection, initialize_database
from .models import EventIn, HeartbeatIn, MarkerIn, SessionEnd, SessionStart
from .report import render_report


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def get_session(db: sqlite3.Connection, session_id: UUID) -> dict:
    row = db.execute("SELECT * FROM sessions WHERE id = ?", (str(session_id),)).fetchone()
    if row is None:
        raise HTTPException(404, "Session not found")
    return dict(row)


def require_active(db: sqlite3.Connection, session_id: UUID) -> None:
    session = get_session(db, session_id)
    if session["ended_at"] is not None:
        raise HTTPException(409, "Session has ended")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="PROCTORING-LAB", version="1.0.0", lifespan=lifespan)
FRONTEND = PROJECT_ROOT / "frontend"


@app.middleware("http")
async def restrict_api_payload(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method == "POST":
        length = request.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > 8192):
            return JSONResponse({"detail": "Request body exceeds 8192 bytes"}, status_code=413)
        # Starlette caches this body for downstream parsing; the size check also
        # covers clients that omit Content-Length.
        if len(await request.body()) > 8192:
            return JSONResponse({"detail": "Request body exceeds 8192 bytes"}, status_code=413)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index():
    path = FRONTEND / "index.html"
    if not path.is_file():
        raise HTTPException(503, "Frontend has not been installed")
    return FileResponse(path)


app.mount("/static", StaticFiles(directory=str(FRONTEND), check_dir=False), name="static")


@app.get("/styles.css", include_in_schema=False)
def stylesheet():
    return FileResponse(FRONTEND / "styles.css", media_type="text/css")


@app.get("/monitor.js", include_in_schema=False)
def monitor_script():
    return FileResponse(FRONTEND / "monitor.js", media_type="text/javascript")


@app.post("/api/session/start", status_code=201)
def start_session(payload: SessionStart):
    session = {
        "id": str(payload.id),
        "started_at": utc_now(),
        "ended_at": None,
        "user_agent": payload.user_agent,
        "platform": payload.platform,
        "screen_width": payload.screen_width,
        "screen_height": payload.screen_height,
    }
    with connection() as db:
        try:
            db.execute(
                "INSERT INTO sessions VALUES (:id,:started_at,:ended_at,:user_agent,:platform,:screen_width,:screen_height)",
                session,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Session ID already exists") from exc
    return session


@app.post("/api/session/end")
def end_session(payload: SessionEnd):
    with connection() as db:
        session = get_session(db, payload.session_id)
        if session["ended_at"] is None:
            db.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (utc_now(), session["id"]))
    with connection() as db:
        return analyze_session(db, str(payload.session_id))


@app.post("/api/events", status_code=201)
def record_event(payload: EventIn):
    metadata = payload.metadata
    if payload.event_type == "keydown":
        allowed = {"keyCategory", "ctrl", "alt", "shift", "meta", "repeat"}
        if metadata.keys() - allowed:
            raise HTTPException(422, "Keydown metadata may contain only safe categories and modifiers")
        if "keyCategory" in metadata and metadata["keyCategory"] not in {
            "modifier", "navigation", "editing", "function", "character", "other"
        }:
            raise HTTPException(422, "Invalid key category")
        if any(type(metadata[key]) is not bool for key in ("ctrl", "alt", "shift", "meta", "repeat") if key in metadata):
            raise HTTPException(422, "Key modifiers must be booleans")
    elif payload.event_type in {"copy", "paste", "cut"}:
        if metadata.keys() - {"character_count"}:
            raise HTTPException(422, "Clipboard metadata may contain only character_count")
        count = metadata.get("character_count", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 10_000_000:
            raise HTTPException(422, "Invalid clipboard character count")
    elif metadata:
        # Browser state is stored in dedicated columns, not opaque telemetry.
        raise HTTPException(422, "Metadata is not accepted for this event type")
    event = {
        "event_id": str(payload.event_id),
        "session_id": str(payload.session_id),
        "event_type": payload.event_type,
        "timestamp_client": utc_text(payload.timestamp_client),
        "timestamp_server": utc_now(),
        "visibility_state": payload.visibility_state,
        "document_has_focus": payload.document_has_focus,
        "fullscreen": payload.fullscreen,
        "screen_width": payload.screen_width,
        "screen_height": payload.screen_height,
        "viewport_width": payload.viewport_width,
        "viewport_height": payload.viewport_height,
        "user_agent": payload.user_agent,
        "metadata": metadata,
    }
    with connection() as db:
        require_active(db, payload.session_id)
        try:
            db.execute(
                """INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["event_id"], event["session_id"], event["event_type"],
                    event["timestamp_client"], event["timestamp_server"],
                    event["visibility_state"], int(event["document_has_focus"]),
                    int(event["fullscreen"]), event["screen_width"], event["screen_height"],
                    event["viewport_width"], event["viewport_height"], event["user_agent"],
                    json.dumps(metadata, separators=(",", ":")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Event ID already exists") from exc
    return event


@app.post("/api/heartbeat", status_code=201)
def record_heartbeat(payload: HeartbeatIn):
    now = utc_now()
    heartbeat = {
        "id": str(uuid4()),
        "session_id": str(payload.session_id),
        "sequence": payload.sequence,
        "client_timestamp": utc_text(payload.client_timestamp),
        "server_timestamp": now,
        "delta_ms": None,
        "gap_level": "FIRST",
        "visibility_state": payload.visibility_state,
        "has_focus": payload.has_focus,
        "fullscreen": payload.fullscreen,
    }
    with connection() as db:
        require_active(db, payload.session_id)
        previous = db.execute(
            "SELECT server_timestamp FROM heartbeats WHERE session_id=? ORDER BY server_timestamp DESC, sequence DESC LIMIT 1",
            (heartbeat["session_id"],),
        ).fetchone()
        if previous:
            delta = (datetime.fromisoformat(now) - datetime.fromisoformat(previous["server_timestamp"])).total_seconds() * 1000
            heartbeat["delta_ms"] = max(0.0, round(delta, 1))
            heartbeat["gap_level"] = "NORMAL" if delta < 4000 else "WARNING" if delta <= 8000 else "LARGE GAP"
        try:
            db.execute(
                "INSERT INTO heartbeats VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    heartbeat["id"], heartbeat["session_id"], heartbeat["sequence"],
                    heartbeat["client_timestamp"], heartbeat["server_timestamp"],
                    heartbeat["delta_ms"], heartbeat["gap_level"], heartbeat["visibility_state"],
                    int(heartbeat["has_focus"]), int(heartbeat["fullscreen"]),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Heartbeat sequence already exists") from exc
    return heartbeat


@app.post("/api/marker", status_code=201)
def record_marker(payload: MarkerIn):
    marker = {
        "id": str(uuid4()),
        "session_id": str(payload.session_id),
        "label": payload.label,
        "timestamp_client": utc_text(payload.timestamp_client),
        "timestamp_server": utc_now(),
    }
    with connection() as db:
        require_active(db, payload.session_id)
        db.execute(
            "INSERT INTO markers VALUES (:id,:session_id,:label,:timestamp_client,:timestamp_server)", marker
        )
    return marker


@app.get("/api/session/{session_id}")
def read_session(session_id: UUID):
    with connection() as db:
        session = get_session(db, session_id)
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (str(session_id),)).fetchone()[0]
            for table in ("events", "heartbeats", "markers")
        }
    return {**session, "counts": counts}


@app.get("/api/session/{session_id}/timeline")
def read_timeline(session_id: UUID):
    with connection() as db:
        get_session(db, session_id)
        return {"session_id": str(session_id), "items": build_timeline(db, str(session_id))}


@app.get("/api/session/{session_id}/analysis")
def read_analysis(session_id: UUID):
    with connection() as db:
        get_session(db, session_id)
        return analyze_session(db, str(session_id))


@app.get("/api/session/{session_id}/report", response_class=HTMLResponse)
def read_report(session_id: UUID):
    with connection() as db:
        get_session(db, session_id)
        analysis = analyze_session(db, str(session_id))
    report_html = render_report(analysis)
    target = PROJECT_ROOT / "reports" / f"session_{session_id}.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_html, encoding="utf-8")
    return HTMLResponse(report_html)
