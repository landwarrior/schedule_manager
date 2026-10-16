"""SQLite 接続とスキーマ初期化."""

from __future__ import annotations

import sqlite3

from calendar_util import DEFAULT_PHASES
from paths import data_dir

DB_PATH = data_dir() / "schedule.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    contract_name TEXT NOT NULL DEFAULT '',
    member_count INTEGER NOT NULL DEFAULT 1,
    display_from TEXT NOT NULL DEFAULT '2026-01',
    display_to TEXT NOT NULL DEFAULT '2026-12',
    planned_utilization REAL NOT NULL DEFAULT 80,
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

CREATE TABLE IF NOT EXISTS phase_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    input_mode TEXT NOT NULL DEFAULT 'effort' CHECK (input_mode IN ('period', 'effort')),
    color TEXT NOT NULL DEFAULT 'cyan' CHECK (color IN ('cyan', 'orange', 'green', 'lavender')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    legacy_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS project_phases (
    project_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    input_mode TEXT NOT NULL DEFAULT 'effort' CHECK (input_mode IN ('period', 'effort')),
    total_effort REAL NOT NULL DEFAULT 0,
    start_ym TEXT,
    start_decade INTEGER CHECK (start_decade IS NULL OR start_decade IN (1, 2, 3)),
    end_ym TEXT,
    end_decade INTEGER CHECK (end_decade IS NULL OR end_decade IN (1, 2, 3)),
    PRIMARY KEY (project_id, phase_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS allocations (
    project_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    year_month TEXT NOT NULL,
    decade INTEGER NOT NULL CHECK (decade IN (1, 2, 3)),
    effort REAL NOT NULL DEFAULT 0,
    actual_effort REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, phase_id, year_month, decade),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
);
"""


def get_connection() -> sqlite3.Connection:
    """schedule.db への接続を開き、Row ファクトリと外部キー制約を有効化して返す.

    Returns:
        sqlite3.Connection: Row ファクトリ有効・外部キー制約 ON の接続。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """指定名のテーブルが存在すれば True を返す.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        name (str): 確認するテーブル名。

    Returns:
        bool: 存在すれば True。
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """テーブルに指定名のカラムが存在すれば True を返す.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        table (str): テーブル名。
        column (str): 確認するカラム名。

    Returns:
        bool: 存在すれば True。
    """
    return column in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_project_phases_columns(conn: sqlite3.Connection) -> None:
    """project_phases に不足カラムを追加し、input_mode を補完する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
    """
    if not _table_exists(conn, "project_phases"):
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(project_phases)").fetchall()}
    if "enabled" not in columns:
        conn.execute("ALTER TABLE project_phases ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(project_phases)").fetchall()}
    if "input_mode" not in columns:
        conn.execute("ALTER TABLE project_phases ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'effort'")
        conn.execute(
            """
            UPDATE project_phases
            SET input_mode = (
                SELECT pd.input_mode FROM phase_definitions pd
                WHERE pd.id = project_phases.phase_id
            )
            """
        )
        conn.execute(
            """
            UPDATE project_phases
            SET input_mode = 'period'
            WHERE start_ym IS NOT NULL AND end_ym IS NOT NULL
            """
        )
        conn.execute(
            """
            UPDATE project_phases
            SET input_mode = 'effort'
            WHERE total_effort > 0
            """
        )
        conn.execute(
            """
            UPDATE project_phases
            SET input_mode = 'effort'
            WHERE EXISTS (
                SELECT 1 FROM allocations a
                WHERE a.project_id = project_phases.project_id
                  AND a.phase_id = project_phases.phase_id
            )
            """
        )


def _ensure_settings_columns(conn: sqlite3.Connection) -> None:
    """settings に不足カラムを追加・改名する（旧バージョンからの移行用）.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    if "contract_name" not in columns:
        conn.execute("ALTER TABLE settings ADD COLUMN contract_name TEXT NOT NULL DEFAULT ''")
    if "planned_utilization" not in columns:
        if "safety_rate" in columns:
            conn.execute("ALTER TABLE settings RENAME COLUMN safety_rate TO planned_utilization")
        else:
            conn.execute("ALTER TABLE settings ADD COLUMN planned_utilization REAL NOT NULL DEFAULT 80")
    if "theme" not in columns:
        conn.execute("ALTER TABLE settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'system'")


def _seed_phase_definitions(conn: sqlite3.Connection) -> None:
    """工程マスタが空なら初期工程を投入する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM phase_definitions").fetchone()["c"]
    if count:
        return
    for legacy_key, name, input_mode, color, sort_order in DEFAULT_PHASES:
        conn.execute(
            "INSERT INTO phase_definitions (name, input_mode, color, sort_order, legacy_key) VALUES (?, ?, ?, ?, ?)",
            (name, input_mode, color, sort_order, legacy_key),
        )


def _legacy_phase_map(conn: sqlite3.Connection) -> dict[str, int]:
    """旧キー（legacy_key）から phase_definitions の id への対応表を作る.

    Args:
        conn (sqlite3.Connection): SQLite 接続。

    Returns:
        dict[str, int]: legacy_key をキー、phase_definitions.id を値とする dict。
    """
    rows = conn.execute("SELECT id, legacy_key FROM phase_definitions WHERE legacy_key IS NOT NULL").fetchall()
    return {row["legacy_key"]: row["id"] for row in rows}


def _migrate_project_data(conn: sqlite3.Connection, legacy_map: dict[str, int]) -> None:
    """旧 phase_totals / test_t_period のデータを project_phases に移す.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        legacy_map (dict[str, int]): legacy_key から phase_definitions.id への対応表。
    """
    projects = conn.execute("SELECT id FROM projects").fetchall()
    for project in projects:
        project_id = project["id"]
        if conn.execute(
            "SELECT 1 FROM project_phases WHERE project_id = ? LIMIT 1",
            (project_id,),
        ).fetchone():
            continue

        totals: dict[str, float] = {}
        if _table_exists(conn, "phase_totals"):
            totals = {
                row["phase"]: row["total_effort"]
                for row in conn.execute(
                    "SELECT phase, total_effort FROM phase_totals WHERE project_id = ?",
                    (project_id,),
                )
            }

        test_t = None
        if _table_exists(conn, "test_t_period"):
            test_t = conn.execute(
                "SELECT start_ym, start_decade, end_ym, end_decade FROM test_t_period WHERE project_id = ?",
                (project_id,),
            ).fetchone()

        test_t_mode = "period"
        if _column_exists(conn, "projects", "test_t_mode"):
            row = conn.execute("SELECT test_t_mode FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row and row["test_t_mode"] in ("period", "effort"):
                test_t_mode = row["test_t_mode"]

        phase_defs = conn.execute(
            "SELECT id, legacy_key, sort_order FROM phase_definitions ORDER BY sort_order, id"
        ).fetchall()
        for phase_def in phase_defs:
            legacy_key = phase_def["legacy_key"] or ""
            total = float(totals.get(legacy_key, 0.0) or 0.0)
            start_ym = start_decade = end_ym = end_decade = None
            if legacy_key == "integration":
                phase_input_mode = test_t_mode
                if test_t and test_t_mode == "period":
                    start_ym = test_t["start_ym"]
                    start_decade = test_t["start_decade"]
                    end_ym = test_t["end_ym"]
                    end_decade = test_t["end_decade"]
            else:
                phase_input_mode = "effort"
            conn.execute(
                "INSERT INTO project_phases "
                "(project_id, phase_id, sort_order, enabled, input_mode, total_effort, start_ym, start_decade, end_ym, end_decade) "  # noqa: E501
                "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    phase_def["id"],
                    phase_def["sort_order"],
                    phase_input_mode,
                    total,
                    start_ym,
                    start_decade,
                    end_ym,
                    end_decade,
                ),
            )


def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
    """旧スキーマ（phase 文字列ベース）を phase_id ベースに移行する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
    """
    if not _table_exists(conn, "phase_definitions"):
        return

    legacy_map = _legacy_phase_map(conn)
    if not legacy_map:
        return

    if _table_exists(conn, "phase_totals") or _table_exists(conn, "test_t_period"):
        _migrate_project_data(conn, legacy_map)

    if _column_exists(conn, "allocations", "phase") and not _column_exists(conn, "allocations", "phase_id"):
        conn.executescript(
            """
            CREATE TABLE allocations_new (
                project_id INTEGER NOT NULL,
                phase_id INTEGER NOT NULL,
                year_month TEXT NOT NULL,
                decade INTEGER NOT NULL CHECK (decade IN (1, 2, 3)),
                effort REAL NOT NULL DEFAULT 0,
                actual_effort REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (project_id, phase_id, year_month, decade),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (phase_id) REFERENCES phase_definitions(id) ON DELETE CASCADE
            );
            """
        )
        rows = conn.execute("SELECT project_id, phase, year_month, decade, effort FROM allocations").fetchall()
        for row in rows:
            phase_id = legacy_map.get(row["phase"])
            if phase_id is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO allocations_new "
                "(project_id, phase_id, year_month, decade, effort) VALUES (?, ?, ?, ?, ?)",
                (
                    row["project_id"],
                    phase_id,
                    row["year_month"],
                    row["decade"],
                    row["effort"],
                ),
            )
        conn.execute("DROP TABLE allocations")
        conn.execute("ALTER TABLE allocations_new RENAME TO allocations")


def _ensure_allocations_columns(conn: sqlite3.Connection) -> None:
    """allocations に実績工数カラムが無ければ追加する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
    """
    if not _table_exists(conn, "allocations"):
        return
    if not _column_exists(conn, "allocations", "actual_effort"):
        conn.execute("ALTER TABLE allocations ADD COLUMN actual_effort REAL NOT NULL DEFAULT 0")


def init_db() -> None:
    """スキーマ作成・マイグレーションを適用し、settings の初期行を保証する.

    起動時に 1 回だけ呼び出す想定。
    """
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _ensure_settings_columns(conn)
        _ensure_project_phases_columns(conn)
        _seed_phase_definitions(conn)
        _migrate_legacy_schema(conn)
        _ensure_allocations_columns(conn)
        row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO settings "
                "(id, member_count, display_from, display_to, planned_utilization, theme) "
                "VALUES (1, 1, '2026-01', '2026-12', 80, 'system')"
            )
        conn.commit()
