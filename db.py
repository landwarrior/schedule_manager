"""SQLite connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "schedule.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    member_count INTEGER NOT NULL DEFAULT 1,
    display_from TEXT NOT NULL DEFAULT '2026-01',
    display_to TEXT NOT NULL DEFAULT '2026-12',
    safety_rate REAL NOT NULL DEFAULT 80,
    theme TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS holidays (
    date TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS phase_totals (
    project_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    total_effort REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, phase),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS allocations (
    project_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    year_month TEXT NOT NULL,
    decade INTEGER NOT NULL CHECK (decade IN (1, 2, 3)),
    effort REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, phase, year_month, decade),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS test_t_period (
    project_id INTEGER PRIMARY KEY,
    start_ym TEXT,
    start_decade INTEGER CHECK (start_decade IS NULL OR start_decade IN (1, 2, 3)),
    end_ym TEXT,
    end_decade INTEGER CHECK (end_decade IS NULL OR end_decade IN (1, 2, 3)),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_settings_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()
    }
    if "safety_rate" not in columns:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN safety_rate REAL NOT NULL DEFAULT 80"
        )
    if "theme" not in columns:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'system'"
        )


def _ensure_project_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "test_t_mode" not in columns:
        conn.execute(
            "ALTER TABLE projects ADD COLUMN test_t_mode TEXT NOT NULL DEFAULT 'period'"
        )


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _ensure_settings_columns(conn)
        _ensure_project_columns(conn)
        row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO settings "
                "(id, member_count, display_from, display_to, safety_rate, theme) "
                "VALUES (1, 1, '2026-01', '2026-12', 80, 'system')"
            )
        conn.commit()
