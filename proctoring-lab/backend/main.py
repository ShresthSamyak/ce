"""Local-only assessment simulation API and frontend server."""

from __future__ import annotations

import json
import sqlite3
import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .analysis import analyze_session, build_timeline
from .database import PROJECT_ROOT, connection, initialize_database
from .models import EventIn, HeartbeatIn, MarkerIn, SessionEnd, SessionStart, SubmissionIn
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    path = FRONTEND / "favicon.svg"
    if not path.is_file():
        return Response(status_code=204)
    return FileResponse(path, media_type="image/svg+xml")


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
        "viewport_width": payload.viewport_width,
        "viewport_height": payload.viewport_height,
        "language": payload.language,
        "hardware_concurrency": payload.hardware_concurrency,
        "device_memory": payload.device_memory,
        "timezone": payload.timezone,
        "duration_minutes": payload.duration_minutes,
    }
    with connection() as db:
        try:
            db.execute(
                """INSERT INTO sessions
                (id,started_at,ended_at,user_agent,platform,screen_width,screen_height,
                viewport_width,viewport_height,language,hardware_concurrency,device_memory,timezone,duration_minutes)
                VALUES (:id,:started_at,:ended_at,:user_agent,:platform,:screen_width,:screen_height,
                :viewport_width,:viewport_height,:language,:hardware_concurrency,:device_memory,:timezone,:duration_minutes)""",
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
    elif payload.event_type == "editor_change":
        if metadata.keys() != {"old_length", "new_length", "delta_length", "change_size"}:
            raise HTTPException(422, "Editor metadata must contain only length changes and classification")
        old, new, delta = (metadata[name] for name in ("old_length", "new_length", "delta_length"))
        if any(type(value) is not int for value in (old, new, delta)) or not (0 <= old <= 1_000_000 and 0 <= new <= 1_000_000) or delta != new - old:
            raise HTTPException(422, "Invalid editor length change")
        expected = "SMALL_CHANGE" if abs(delta) < 30 else "MEDIUM_CHANGE" if abs(delta) <= 150 else "LARGE_CHANGE"
        if metadata["change_size"] != expected:
            raise HTTPException(422, "Invalid editor change classification")
    elif payload.event_type == "fetch_failure":
        operation = metadata.get("operation")
        if metadata.keys() != {"operation"} or not isinstance(operation, str) or len(operation) > 50 or not operation.replace("_", "").isalnum():
            raise HTTPException(422, "Fetch failure metadata may contain only a short operation label")
    elif metadata:
        # Browser state is stored in dedicated columns, not opaque telemetry.
        raise HTTPException(422, "Metadata is not accepted for this event type")
    event = {
        "event_id": str(payload.event_id),
        "session_id": str(payload.session_id),
        "event_type": payload.event_type,
        "sequence": payload.sequence,
        "performance_ms": payload.performance_ms,
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
                """INSERT INTO events
                (id,session_id,event_type,client_timestamp,server_timestamp,visibility_state,
                document_has_focus,fullscreen,screen_width,screen_height,viewport_width,
                viewport_height,user_agent,metadata_json,sequence,performance_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["event_id"], event["session_id"], event["event_type"],
                    event["timestamp_client"], event["timestamp_server"],
                    event["visibility_state"], int(event["document_has_focus"]),
                    int(event["fullscreen"]), event["screen_width"], event["screen_height"],
                    event["viewport_width"], event["viewport_height"], event["user_agent"],
                    json.dumps(metadata, separators=(",", ":")),
                    event["sequence"], event["performance_ms"],
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
        "performance_ms": payload.performance_ms,
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
                """INSERT INTO heartbeats
                (id,session_id,sequence,client_timestamp,server_timestamp,delta_ms,gap_level,
                visibility_state,has_focus,fullscreen,performance_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    heartbeat["id"], heartbeat["session_id"], heartbeat["sequence"],
                    heartbeat["client_timestamp"], heartbeat["server_timestamp"],
                    heartbeat["delta_ms"], heartbeat["gap_level"], heartbeat["visibility_state"],
                    int(heartbeat["has_focus"]), int(heartbeat["fullscreen"]),
                    heartbeat["performance_ms"],
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


MOCK_RESULTS = (
    "Wrong Answer", "Accepted", "Compilation Error", "Runtime Error", "Time Limit Exceeded"
)
MOCK_NOTE = "Mock result only; source code was not evaluated."


@app.post("/api/submission", status_code=201)
def record_submission(payload: SubmissionIn):
    """Record a simulated judge result without receiving source or input contents."""
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        require_active(db, payload.session_id)
        number = db.execute(
            "SELECT COALESCE(MAX(submission_number), 0) + 1 FROM submissions WHERE session_id=?",
            (str(payload.session_id),),
        ).fetchone()[0]
        submission = {
            "id": str(uuid4()), "session_id": str(payload.session_id),
            "submission_number": number, "question_id": payload.question_id,
            "language": payload.language, "action": payload.action,
            "code_length": payload.code_length,
            "result": MOCK_RESULTS[(number - 1) % len(MOCK_RESULTS)],
            "timestamp_client": utc_text(payload.timestamp_client),
            "timestamp_server": utc_now(),
        }
        db.execute(
            """INSERT INTO submissions
            (id,session_id,submission_number,question_id,language,action,code_length,
            result,client_timestamp,server_timestamp)
            VALUES (:id,:session_id,:submission_number,:question_id,:language,:action,
            :code_length,:result,:timestamp_client,:timestamp_server)""",
            submission,
        )
    return {**submission, "mocked": True, "evaluation_note": MOCK_NOTE}


@app.get("/api/session/{session_id}/submissions")
def read_submissions(session_id: UUID):
    with connection() as db:
        get_session(db, session_id)
        items = [dict(row) for row in db.execute(
            "SELECT * FROM submissions WHERE session_id=? ORDER BY submission_number",
            (str(session_id),),
        )]
    return {"session_id": str(session_id), "items": [{**item, "mocked": True} for item in items]}


@app.get("/api/session/{session_id}")
def read_session(session_id: UUID):
    with connection() as db:
        session = get_session(db, session_id)
        counts = {
            table: db.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (str(session_id),)).fetchone()[0]
            for table in ("events", "heartbeats", "markers", "submissions")
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


def _export_rows(db: sqlite3.Connection, session_id: UUID) -> tuple[dict, dict[str, list[dict]]]:
    session = get_session(db, session_id)
    tables = {}
    for table in ("events", "heartbeats", "markers", "submissions"):
        tables[table] = [dict(row) for row in db.execute(
            f"SELECT * FROM {table} WHERE session_id=? ORDER BY server_timestamp, rowid",
            (str(session_id),),
        )]
    return session, tables


@app.get("/api/session/{session_id}/export/json")
def export_json(session_id: UUID):
    with connection() as db:
        session, tables = _export_rows(db, session_id)
    for event in tables["events"]:
        event["metadata"] = json.loads(event.pop("metadata_json"))
    filename = f"session_{session_id}_events.json"
    return Response(
        json.dumps({"session": session, **tables}, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _csv_safe(value: object) -> object:
    """Prevent untrusted labels or environment strings becoming spreadsheet formulas."""
    if value is None:
        return ""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@app.get("/api/session/{session_id}/export/csv")
def export_csv(session_id: UUID):
    with connection() as db:
        _, tables = _export_rows(db, session_id)
    output = io.StringIO(newline="")
    columns = (
        "kind", "id", "session_id", "event_type", "sequence", "timestamp_client",
        "timestamp_server", "performance_ms", "visibility_state", "has_focus",
        "fullscreen", "metadata",
    )
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    rows: list[dict] = []
    for event in tables["events"]:
        rows.append({
            "kind": "EVENT", "id": event["id"], "session_id": event["session_id"],
            "event_type": event["event_type"], "sequence": event["sequence"],
            "timestamp_client": event["client_timestamp"], "timestamp_server": event["server_timestamp"],
            "performance_ms": event["performance_ms"], "visibility_state": event["visibility_state"],
            "has_focus": bool(event["document_has_focus"]), "fullscreen": bool(event["fullscreen"]),
            "metadata": event["metadata_json"],
        })
    for heartbeat in tables["heartbeats"]:
        rows.append({
            "kind": "HEARTBEAT", "id": heartbeat["id"], "session_id": heartbeat["session_id"],
            "event_type": "heartbeat", "sequence": heartbeat["sequence"],
            "timestamp_client": heartbeat["client_timestamp"], "timestamp_server": heartbeat["server_timestamp"],
            "performance_ms": heartbeat["performance_ms"], "visibility_state": heartbeat["visibility_state"],
            "has_focus": bool(heartbeat["has_focus"]), "fullscreen": bool(heartbeat["fullscreen"]),
            "metadata": json.dumps({"delta_ms": heartbeat["delta_ms"], "gap_level": heartbeat["gap_level"]}),
        })
    for marker in tables["markers"]:
        rows.append({
            "kind": "MARKER", "id": marker["id"], "session_id": marker["session_id"],
            "event_type": "marker", "timestamp_client": marker["client_timestamp"],
            "timestamp_server": marker["server_timestamp"], "metadata": json.dumps({"label": marker["label"]}),
        })
    for submission in tables["submissions"]:
        rows.append({
            "kind": "SUBMISSION", "id": submission["id"], "session_id": submission["session_id"],
            "event_type": submission["action"], "sequence": submission["submission_number"],
            "timestamp_client": submission["client_timestamp"],
            "timestamp_server": submission["server_timestamp"],
            "metadata": json.dumps({key: submission[key] for key in ("question_id", "language", "code_length", "result")}),
        })
    for row in sorted(rows, key=lambda item: (item["timestamp_server"], item["kind"], item["id"])):
        writer.writerow({column: _csv_safe(row.get(column)) for column in columns})
    filename = f"session_{session_id}_events.csv"
    return Response(
        output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
