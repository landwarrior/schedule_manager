"""スケジュール管理の DB アクセス層."""

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


def _require_lastrowid(cur: sqlite3.Cursor) -> int:
    """INSERT 後の cursor.lastrowid を返す.

    Args:
        cur (sqlite3.Cursor): INSERT 実行後のカーソル。

    Returns:
        int: 挿入された行の id。

    Raises:
        RuntimeError: lastrowid を取得できなかった場合。
    """
    lastrowid = cur.lastrowid
    if lastrowid is None:
        raise RuntimeError("INSERT did not return a row id")
    return lastrowid


def _optional_int(value: Any) -> int | None:
    """値を int に変換する（None は None のまま返す）.

    Args:
        value (Any): 変換対象の値。

    Returns:
        int | None: int 変換結果。入力が None なら None。
    """
    if value is None:
        return None
    return int(value)


def get_settings() -> sqlite3.Row:
    """設定行（id=1 の 1 行）を返す.

    Returns:
        sqlite3.Row: settings テーブルの 1 行。
    """
    with get_connection() as conn:
        return conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()


def update_settings(
    contract_name: str,
    member_count: int,
    display_from: str,
    display_to: str,
    planned_utilization: float,
    theme: str,
) -> None:
    """契約名・人数・表示期間・計画稼働率・テーマをまとめて更新する.

    Args:
        contract_name (str): 契約名。
        member_count (int): メンバー人数。
        display_from (str): 表示開始年月（YYYY-MM）。
        display_to (str): 表示終了年月（YYYY-MM）。
        planned_utilization (float): 計画稼働率（パーセント）。
        theme (str): UI テーマ（light / dark / system）。
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET contract_name = ?, member_count = ?, display_from = ?, "
            "display_to = ?, planned_utilization = ?, theme = ? WHERE id = 1",
            (contract_name, member_count, display_from, display_to, planned_utilization, theme),
        )
        conn.commit()


def update_theme(theme: str) -> None:
    """UI テーマ設定だけを保存する.

    Args:
        theme (str): UI テーマ（light / dark / system）。
    """
    with get_connection() as conn:
        conn.execute("UPDATE settings SET theme = ? WHERE id = 1", (theme,))
        conn.commit()


def list_holidays() -> list[sqlite3.Row]:
    """祝日を日付順で返す.

    Returns:
        list[sqlite3.Row]: 祝日行のリスト（date / name カラム）。
    """
    with get_connection() as conn:
        return list(conn.execute("SELECT date, name FROM holidays ORDER BY date").fetchall())


def list_holiday_dates() -> list[str]:
    """祝日の日付文字列（YYYY-MM-DD）だけのリストを返す.

    Returns:
        list[str]: 日付文字列のリスト。
    """
    return [row["date"] for row in list_holidays()]


def add_holiday(date_str: str, name: str) -> None:
    """日付をキーに祝日を登録・置き換える.

    Args:
        date_str (str): 祝日の日付（YYYY-MM-DD）。
        name (str): 祝日名。
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO holidays (date, name) VALUES (?, ?)",
            (date_str, name.strip()),
        )
        conn.commit()


def update_holiday(date_str: str, name: str) -> None:
    """祝日の名称を更新する.

    Args:
        date_str (str): 祝日の日付（YYYY-MM-DD）。
        name (str): 新しい祝日名。

    Raises:
        ValueError: 該当する日付が登録されていない場合。
    """
    with get_connection() as conn:
        row = conn.execute("SELECT date FROM holidays WHERE date = ?", (date_str,)).fetchone()
        if row is None:
            raise ValueError("祝日が見つかりません")
        conn.execute(
            "UPDATE holidays SET name = ? WHERE date = ?",
            (name.strip(), date_str),
        )
        conn.commit()


def delete_holiday(date_str: str) -> None:
    """日付指定で祝日を削除する.

    Args:
        date_str (str): 削除する祝日の日付（YYYY-MM-DD）。
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM holidays WHERE date = ?", (date_str,))
        conn.commit()


def list_phase_definitions() -> list[dict[str, Any]]:
    """工程マスタを表示順で返す.

    Returns:
        list[dict[str, Any]]: 工程マスタの dict リスト（id / name / color /
            sort_order / legacy_key）。
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, input_mode, color, sort_order, legacy_key FROM phase_definitions ORDER BY sort_order, id"
        ).fetchall()
        return [_phase_row(row) for row in rows]


def get_phase_definition(phase_id: int) -> dict[str, Any] | None:
    """工程マスタを 1 件返す.

    Args:
        phase_id (int): 工程マスタの id。

    Returns:
        dict[str, Any] | None: 工程マスタの dict。存在しなければ None。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, input_mode, color, sort_order, legacy_key FROM phase_definitions WHERE id = ?",
            (phase_id,),
        ).fetchone()
        return _phase_row(row) if row else None


def create_phase_definition(name: str, color: str) -> int:
    """工程マスタを新規作成し、全プロジェクトに無効状態で紐付ける.

    Args:
        name (str): 工程名。
        color (str): 表示色（cyan / orange / green / lavender）。

    Returns:
        int: 作成した工程マスタの id。

    Raises:
        ValueError: 工程名が空の場合。
    """
    name = name.strip()
    if not name:
        raise ValueError("工程名は必須です")
    color = normalize_phase_color(color)
    with get_connection() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM phase_definitions").fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO phase_definitions (name, input_mode, color, sort_order) VALUES (?, 'effort', ?, ?)",
            (name, color, max_order + 1),
        )
        phase_id = _require_lastrowid(cur)
        _attach_phase_to_all_projects(conn, phase_id, max_order + 1)
        conn.commit()
        return phase_id


def update_phase_definition(
    phase_id: int,
    name: str,
    color: str,
) -> None:
    """工程マスタの名称・色を更新する.

    Args:
        phase_id (int): 工程マスタの id。
        name (str): 新しい工程名。
        color (str): 新しい表示色。

    Raises:
        ValueError: 工程名が空、または該当 id が存在しない場合。
    """
    name = name.strip()
    if not name:
        raise ValueError("工程名は必須です")
    color = normalize_phase_color(color)
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM phase_definitions WHERE id = ?", (phase_id,)).fetchone()
        if row is None:
            raise ValueError("工程が見つかりません")
        conn.execute(
            "UPDATE phase_definitions SET name = ?, color = ? WHERE id = ?",
            (name, color, phase_id),
        )
        conn.commit()


def reorder_phase_definitions(ordered_ids: list[int]) -> None:
    """指定した id 順に工程マスタの表示順を更新する.

    Args:
        ordered_ids (list[int]): 全工程マスタの id を並べ替えたリスト。

    Raises:
        ValueError: id 一覧が既存の工程マスタと一致しない場合。
    """
    if not ordered_ids:
        raise ValueError("並び順が不正です")
    with get_connection() as conn:
        known = {row["id"] for row in conn.execute("SELECT id FROM phase_definitions").fetchall()}
        if set(ordered_ids) != known:
            raise ValueError("並び順が不正です")
        for index, phase_id in enumerate(ordered_ids):
            conn.execute(
                "UPDATE phase_definitions SET sort_order = ? WHERE id = ?",
                (index, phase_id),
            )
        conn.commit()


def reorder_projects(ordered_ids: list[int]) -> None:
    """指定した id 順にプロジェクトの表示順を更新する.

    Args:
        ordered_ids (list[int]): 全プロジェクトの id を並べ替えたリスト。

    Raises:
        ValueError: id 一覧が既存のプロジェクトと一致しない場合。
    """
    if not ordered_ids:
        raise ValueError("並び順が不正です")
    with get_connection() as conn:
        known = {row["id"] for row in conn.execute("SELECT id FROM projects").fetchall()}
        if set(ordered_ids) != known:
            raise ValueError("並び順が不正です")
        for index, project_id in enumerate(ordered_ids):
            conn.execute(
                "UPDATE projects SET sort_order = ? WHERE id = ?",
                (index, project_id),
            )
        conn.commit()


def delete_phase_definition(phase_id: int) -> None:
    """工程マスタを削除する（最後の 1 件は削除しない）.

    Args:
        phase_id (int): 削除する工程マスタの id。

    Raises:
        ValueError: 工程マスタが残り 1 件しかない場合。
    """
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM phase_definitions").fetchone()["c"]
        if count <= 1:
            raise ValueError("工程は最低1つ必要です")
        conn.execute("DELETE FROM phase_definitions WHERE id = ?", (phase_id,))
        conn.commit()


def _attach_phase_to_all_projects(conn: sqlite3.Connection, phase_id: int, sort_order: int) -> None:
    """全プロジェクトに、無効かつ工数入力モードの工程行を追加する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        phase_id (int): 追加する工程マスタの id。
        sort_order (int): project_phases に設定する表示順。
    """
    projects = conn.execute("SELECT id FROM projects").fetchall()
    for project in projects:
        conn.execute(
            "INSERT OR IGNORE INTO project_phases "
            "(project_id, phase_id, sort_order, enabled, input_mode, total_effort) "
            "VALUES (?, ?, ?, 0, 'effort', 0)",
            (project["id"], phase_id, sort_order),
        )


def _default_input_mode(legacy_key: str | None) -> str:
    """新規プロジェクト工程の初期入力方式を legacy_key から決める.

    Args:
        legacy_key (str | None): 工程マスタの legacy_key。

    Returns:
        str: ``"integration"`` なら ``"period"``、それ以外は ``"effort"``。
    """
    if legacy_key == "integration":
        return "period"
    return "effort"


def _clear_project_phase_mode_data(
    conn: sqlite3.Connection,
    project_id: int,
    phase_id: int,
    input_mode: str,
) -> None:
    """入力方式変更時に、使わなくなった工数・期間データを消す.

    period に変える場合は割当・総工数を削除し、effort に変える場合は期間を消す。

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        project_id (int): 対象プロジェクト id。
        phase_id (int): 対象工程 id。
        input_mode (str): 新しい入力方式（period / effort）。
    """
    if input_mode == "period":
        conn.execute(
            "UPDATE project_phases SET total_effort = 0 WHERE project_id = ? AND phase_id = ?",
            (project_id, phase_id),
        )
        conn.execute(
            "DELETE FROM allocations WHERE project_id = ? AND phase_id = ?",
            (project_id, phase_id),
        )
    else:
        conn.execute(
            "UPDATE project_phases SET start_ym = NULL, start_decade = NULL, "
            "end_ym = NULL, end_decade = NULL "
            "WHERE project_id = ? AND phase_id = ?",
            (project_id, phase_id),
        )


def _phase_row(row: sqlite3.Row) -> dict[str, Any]:
    """phase_definitions の行を表示用 dict に変換する.

    Args:
        row (sqlite3.Row): phase_definitions の 1 行。

    Returns:
        dict[str, Any]: id / name / color / sort_order / legacy_key を持つ dict。
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "color": normalize_phase_color(row["color"]),
        "sort_order": row["sort_order"],
        "legacy_key": row["legacy_key"],
    }


def _load_project_phases(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    """指定プロジェクトの工程設定をマスタと結合して読み込む.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        project_id (int): プロジェクト id。

    Returns:
        list[dict[str, Any]]: 工程設定の dict リスト（表示順）。
    """
    rows = conn.execute(
        """
        SELECT
            pp.project_id,
            pp.phase_id,
            pp.sort_order,
            pp.enabled,
            pp.input_mode,
            pp.total_effort,
            pp.start_ym,
            pp.start_decade,
            pp.end_ym,
            pp.end_decade,
            pd.name,
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
                "input_mode": normalize_phase_input_mode(row["input_mode"]),
                "total_effort": row["total_effort"],
                "start_ym": row["start_ym"],
                "start_decade": row["start_decade"],
                "end_ym": row["end_ym"],
                "end_decade": row["end_decade"],
                "name": row["name"],
                "color": normalize_phase_color(row["color"]),
            }
        )
    return phases


def list_projects() -> list[dict[str, Any]]:
    """全プロジェクトを工程設定つきで返す.

    Returns:
        list[dict[str, Any]]: プロジェクト dict（id / name / sort_order / phases）のリスト。
    """
    with get_connection() as conn:
        projects = conn.execute("SELECT id, name, sort_order FROM projects ORDER BY sort_order, id").fetchall()
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
    """プロジェクト 1 件を工程設定つきで返す.

    Args:
        project_id (int): プロジェクト id。

    Returns:
        dict[str, Any] | None: プロジェクト dict。存在しなければ None。
    """
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
    """新規プロジェクトに初期工程行を挿入する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        project_id (int): 新規作成したプロジェクト id。
    """
    phase_defs = conn.execute(
        "SELECT id, sort_order, legacy_key FROM phase_definitions ORDER BY sort_order, id"
    ).fetchall()
    for phase_def in phase_defs:
        input_mode = _default_input_mode(phase_def["legacy_key"])
        conn.execute(
            "INSERT INTO project_phases "
            "(project_id, phase_id, sort_order, enabled, input_mode, total_effort) "
            "VALUES (?, ?, ?, 1, ?, 0)",
            (project_id, phase_def["id"], phase_def["sort_order"], input_mode),
        )


def create_project(name: str, phase_configs: list[dict[str, Any]]) -> int:
    """プロジェクトを作成し、初期工程と指定設定を適用する.

    Args:
        name (str): プロジェクト名。
        phase_configs (list[dict[str, Any]]): 工程設定の dict リスト
            （phase_id / enabled / input_mode など）。

    Returns:
        int: 作成したプロジェクトの id。
    """
    with get_connection() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM projects").fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO projects (name, sort_order) VALUES (?, ?)",
            (name.strip(), max_order + 1),
        )
        project_id = _require_lastrowid(cur)
        _init_project_phases(conn, project_id)
        _save_project_phases(conn, project_id, phase_configs)
        conn.commit()
        return project_id


def update_project(project_id: int, name: str, phase_configs: list[dict[str, Any]]) -> None:
    """プロジェクト名と工程設定を更新する.

    Args:
        project_id (int): プロジェクト id。
        name (str): 新しいプロジェクト名。
        phase_configs (list[dict[str, Any]]): 工程設定の dict リスト。
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?",
            (name.strip(), project_id),
        )
        _save_project_phases(conn, project_id, phase_configs)
        conn.commit()


def _save_project_phases(conn: sqlite3.Connection, project_id: int, phase_configs: list[dict[str, Any]]) -> None:
    """プロジェクトの有効フラグ・入力方式・工数/期間を保存する.

    入力方式が変更された工程は、使わなくなった側のデータを消去する。

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        project_id (int): プロジェクト id。
        phase_configs (list[dict[str, Any]]): 工程設定の dict リスト
            （phase_id / enabled / input_mode / total_effort / start_ym /
            start_decade / end_ym / end_decade）。

    Raises:
        ValueError: 不明な工程 id が含まれる場合。
    """
    known_ids = {row["id"] for row in conn.execute("SELECT id FROM phase_definitions").fetchall()}
    for index, config in enumerate(phase_configs):
        phase_id = int(config["phase_id"])
        if phase_id not in known_ids:
            raise ValueError("工程が不正です")
        input_mode = normalize_phase_input_mode(config.get("input_mode", "effort"))
        enabled = 1 if config.get("enabled", True) else 0
        prev = conn.execute(
            "SELECT input_mode FROM project_phases WHERE project_id = ? AND phase_id = ?",
            (project_id, phase_id),
        ).fetchone()
        if prev and normalize_phase_input_mode(prev["input_mode"]) != input_mode:
            _clear_project_phase_mode_data(conn, project_id, phase_id, input_mode)

        total_effort = 0.0
        start_ym = start_decade = end_ym = end_decade = None
        if input_mode == "effort":
            total_effort = round_effort(float(config.get("total_effort", 0) or 0))
        else:
            start_ym = config.get("start_ym") or None
            end_ym = config.get("end_ym") or None
            start_decade = _optional_int(config.get("start_decade"))
            end_decade = _optional_int(config.get("end_decade"))
        conn.execute(
            "UPDATE project_phases SET sort_order = ?, enabled = ?, input_mode = ?, "
            "total_effort = ?, start_ym = ?, start_decade = ?, end_ym = ?, end_decade = ? "
            "WHERE project_id = ? AND phase_id = ?",
            (
                index,
                enabled,
                input_mode,
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
    """プロジェクトを削除する（割当・工程設定はカスケード削除）.

    Args:
        project_id (int): 削除するプロジェクト id。
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()


def _normalize_cell_effort(decade: int, effort: float) -> float:
    """旬と工数を検証し、0.1 刻みに丸めて返す.

    Args:
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        effort (float): 工数（人日）。

    Returns:
        float: 0.1 刻みに丸めた工数。

    Raises:
        ValueError: 旬または工数が不正な場合。
    """
    if decade not in (1, 2, 3):
        raise ValueError("invalid decade")
    effort = round_effort(effort)
    if not is_valid_effort(effort):
        raise ValueError("effort must be in 0.1 increments")
    return effort


def _assert_effort_phase(conn: sqlite3.Connection, project_id: int, phase_id: int) -> None:
    """対象工程が表示中の工数入力であることを確認する.

    Args:
        conn (sqlite3.Connection): SQLite 接続。
        project_id (int): プロジェクト id。
        phase_id (int): 工程マスタ id。

    Raises:
        ValueError: 工程が無効、または工数入力でない場合。
    """
    linked = conn.execute(
        "SELECT enabled, input_mode FROM project_phases WHERE project_id = ? AND phase_id = ?",
        (project_id, phase_id),
    ).fetchone()
    if linked is None or not linked["enabled"] or linked["input_mode"] != "effort":
        raise ValueError("invalid phase")


def list_allocation_cells(from_ym: str, to_ym: str) -> dict[tuple[int, int, str, int], tuple[float, float]]:
    """指定期間内の見積工数と実績工数をキー付き dict で返す.

    有効かつ入力方式が effort の工程のみを対象とする。

    Args:
        from_ym (str): 開始年月（YYYY-MM、含む）。
        to_ym (str): 終了年月（YYYY-MM、含む）。

    Returns:
        dict[tuple[int, int, str, int], tuple[float, float]]:
            (project_id, phase_id, year_month, decade) をキー、
            (見積工数, 実績工数) を値とする dict。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.project_id, a.phase_id, a.year_month, a.decade, a.effort, a.actual_effort
            FROM allocations a
            JOIN project_phases pp
              ON pp.project_id = a.project_id
             AND pp.phase_id = a.phase_id
             AND pp.enabled = 1
             AND pp.input_mode = 'effort'
            WHERE a.year_month >= ? AND a.year_month <= ?
            """,
            (from_ym, to_ym),
        ).fetchall()
        return {
            (row["project_id"], row["phase_id"], row["year_month"], row["decade"]): (
                float(row["effort"]),
                float(row["actual_effort"]),
            )
            for row in rows
        }


def _save_allocation_value(
    project_id: int,
    phase_id: int,
    year_month: str,
    decade: int,
    value: float,
    *,
    field: str,
) -> tuple[float, float]:
    """セルの見積工数または実績工数を保存する.

    見積と実績がともに 0 のときは行を削除する。片方だけ残る場合は行を保持する。

    Args:
        project_id (int): プロジェクト id。
        phase_id (int): 工程マスタ id。
        year_month (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        value (float): 保存する工数（人日、0.1 刻み）。
        field (str): ``"effort"``（見積）または ``"actual_effort"``（実績）。

    Returns:
        tuple[float, float]: 保存後の (見積工数, 実績工数)。

    Raises:
        ValueError: 旬・工数・工程・対象フィールドが不正な場合。
    """
    if field not in ("effort", "actual_effort"):
        raise ValueError("invalid field")
    value = _normalize_cell_effort(decade, value)
    with get_connection() as conn:
        _assert_effort_phase(conn, project_id, phase_id)
        row = conn.execute(
            """
            SELECT effort, actual_effort
            FROM allocations
            WHERE project_id = ? AND phase_id = ? AND year_month = ? AND decade = ?
            """,
            (project_id, phase_id, year_month, decade),
        ).fetchone()
        effort = float(row["effort"]) if row else 0.0
        actual = float(row["actual_effort"]) if row else 0.0
        if field == "effort":
            effort = value
        else:
            actual = value
        if effort == 0 and actual == 0:
            conn.execute(
                "DELETE FROM allocations WHERE project_id = ? AND phase_id = ? AND year_month = ? AND decade = ?",
                (project_id, phase_id, year_month, decade),
            )
        else:
            conn.execute(
                "INSERT INTO allocations (project_id, phase_id, year_month, decade, effort, actual_effort) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, phase_id, year_month, decade) "
                "DO UPDATE SET effort = excluded.effort, actual_effort = excluded.actual_effort",
                (project_id, phase_id, year_month, decade, effort, actual),
            )
        conn.commit()
    return effort, actual


def set_allocation(
    project_id: int,
    phase_id: int,
    year_month: str,
    decade: int,
    effort: float,
) -> tuple[float, float]:
    """工程×年月×旬のセルに見積工数を登録・更新する.

    見積が 0 でも実績が残っていれば行は削除しない。

    Args:
        project_id (int): プロジェクト id。
        phase_id (int): 工程マスタ id。
        year_month (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        effort (float): 見積工数（人日、0.1 刻み）。

    Returns:
        tuple[float, float]: 保存後の (見積工数, 実績工数)。

    Raises:
        ValueError: 旬や工数が不正、または工程が無効・effort モードでない場合。
    """
    return _save_allocation_value(project_id, phase_id, year_month, decade, effort, field="effort")


def set_actual_effort(
    project_id: int,
    phase_id: int,
    year_month: str,
    decade: int,
    actual_effort: float,
) -> tuple[float, float]:
    """工程×年月×旬のセルに実績工数を登録・更新する.

    実績が 0 でも見積が残っていれば行は削除しない。

    Args:
        project_id (int): プロジェクト id。
        phase_id (int): 工程マスタ id。
        year_month (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        actual_effort (float): 実績工数（人日、0.1 刻み）。

    Returns:
        tuple[float, float]: 保存後の (見積工数, 実績工数)。

    Raises:
        ValueError: 旬や工数が不正、または工程が無効・effort モードでない場合。
    """
    return _save_allocation_value(
        project_id,
        phase_id,
        year_month,
        decade,
        actual_effort,
        field="actual_effort",
    )


def allocation_totals_by_project_phase() -> dict[tuple[int, int], tuple[float, float]]:
    """プロジェクト×工程ごとの見積割当と実績割当の合計を返す.

    有効かつ入力方式が effort の工程のみを対象とする。表示期間では絞らない。

    Returns:
        dict[tuple[int, int], tuple[float, float]]: (project_id, phase_id) をキー、
            (見積割当合計, 実績割当合計) を値とする dict。
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.project_id, a.phase_id,
                   COALESCE(SUM(a.effort), 0) AS total,
                   COALESCE(SUM(a.actual_effort), 0) AS actual
            FROM allocations a
            JOIN project_phases pp
              ON pp.project_id = a.project_id
             AND pp.phase_id = a.phase_id
             AND pp.enabled = 1
             AND pp.input_mode = 'effort'
            GROUP BY a.project_id, a.phase_id
            """
        ).fetchall()
        return {
            (row["project_id"], row["phase_id"]): (float(row["total"]), float(row["actual"]))
            for row in rows
        }


def allocated_totals_by_project_phase() -> dict[tuple[int, int], float]:
    """プロジェクト×工程ごとの見積割当工数合計を返す.

    有効かつ入力方式が effort の工程のみを対象とする。

    Returns:
        dict[tuple[int, int], float]: (project_id, phase_id) をキー、見積割当工数の合計を
            値とする dict。
    """
    return {key: effort for key, (effort, _actual) in allocation_totals_by_project_phase().items()}


def phase_input_mode_label(mode: str) -> str:
    """入力方式の日本語ラベルを返す.

    Args:
        mode (str): 入力方式（period / effort）。

    Returns:
        str: ``"期間のみ"`` または ``"工数入力"``。
    """
    if mode == "period":
        return "期間のみ"
    return "工数入力"
