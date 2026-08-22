"""Data access helpers for the schedule manager."""

from __future__ import annotations

import sqlite3
from typing import Any

from calendar_util import (
    is_valid_effort,
    normalize_phase_color,
    normalize_phase_input_mode,
    round_effort,
)
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


def list_phase_definitions() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, input_mode, color, sort_order, legacy_key "
            "FROM phase_definitions ORDER BY sort_order, id"
        ).fetchall()
        return [_phase_row(row) for row in rows]


def get_phase_definition(phase_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, input_mode, color, sort_order, legacy_key "
            "FROM phase_definitions WHERE id = ?",
            (phase_id,),
        ).fetchone()
        return _phase_row(row) if row else None


def create_phase_definition(name: str, input_mode: str, color: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("工程名は必須です")
    input_mode = normalize_phase_input_mode(input_mode)
    color = normalize_phase_color(color)
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM phase_definitions"
        ).fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO phase_definitions (name, input_mode, color, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (name, input_mode, color, max_order + 1),
        )
        phase_id = int(cur.lastrowid)
        _attach_phase_to_all_projects(conn, phase_id, max_order + 1)
        conn.commit()
        return phase_id


def update_phase_definition(
    phase_id: int,
    name: str,
    input_mode: str,
    color: str,
    sort_order: int,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("工程名は必須です")
    input_mode = normalize_phase_input_mode(input_mode)
    color = normalize_phase_color(color)
    with get_connection() as conn:
        prev = conn.execute(
            "SELECT input_mode FROM phase_definitions WHERE id = ?", (phase_id,)
        ).fetchone()
        if prev is None:
            raise ValueError("工程が見つかりません")
        conn.execute(
            "UPDATE phase_definitions SET name = ?, input_mode = ?, color = ?, sort_order = ? "
            "WHERE id = ?",
            (name, input_mode, color, sort_order, phase_id),
        )
        if prev["input_mode"] != input_mode:
            _sync_project_phase_mode(conn, phase_id, input_mode)
        conn.commit()


def delete_phase_definition(phase_id: int) -> None:
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM phase_definitions").fetchone()["c"]
        if count <= 1:
            raise ValueError("工程は最低1つ必要です")
        conn.execute("DELETE FROM phase_definitions WHERE id = ?", (phase_id,))
        conn.commit()


def _attach_phase_to_all_projects(
    conn: sqlite3.Connection, phase_id: int, sort_order: int
) -> None:
    projects = conn.execute("SELECT id FROM projects").fetchall()
    for project in projects:
        conn.execute(
            "INSERT OR IGNORE INTO project_phases "
            "(project_id, phase_id, sort_order, enabled, total_effort) VALUES (?, ?, ?, 0, 0)",
            (project["id"], phase_id, sort_order),
        )


def _sync_project_phase_mode(
    conn: sqlite3.Connection, phase_id: int, input_mode: str
) -> None:
    if input_mode == "period":
        conn.execute(
            "UPDATE project_phases SET total_effort = 0 WHERE phase_id = ?", (phase_id,)
        )
        conn.execute("DELETE FROM allocations WHERE phase_id = ?", (phase_id,))
    else:
        conn.execute(
            "UPDATE project_phases SET start_ym = NULL, start_decade = NULL, "
            "end_ym = NULL, end_decade = NULL WHERE phase_id = ?",
            (phase_id,),
        )


def _phase_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "input_mode": normalize_phase_input_mode(row["input_mode"]),
        "color": normalize_phase_color(row["color"]),
        "sort_order": row["sort_order"],
        "legacy_key": row["legacy_key"],
    }


def _load_project_phases(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            pp.project_id,
            pp.phase_id,
            pp.sort_order,
            pp.enabled,
            pp.total_effort,
            pp.start_ym,
            pp.start_decade,
            pp.end_ym,
            pp.end_decade,
            pd.name,
            pd.input_mode,
            pd.color
        FROM project_phases pp
        JOIN phase_definitions pd ON pd.id = pp.phase_id
        WHERE pp.project_id = ?
        ORDER BY pp.sort_order, pp.phase_id
        """,
        (project_id,),
    ).fetchall()
    phases: list[dict[str, Any]] = []
    for row in rows:
        phases.append(
            {
                "phase_id": row["phase_id"],
                "sort_order": row["sort_order"],
                "enabled": bool(row["enabled"]),
                "total_effort": row["total_effort"],
                "start_ym": row["start_ym"],
                "start_decade": row["start_decade"],
                "end_ym": row["end_ym"],
                "end_decade": row["end_decade"],
                "name": row["name"],
                "input_mode": normalize_phase_input_mode(row["input_mode"]),
                "color": normalize_phase_color(row["color"]),
            }
        )
    return phases


def list_projects() -> list[dict[str, Any]]:
    with get_connection() as conn:
        projects = conn.execute(
            "SELECT id, name, sort_order FROM projects ORDER BY sort_order, id"
        ).fetchall()
        return [
            {
                "id": project["id"],
                "name": project["name"],
                "sort_order": project["sort_order"],
                "phases": _load_project_phases(conn, project["id"]),
            }
            for project in projects
        ]


def get_project(project_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        project = conn.execute(
            "SELECT id, name, sort_order FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            return None
        return {
            "id": project["id"],
            "name": project["name"],
            "sort_order": project["sort_order"],
            "phases": _load_project_phases(conn, project_id),
        }


def _init_project_phases(conn: sqlite3.Connection, project_id: int) -> None:
    phase_defs = conn.execute(
        "SELECT id, sort_order FROM phase_definitions ORDER BY sort_order, id"
    ).fetchall()
    for phase_def in phase_defs:
        conn.execute(
            "INSERT INTO project_phases "
            "(project_id, phase_id, sort_order, enabled, total_effort) VALUES (?, ?, ?, 1, 0)",
            (project_id, phase_def["id"], phase_def["sort_order"]),
        )


def create_project(name: str, phase_configs: list[dict[str, Any]]) -> int:
    with get_connection() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM projects"
        ).fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO projects (name, sort_order) VALUES (?, ?)",
            (name.strip(), max_order + 1),
        )
        project_id = int(cur.lastrowid)
        _init_project_phases(conn, project_id)
        _save_project_phases(conn, project_id, phase_configs)
        conn.commit()
        return project_id


def update_project(
    project_id: int, name: str, phase_configs: list[dict[str, Any]]
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?",
            (name.strip(), project_id),
        )
        _save_project_phases(conn, project_id, phase_configs)
        conn.commit()


def _save_project_phases(
    conn: sqlite3.Connection, project_id: int, phase_configs: list[dict[str, Any]]
) -> None:
    phase_defs = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, input_mode FROM phase_definitions"
        ).fetchall()
    }
    for index, config in enumerate(phase_configs):
        phase_id = int(config["phase_id"])
        phase_def = phase_defs.get(phase_id)
        if phase_def is None:
            raise ValueError("工程が不正です")
        input_mode = normalize_phase_input_mode(phase_def["input_mode"])
        total_effort = 0.0
        start_ym = start_decade = end_ym = end_decade = None
        enabled = 1 if config.get("enabled", True) else 0
        if input_mode == "effort":
            total_effort = round_effort(float(config.get("total_effort", 0) or 0))
        else:
            start_ym = config.get("start_ym") or None
            end_ym = config.get("end_ym") or None
            start_decade = config.get("start_decade")
            end_decade = config.get("end_decade")
            start_decade = int(start_decade) if start_decade else None
            end_decade = int(end_decade) if end_decade else None
        conn.execute(
            "UPDATE project_phases SET sort_order = ?, enabled = ?, total_effort = ?, "
            "start_ym = ?, start_decade = ?, end_ym = ?, end_decade = ? "
            "WHERE project_id = ? AND phase_id = ?",
            (
                index,
                enabled,
                total_effort,
                start_ym,
                start_decade,
                end_ym,
                end_decade,
                project_id,
                phase_id,
            ),
        )


def delete_project(project_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()


def list_allocations(
    from_ym: str, to_ym: str
) -> dict[tuple[int, int, str, int], float]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.project_id, a.phase_id, a.year_month, a.decade, a.effort, pd.input_mode
            FROM allocations a
            JOIN phase_definitions pd ON pd.id = a.phase_id
            JOIN project_phases pp
              ON pp.project_id = a.project_id
             AND pp.phase_id = a.phase_id
             AND pp.enabled = 1
            WHERE a.year_month >= ? AND a.year_month <= ? AND pd.input_mode = 'effort'
            """,
            (from_ym, to_ym),
        ).fetchall()
        return {
            (row["project_id"], row["phase_id"], row["year_month"], row["decade"]): row[
                "effort"
            ]
            for row in rows
        }


def set_allocation(
    project_id: int, phase_id: int, year_month: str, decade: int, effort: float
) -> None:
    if decade not in (1, 2, 3):
        raise ValueError("invalid decade")
    effort = round_effort(effort)
    if not is_valid_effort(effort):
        raise ValueError("effort must be in 0.1 increments")
    with get_connection() as conn:
        phase = conn.execute(
            "SELECT id, input_mode FROM phase_definitions WHERE id = ?",
            (phase_id,),
        ).fetchone()
        if phase is None or phase["input_mode"] != "effort":
            raise ValueError("invalid phase")
        linked = conn.execute(
            "SELECT enabled FROM project_phases WHERE project_id = ? AND phase_id = ?",
            (project_id, phase_id),
        ).fetchone()
        if linked is None or not linked["enabled"]:
            raise ValueError("invalid phase")
        if effort == 0:
            conn.execute(
                "DELETE FROM allocations "
                "WHERE project_id = ? AND phase_id = ? AND year_month = ? AND decade = ?",
                (project_id, phase_id, year_month, decade),
            )
        else:
            conn.execute(
                "INSERT INTO allocations (project_id, phase_id, year_month, decade, effort) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, phase_id, year_month, decade) "
                "DO UPDATE SET effort = excluded.effort",
                (project_id, phase_id, year_month, decade, effort),
            )
        conn.commit()


def allocated_totals_by_project_phase() -> dict[tuple[int, int], float]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.project_id, a.phase_id, COALESCE(SUM(a.effort), 0) AS total
            FROM allocations a
            JOIN phase_definitions pd ON pd.id = a.phase_id
            JOIN project_phases pp
              ON pp.project_id = a.project_id
             AND pp.phase_id = a.phase_id
             AND pp.enabled = 1
            WHERE pd.input_mode = 'effort'
            GROUP BY a.project_id, a.phase_id
            """
        ).fetchall()
        return {(row["project_id"], row["phase_id"]): row["total"] for row in rows}


def phase_input_mode_label(mode: str) -> str:
    if mode == "period":
        return "期間のみ"
    return "工数入力"
