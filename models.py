"""Data access helpers for the schedule manager."""

from __future__ import annotations

import sqlite3
from typing import Any

from calendar_util import PHASE_KEYS, is_valid_effort, round_effort
from db import get_connection


def get_settings() -> sqlite3.Row:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()


def update_settings(
    member_count: int,
    display_from: str,
    display_to: str,
    safety_rate: float,
    theme: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET member_count = ?, display_from = ?, display_to = ?, "
            "safety_rate = ?, theme = ? WHERE id = 1",
            (member_count, display_from, display_to, safety_rate, theme),
        )
        conn.commit()


def update_theme(theme: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE settings SET theme = ? WHERE id = 1", (theme,))
        conn.commit()


def list_holidays() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute("SELECT date, name FROM holidays ORDER BY date").fetchall()
        )


def list_holiday_dates() -> list[str]:
    return [row["date"] for row in list_holidays()]


def add_holiday(date_str: str, name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO holidays (date, name) VALUES (?, ?)",
            (date_str, name.strip()),
        )
        conn.commit()


def delete_holiday(date_str: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM holidays WHERE date = ?", (date_str,))
        conn.commit()


def list_projects() -> list[dict[str, Any]]:
    with get_connection() as conn:
        projects = conn.execute(
            "SELECT id, name, sort_order FROM projects ORDER BY sort_order, id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for project in projects:
            totals = {
                row["phase"]: row["total_effort"]
                for row in conn.execute(
                    "SELECT phase, total_effort FROM phase_totals WHERE project_id = ?",
                    (project["id"],),
                )
            }
            test_t = conn.execute(
                "SELECT start_ym, start_decade, end_ym, end_decade "
                "FROM test_t_period WHERE project_id = ?",
                (project["id"],),
            ).fetchone()
            item = dict(project)
            item["totals"] = {key: totals.get(key, 0.0) for key in PHASE_KEYS}
            item["test_t"] = dict(test_t) if test_t else {
                "start_ym": None,
                "start_decade": None,
                "end_ym": None,
                "end_decade": None,
            }
            result.append(item)
        return result


def get_project(project_id: int) -> dict[str, Any] | None:
    projects = list_projects()
    for project in projects:
        if project["id"] == project_id:
            return project
    return None


def create_project(
    name: str,
    totals: dict[str, float],
    test_t: dict[str, Any],
) -> int:
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM projects"
        ).fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO projects (name, sort_order) VALUES (?, ?)",
            (name.strip(), max_order + 1),
        )
        project_id = int(cur.lastrowid)
        _upsert_phase_totals(conn, project_id, totals)
        _upsert_test_t(conn, project_id, test_t)
        conn.commit()
        return project_id


def update_project(
    project_id: int,
    name: str,
    totals: dict[str, float],
    test_t: dict[str, Any],
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?",
            (name.strip(), project_id),
        )
        _upsert_phase_totals(conn, project_id, totals)
        _upsert_test_t(conn, project_id, test_t)
        conn.commit()


def delete_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()


def _upsert_phase_totals(
    conn: sqlite3.Connection, project_id: int, totals: dict[str, float]
) -> None:
    for phase in PHASE_KEYS:
        effort = round_effort(float(totals.get(phase, 0) or 0))
        conn.execute(
            "INSERT INTO phase_totals (project_id, phase, total_effort) VALUES (?, ?, ?) "
            "ON CONFLICT(project_id, phase) DO UPDATE SET total_effort = excluded.total_effort",
            (project_id, phase, effort),
        )


def _upsert_test_t(
    conn: sqlite3.Connection, project_id: int, test_t: dict[str, Any]
) -> None:
    start_ym = test_t.get("start_ym") or None
    end_ym = test_t.get("end_ym") or None
    start_decade = test_t.get("start_decade")
    end_decade = test_t.get("end_decade")
    start_decade = int(start_decade) if start_decade else None
    end_decade = int(end_decade) if end_decade else None
    conn.execute(
        "INSERT INTO test_t_period "
        "(project_id, start_ym, start_decade, end_ym, end_decade) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(project_id) DO UPDATE SET "
        "start_ym = excluded.start_ym, start_decade = excluded.start_decade, "
        "end_ym = excluded.end_ym, end_decade = excluded.end_decade",
        (project_id, start_ym, start_decade, end_ym, end_decade),
    )


def list_allocations(
    from_ym: str, to_ym: str
) -> dict[tuple[int, str, str, int], float]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT project_id, phase, year_month, decade, effort "
            "FROM allocations WHERE year_month >= ? AND year_month <= ?",
            (from_ym, to_ym),
        ).fetchall()
        return {
            (row["project_id"], row["phase"], row["year_month"], row["decade"]): row[
                "effort"
            ]
            for row in rows
        }


def set_allocation(
    project_id: int, phase: str, year_month: str, decade: int, effort: float
) -> None:
    if phase not in PHASE_KEYS:
        raise ValueError("invalid phase")
    if decade not in (1, 2, 3):
        raise ValueError("invalid decade")
    effort = round_effort(effort)
    if not is_valid_effort(effort):
        raise ValueError("effort must be in 0.1 increments")
    with get_connection() as conn:
        if effort == 0:
            conn.execute(
                "DELETE FROM allocations "
                "WHERE project_id = ? AND phase = ? AND year_month = ? AND decade = ?",
                (project_id, phase, year_month, decade),
            )
        else:
            conn.execute(
                "INSERT INTO allocations (project_id, phase, year_month, decade, effort) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, phase, year_month, decade) "
                "DO UPDATE SET effort = excluded.effort",
                (project_id, phase, year_month, decade, effort),
            )
        conn.commit()


def allocated_totals_by_project_phase() -> dict[tuple[int, str], float]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT project_id, phase, COALESCE(SUM(effort), 0) AS total "
            "FROM allocations GROUP BY project_id, phase"
        ).fetchall()
        return {(row["project_id"], row["phase"]): row["total"] for row in rows}
