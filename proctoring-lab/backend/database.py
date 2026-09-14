"""Small SQLite storage layer for the local simulation."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "proctoring_lab.sqlite3"


def database_path() -> Path:
    """Allow tests to use an isolated database without changing production defaults."""
    return Path(os.environ.get("PROCTORING_LAB_DB", str(DEFAULT_DATABASE)))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    """Create only the tables used by this experiment."""
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                user_agent TEXT NOT NULL,
                platform TEXT NOT NULL,
                screen_width INTEGER NOT NULL,
                screen_height INTEGER NOT NULL,
                viewport_width INTEGER,
                viewport_height INTEGER,
                language TEXT,
                hardware_concurrency INTEGER,
                device_memory REAL,
                timezone TEXT,
                duration_minutes INTEGER NOT NULL DEFAULT 60
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                event_type TEXT NOT NULL,
                client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL,
                visibility_state TEXT NOT NULL,
                document_has_focus INTEGER NOT NULL,
                fullscreen INTEGER NOT NULL,
                screen_width INTEGER NOT NULL,
                screen_height INTEGER NOT NULL,
                viewport_width INTEGER NOT NULL,
                viewport_height INTEGER NOT NULL,
                user_agent TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                sequence INTEGER,
                performance_ms REAL
            );
            CREATE INDEX IF NOT EXISTS events_session_time ON events(session_id, server_timestamp);
            CREATE TABLE IF NOT EXISTS heartbeats (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                sequence INTEGER NOT NULL,
                client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL,
                delta_ms REAL,
                gap_level TEXT NOT NULL,
                visibility_state TEXT NOT NULL,
                has_focus INTEGER NOT NULL,
                fullscreen INTEGER NOT NULL,
                performance_ms REAL,
                UNIQUE(session_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS heartbeats_session_time ON heartbeats(session_id, server_timestamp);
            CREATE TABLE IF NOT EXISTS markers (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                label TEXT NOT NULL,
                client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS markers_session_time ON markers(session_id, server_timestamp);
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                submission_number INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                language TEXT NOT NULL,
                action TEXT NOT NULL,
                code_length INTEGER NOT NULL,
                result TEXT NOT NULL,
                client_timestamp TEXT NOT NULL,
                server_timestamp TEXT NOT NULL,
                UNIQUE(session_id, submission_number)
            );
            CREATE INDEX IF NOT EXISTS submissions_session_time ON submissions(session_id, server_timestamp);
            """
        )
        # Existing installations retain measured sessions and gain only the new columns.
        additions = {
            "sessions": {
                "viewport_width": "INTEGER", "viewport_height": "INTEGER",
                "language": "TEXT", "hardware_concurrency": "INTEGER",
                "device_memory": "REAL", "timezone": "TEXT",
                "duration_minutes": "INTEGER NOT NULL DEFAULT 60",
            },
            "events": {"sequence": "INTEGER", "performance_ms": "REAL"},
            "heartbeats": {"performance_ms": "REAL"},
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
