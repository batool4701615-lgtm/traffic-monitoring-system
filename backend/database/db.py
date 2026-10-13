"""
Lightweight SQLite storage for completed monitoring sessions and their
count-over-time history. No ORM is used on purpose, to keep this
beginner-friendly and dependency-light -- just the standard library
sqlite3 module with plain SQL.
"""

import sqlite3
import threading
from contextlib import contextmanager

from backend.utils.config import DB_PATH

_lock = threading.Lock()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                video_name TEXT NOT NULL,
                total INTEGER NOT NULL,
                car INTEGER NOT NULL,
                bus INTEGER NOT NULL,
                truck INTEGER NOT NULL,
                motorcycle INTEGER NOT NULL,
                bicycle INTEGER NOT NULL,
                density TEXT NOT NULL,
                fps REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                suspected_duplicates INTEGER NOT NULL DEFAULT 0,
                missed_detections INTEGER,
                duplicate_detections INTEGER,
                notes TEXT,
                output_video TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS timeseries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                total INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
            """
        )


def save_session(record: dict) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO sessions
                (created_at, video_name, total, car, bus, truck, motorcycle,
                 bicycle, density, fps, duration_seconds, suspected_duplicates,
                 output_video)
            VALUES (:created_at, :video_name, :total, :car, :bus, :truck,
                    :motorcycle, :bicycle, :density, :fps, :duration_seconds,
                    :suspected_duplicates, :output_video)
            """,
            record,
        )
        return cur.lastrowid


def save_timeseries_point(session_id: int, timestamp: str, total: int):
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO timeseries (session_id, timestamp, total) VALUES (?, ?, ?)",
            (session_id, timestamp, total),
        )


def get_history() -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_session(session_id: int):
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def get_timeseries(session_id: int) -> list:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, total FROM timeseries WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_session(session_id: int, fields: dict):
    if not fields:
        return
    columns = ", ".join(f"{k} = :{k}" for k in fields)
    fields = dict(fields)
    fields["id"] = session_id
    with _lock, _connect() as conn:
        conn.execute(f"UPDATE sessions SET {columns} WHERE id = :id", fields)
