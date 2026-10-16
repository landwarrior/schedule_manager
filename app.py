"""スケジュール管理 Web アプリケーション."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from collections.abc import Mapping, Sequence
from typing import Any

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from werkzeug.datastructures import MultiDict
from werkzeug.serving import make_server

from calendar_util import (
    DECADE_LABELS,
    PHASE_COLOR_LABELS,
    PHASE_COLORS,
    allocation_status,
    business_days,
    capacity,
    is_period_in_range,
    is_valid_effort,
    iter_months,
    normalize_date,
    normalize_ym,
    parse_ym,
    round_effort,
)
from db import DB_PATH, init_db
from models import (
    add_holiday,
    allocation_totals_by_project_phase,
    allocated_totals_by_project_phase,
    create_phase_definition,
    create_project,
    delete_holiday,
    delete_phase_definition,
    delete_project,
    get_phase_definition,
    get_project,
    get_settings,
    list_allocation_cells,
    list_holiday_dates,
    list_holidays,
    list_phase_definitions,
    list_projects,
    phase_input_mode_label,
    reorder_phase_definitions,
    reorder_projects,
    set_actual_effort,
    set_allocation,
    update_holiday,
    update_phase_definition,
    update_project,
    update_settings,
    update_theme,
)
from paths import is_frozen, resource_root

_ROOT = resource_root()
app = Flask(
    __name__,
    template_folder=str(_ROOT / "templates"),
    static_folder=str(_ROOT / "static"),
)
app.secret_key = "schedule-manager-local"
init_db()

THEME_CHOICES = ("light", "dark", "system")
THEME_LABELS = {
    "light": "ライト",
    "dark": "ダーク",
    "system": "システムに合わせる",
}


def _normalize_theme(raw: str | None) -> str:
    """テーマ指定（light/dark/system）を検証・正規化する.

    Args:
        raw (str | None): フォームなどから受け取ったテーマ文字列。

    Returns:
        str: 正規化したテーマ名（light / dark / system）。

    Raises:
        ValueError: テーマ名が不正な場合。
    """
    theme = (raw or "system").strip().lower()
    if theme not in THEME_CHOICES:
        raise ValueError("テーマの指定が不正です")
    return theme


@app.context_processor
def inject_theme() -> dict[str, Any]:
    """テーマと工程色ラベルを全テンプレートのコンテキストに注入する.

    Returns:
        dict[str, Any]: ui_theme / theme_choices / theme_labels /
            phase_color_labels を含む dict。
    """
    settings = get_settings()
    theme = settings["theme"] if settings and settings["theme"] else "system"
    if theme not in THEME_CHOICES:
        theme = "system"
    return {
        "ui_theme": theme,
        "theme_choices": THEME_CHOICES,
        "theme_labels": THEME_LABELS,
        "phase_color_labels": PHASE_COLOR_LABELS,
    }


def _parse_effort(raw: str | None) -> float:
    """フォームの工数文字列を 0.1 刻みの float に変換する（空は 0）.

    Args:
        raw (str | None): 工数の入力文字列。None や空文字は 0.0 とみなす。

    Returns:
        float: 0.1 刻みに丸めた工数（人日）。

    Raises:
        ValueError: 数値でない、または 0.1 刻みでない場合。
    """
    if raw is None:
        return 0.0
    text = raw.strip()
    if not text:
        return 0.0
    value = round_effort(float(text))
    if not is_valid_effort(value):
        raise ValueError("工数は 0.1 刻みで入力してください")
    return value


def _parse_decade(raw: str | None) -> int | None:
    """フォームの旬指定を 1/2/3 に変換する（空は None）.

    Args:
        raw (str | None): 旬の入力文字列。

    Returns:
        int | None: 1 / 2 / 3 のいずれか。空なら None。

    Raises:
        ValueError: 1, 2, 3 以外が指定された場合。
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    value = int(text)
    if value not in (1, 2, 3):
        raise ValueError("旬が不正です")
    return value


def _require_form_int(raw: str | None, message: str) -> int:
    """必須の整数フォーム項目を変換する.

    Args:
        raw (str | None): フォームの入力文字列。
        message (str): 変換失敗時に使うエラーメッセージ。

    Returns:
        int: 変換した整数値。

    Raises:
        ValueError: 未入力・空文字・整数でない場合。
    """
    if raw is None:
        raise ValueError(message)
    text = raw.strip()
    if not text:
        raise ValueError(message)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_project_phases(form: MultiDict[str, str]) -> list[dict[str, Any]]:
    """プロジェクト作成/編集フォームから工程設定リストを組み立てる.

    Args:
        form (MultiDict[str, str]): 送信されたフォーム（phase_order と
            工程ごとの入力を含む）。

    Returns:
        list[dict[str, Any]]: models._save_project_phases に渡す工程設定 dict のリスト。

    Raises:
        ValueError: 並び順や工程指定が不正な場合。
    """
    order_raw = (form.get("phase_order") or "").strip()
    if not order_raw:
        raise ValueError("工程の並び順が不正です")
    phase_ids = [int(part) for part in order_raw.split(",") if part.strip()]
    if not phase_ids:
        raise ValueError("工程の並び順が不正です")

    configs: list[dict[str, Any]] = []
    enabled_count = 0
    for phase_id in phase_ids:
        phase = get_phase_definition(phase_id)
        if phase is None:
            raise ValueError("工程が不正です")
        enabled = form.get(f"enabled_{phase_id}") == "1"
        if enabled:
            enabled_count += 1
        config: dict[str, Any] = {"phase_id": phase_id, "enabled": enabled}
        mode_raw = (form.get(f"input_mode_{phase_id}") or "effort").strip()
        if mode_raw not in ("period", "effort"):
            raise ValueError("入力方式が不正です")
        config["input_mode"] = mode_raw
        if mode_raw == "effort":
            config["total_effort"] = _parse_effort(form.get(f"total_{phase_id}"))
        else:
            start_raw = (form.get(f"period_{phase_id}_start_ym") or "").strip()
            end_raw = (form.get(f"period_{phase_id}_end_ym") or "").strip()
            config["start_ym"] = normalize_ym(start_raw) if start_raw else None
            config["end_ym"] = normalize_ym(end_raw) if end_raw else None
            config["start_decade"] = _parse_decade(form.get(f"period_{phase_id}_start_decade"))
            config["end_decade"] = _parse_decade(form.get(f"period_{phase_id}_end_decade"))
        configs.append(config)
    if enabled_count == 0:
        raise ValueError("表示する工程を1つ以上選んでください")
    return configs


def _build_schedule_phase_rows(
    project: dict[str, Any],
    columns: Sequence[tuple[str, int]],
    allocation_cells: Mapping[tuple[int, int, str, int], tuple[float, float]],
    allocated_sums: Mapping[tuple[int, int], tuple[float, float]],
) -> list[dict[str, Any]]:
    """プロジェクト 1 件分の有効工程からスケジュール表の行を組み立てる.

    Args:
        project (dict[str, Any]): 工程設定を含むプロジェクト dict。
        columns (Sequence[tuple[str, int]]): 表示対象の (年月, 旬) の列一覧。
        allocation_cells (Mapping[tuple[int, int, str, int], tuple[float, float]]):
            セル工数の dict。キーは (project_id, phase_id, 年月, 旬)、
            値は (見積工数, 実績工数)。
        allocated_sums (Mapping[tuple[int, int], tuple[float, float]]):
            プロジェクト×工程ごとの (見積割当合計, 実績割当合計)。

    Returns:
        list[dict[str, Any]]: テンプレートに渡す工程行 dict のリスト。
    """
    rows: list[dict[str, Any]] = []
    for phase in project["phases"]:
        if not phase.get("enabled", True):
            continue
        phase_id = phase["phase_id"]
        if phase["input_mode"] == "effort":
            cells = []
            allocated, actual_allocated = allocated_sums.get((project["id"], phase_id), (0.0, 0.0))
            total = float(phase["total_effort"] or 0.0)
            for ym, decade in columns:
                effort, actual = allocation_cells.get((project["id"], phase_id, ym, decade), (0.0, 0.0))
                cells.append(
                    {
                        "ym": ym,
                        "decade": decade,
                        "effort": effort,
                        "actual": actual,
                        "active": effort > 0,
                    }
                )
            rows.append(
                {
                    "id": phase_id,
                    "name": phase["name"],
                    "input_mode": "effort",
                    "color": phase["color"],
                    "total": total,
                    "allocated": round_effort(allocated),
                    "actual": round_effort(actual_allocated),
                    "diff": round_effort(total - allocated),
                    "cells": cells,
                }
            )
        else:
            cells = []
            for ym, decade in columns:
                active = is_period_in_range(
                    ym,
                    decade,
                    phase.get("start_ym"),
                    phase.get("start_decade"),
                    phase.get("end_ym"),
                    phase.get("end_decade"),
                )
                cells.append({"ym": ym, "decade": decade, "active": active})
            rows.append(
                {
                    "id": phase_id,
                    "name": phase["name"],
                    "input_mode": "period",
                    "color": phase["color"],
                    "cells": cells,
                }
            )
    return rows


@app.route("/")
def schedule() -> ResponseReturnValue:
    """選択された表示期間のスケジュールマトリクス画面を表示する.

    Returns:
        ResponseReturnValue: schedule.html のレンダリング結果。
            期間不正時はトップへのリダイレクト。
    """
    settings = get_settings()
    try:
        display_from = normalize_ym(request.args.get("from") or settings["display_from"])
        display_to = normalize_ym(request.args.get("to") or settings["display_to"])
    except ValueError:
        flash("表示期間の形式が不正です（YYYY-MM）", "error")
        return redirect(url_for("schedule"))

    if display_from > display_to:
        flash("表示開始月は終了月以前にしてください", "error")
        return redirect(url_for("schedule"))

    months = iter_months(display_from, display_to)
    columns = [(ym, decade) for ym in months for decade in (1, 2, 3)]
    holidays = list_holiday_dates()
    member_count = settings["member_count"]
    planned_utilization = float(settings["planned_utilization"] if settings["planned_utilization"] is not None else 80)

    capacities = {
        (ym, decade): {
            "business_days": business_days(ym, decade, holidays),
            "capacity": capacity(ym, decade, holidays, member_count),
        }
        for ym, decade in columns
    }

    projects = list_projects()
    allocation_cells = list_allocation_cells(display_from, display_to)
    allocated_sums = allocation_totals_by_project_phase()

    period_totals: dict[tuple[str, int], float] = {(ym, d): 0.0 for ym, d in columns}
    period_actuals: dict[tuple[str, int], float] = {(ym, d): 0.0 for ym, d in columns}
    for (_project_id, _phase_id, ym, decade), (effort, actual) in allocation_cells.items():
        if (ym, decade) in period_totals:
            period_totals[(ym, decade)] = round_effort(period_totals[(ym, decade)] + effort)
            period_actuals[(ym, decade)] = round_effort(period_actuals[(ym, decade)] + actual)

    project_rows = []
    for project in projects:
        phases = _build_schedule_phase_rows(project, columns, allocation_cells, allocated_sums)
        project_rows.append(
            {
                "id": project["id"],
                "name": project["name"],
                "phases": phases,
                "phase_count": len(phases),
            }
        )

    summary = []
    for ym, decade in columns:
        cap = capacities[(ym, decade)]
        allocated = period_totals[(ym, decade)]
        actual = period_actuals[(ym, decade)]
        status = allocation_status(allocated, cap["capacity"], planned_utilization)
        summary.append(
            {
                "ym": ym,
                "decade": decade,
                "business_days": cap["business_days"],
                "capacity": cap["capacity"],
                "allocated": allocated,
                "actual": actual,
                "status": status,
                "warn_threshold": round_effort(cap["capacity"] * planned_utilization / 100.0),
            }
        )

    contract_name = (settings["contract_name"] or "").strip() if settings else ""

    return render_template(
        "schedule.html",
        contract_name=contract_name,
        display_from=display_from,
        display_to=display_to,
        months=months,
        decade_labels=DECADE_LABELS,
        projects=project_rows,
        summary=summary,
        member_count=member_count,
        planned_utilization=planned_utilization,
    )


@app.post("/api/allocations")
def api_set_allocation() -> ResponseReturnValue:
    """割当セル 1 件の見積または実績を更新し、最新の合計を JSON で返す.

    ``kind`` が ``actual`` のとき実績工数、それ以外は見積工数を保存する。

    Returns:
        ResponseReturnValue: ok / kind / effort / actual / period / phase を含む JSON。
            入力不正時は HTTP 400 とエラーメッセージ。
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        project_id = int(data["project_id"])
        phase_id = int(data["phase_id"])
        year_month = data["year_month"]
        decade = int(data["decade"])
        kind = str(data.get("kind") or "estimate")
        if kind not in ("estimate", "actual"):
            raise ValueError("入力対象が不正です")
        value = _parse_effort(str(data.get("effort", 0)))
        parse_ym(year_month)
        if kind == "actual":
            effort, actual = set_actual_effort(project_id, phase_id, year_month, decade, value)
        else:
            effort, actual = set_allocation(project_id, phase_id, year_month, decade, value)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    settings = get_settings()
    holidays = list_holiday_dates()
    with_period = list_allocation_cells(year_month, year_month)
    period_total = 0.0
    period_actual = 0.0
    for (_pid, _phase, ym, d), (cell_effort, cell_actual) in with_period.items():
        if ym == year_month and d == decade:
            period_total = round_effort(period_total + cell_effort)
            period_actual = round_effort(period_actual + cell_actual)
    cap = capacity(year_month, decade, holidays, settings["member_count"])
    biz = business_days(year_month, decade, holidays)
    planned_utilization = float(settings["planned_utilization"] if settings["planned_utilization"] is not None else 80)
    status = allocation_status(period_total, cap, planned_utilization)
    allocated_sums = allocation_totals_by_project_phase()
    project = get_project(project_id)
    phase_total = 0.0
    if project:
        for phase in project["phases"]:
            if phase["phase_id"] == phase_id:
                phase_total = float(phase["total_effort"] or 0.0)
                break
    phase_allocated, phase_actual = allocated_sums.get((project_id, phase_id), (0.0, 0.0))
    phase_allocated = round_effort(phase_allocated)
    phase_actual = round_effort(phase_actual)

    return jsonify(
        {
            "ok": True,
            "kind": kind,
            "effort": effort,
            "actual": actual,
            "period": {
                "year_month": year_month,
                "decade": decade,
                "allocated": period_total,
                "actual": period_actual,
                "capacity": cap,
                "business_days": biz,
                "status": status,
            },
            "phase": {
                "allocated": phase_allocated,
                "actual": phase_actual,
                "total": phase_total,
                "diff": round_effort(phase_total - phase_allocated),
            },
        }
    )


@app.route("/projects", methods=["GET", "POST"])
def projects_list() -> ResponseReturnValue:
    """プロジェクト一覧を表示し、表示順の保存を処理する.

    Returns:
        ResponseReturnValue: projects.html のレンダリング結果。
            POST 後は一覧へのリダイレクト。
    """
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "reorder":
                order_raw = (request.form.get("project_order") or "").strip()
                ordered_ids = [int(part) for part in order_raw.split(",") if part.strip()]
                reorder_projects(ordered_ids)
                flash("表示順を保存しました", "ok")
            else:
                raise ValueError("操作が不正です")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("projects_list"))

    projects = list_projects()
    allocated = allocated_totals_by_project_phase()
    return render_template(
        "projects.html",
        projects=projects,
        allocated=allocated,
        phase_definitions=list_phase_definitions(),
        decade_labels=DECADE_LABELS,
        phase_input_mode_label=phase_input_mode_label,
    )


@app.route("/projects/new", methods=["GET", "POST"])
def projects_new() -> ResponseReturnValue:
    """プロジェクトを新規作成する.

    Returns:
        ResponseReturnValue: GET 時は project_form.html、
            POST 成功時は一覧へのリダイレクト。
    """
    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            if not name:
                raise ValueError("プロジェクト名は必須です")
            phase_configs = _parse_project_phases(request.form)
            create_project(name, phase_configs)
            flash("プロジェクトを作成しました", "ok")
            return redirect(url_for("projects_list"))
        except ValueError as exc:
            flash(str(exc), "error")
    phases = list_phase_definitions()
    project = {
        "name": "",
        "phases": [
            {
                "phase_id": phase["id"],
                "name": phase["name"],
                "color": phase["color"],
                "sort_order": index,
                "enabled": True,
                "input_mode": "period" if phase.get("legacy_key") == "integration" else "effort",
                "total_effort": 0.0,
                "start_ym": None,
                "start_decade": None,
                "end_ym": None,
                "end_decade": None,
            }
            for index, phase in enumerate(phases)
        ],
    }
    return render_template(
        "project_form.html",
        mode="new",
        project=project,
        decade_labels=DECADE_LABELS,
        phase_input_mode_label=phase_input_mode_label,
    )


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def projects_edit(project_id: int) -> ResponseReturnValue:
    """既存プロジェクトの名称と工程設定を編集する.

    Args:
        project_id (int): 編集対象のプロジェクト id。

    Returns:
        ResponseReturnValue: GET 時は project_form.html、
            POST 成功時・不明 id 時は一覧へのリダイレクト。
    """
    project = get_project(project_id)
    if project is None:
        flash("プロジェクトが見つかりません", "error")
        return redirect(url_for("projects_list"))
    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            if not name:
                raise ValueError("プロジェクト名は必須です")
            phase_configs = _parse_project_phases(request.form)
            update_project(project_id, name, phase_configs)
            flash("プロジェクトを更新しました", "ok")
            return redirect(url_for("projects_list"))
        except ValueError as exc:
            flash(str(exc), "error")
            project = get_project(project_id)
    return render_template(
        "project_form.html",
        mode="edit",
        project=project,
        decade_labels=DECADE_LABELS,
        phase_input_mode_label=phase_input_mode_label,
    )


@app.post("/projects/<int:project_id>/delete")
def projects_delete(project_id: int) -> ResponseReturnValue:
    """プロジェクトを削除して一覧に戻る.

    Args:
        project_id (int): 削除対象のプロジェクト id。

    Returns:
        ResponseReturnValue: 一覧へのリダイレクト。
    """
    delete_project(project_id)
    flash("プロジェクトを削除しました", "ok")
    return redirect(url_for("projects_list"))


@app.route("/phases", methods=["GET", "POST"])
def phases_page() -> ResponseReturnValue:
    """工程マスタの管理（追加・更新・並び替え）を行う.

    Returns:
        ResponseReturnValue: phases.html のレンダリング結果。
            POST 後は管理画面へのリダイレクト。
    """
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "create":
                create_phase_definition(
                    request.form.get("name") or "",
                    request.form.get("color") or "cyan",
                )
                flash("工程を追加しました", "ok")
            elif action == "update":
                phase_id = _require_form_int(request.form.get("phase_id"), "工程が不正です")
                update_phase_definition(
                    phase_id,
                    request.form.get("name") or "",
                    request.form.get("color") or "cyan",
                )
                flash("工程を更新しました", "ok")
            elif action == "reorder":
                order_raw = (request.form.get("phase_order") or "").strip()
                ordered_ids = [int(part) for part in order_raw.split(",") if part.strip()]
                reorder_phase_definitions(ordered_ids)
                flash("表示順を保存しました", "ok")
            else:
                raise ValueError("操作が不正です")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("phases_page"))
    return render_template(
        "phases.html",
        phases=list_phase_definitions(),
        phase_colors=PHASE_COLORS,
        phase_input_mode_label=phase_input_mode_label,
    )


@app.post("/phases/<int:phase_id>/delete")
def phases_delete(phase_id: int) -> ResponseReturnValue:
    """工程マスタを削除して管理画面に戻る.

    Args:
        phase_id (int): 削除対象の工程マスタ id。

    Returns:
        ResponseReturnValue: 管理画面へのリダイレクト。
    """
    try:
        delete_phase_definition(phase_id)
        flash("工程を削除しました", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("phases_page"))


@app.route("/holidays", methods=["GET", "POST"])
def holidays() -> ResponseReturnValue:
    """祝日一覧を表示し、祝日の登録を処理する.

    Returns:
        ResponseReturnValue: holidays.html のレンダリング結果。
            POST 成功時は一覧へのリダイレクト。
    """
    if request.method == "POST":
        try:
            date_str = normalize_date(request.form.get("date"))
            name = (request.form.get("name") or "").strip()
            add_holiday(date_str, name)
            flash("祝日を登録しました", "ok")
            return redirect(url_for("holidays"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("holidays.html", holidays=list_holidays())


@app.post("/holidays/<date_str>/update")
def holidays_update(date_str: str) -> ResponseReturnValue:
    """祝日の名称を更新して一覧に戻る.

    Args:
        date_str (str): 更新対象の祝日の日付（YYYY-MM-DD）。

    Returns:
        ResponseReturnValue: 一覧へのリダイレクト。
    """
    try:
        name = (request.form.get("name") or "").strip()
        update_holiday(date_str, name)
        flash("祝日を更新しました", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("holidays"))


@app.post("/holidays/<date_str>/delete")
def holidays_delete(date_str: str) -> ResponseReturnValue:
    """祝日を削除して一覧に戻る.

    Args:
        date_str (str): 削除対象の祝日の日付（YYYY-MM-DD）。

    Returns:
        ResponseReturnValue: 一覧へのリダイレクト。
    """
    delete_holiday(date_str)
    flash("祝日を削除しました", "ok")
    return redirect(url_for("holidays"))


@app.route("/settings", methods=["GET", "POST"])
def settings_page() -> ResponseReturnValue:
    """アプリ設定を表示・保存する.

    Returns:
        ResponseReturnValue: settings.html のレンダリング結果。
            POST 成功時は設定画面へのリダイレクト。
    """
    if request.method == "POST":
        try:
            member_count = int(request.form.get("member_count") or "1")
            if member_count < 1:
                raise ValueError("メンバー人数は 1 以上にしてください")
            planned_utilization = float(request.form.get("planned_utilization") or "80")
            if planned_utilization <= 0 or planned_utilization > 100:
                raise ValueError("計画稼働率は 1〜100 の範囲で指定してください")
            display_from = normalize_ym(request.form.get("display_from"))
            display_to = normalize_ym(request.form.get("display_to"))
            if display_from > display_to:
                raise ValueError("表示開始月は終了月以前にしてください")
            theme = _normalize_theme(request.form.get("theme"))
            contract_name = (request.form.get("contract_name") or "").strip()
            update_settings(
                contract_name,
                member_count,
                display_from,
                display_to,
                planned_utilization,
                theme,
            )
            flash("設定を保存しました", "ok")
            return redirect(url_for("settings_page"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("settings.html", settings=get_settings())


@app.post("/settings/theme")
def settings_theme() -> ResponseReturnValue:
    """ヘッダーのテーマ切替を保存して元の画面に戻る.

    Returns:
        ResponseReturnValue: next パラメータで指定された画面へのリダイレクト。
    """
    try:
        theme = _normalize_theme(request.form.get("theme"))
        update_theme(theme)
    except ValueError as exc:
        flash(str(exc), "error")
    next_url = request.form.get("next") or url_for("schedule")
    if not next_url.startswith("/"):
        next_url = url_for("schedule")
    return redirect(next_url)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """起動時の CLI 引数（ポート・ブラウザ起動）を解析する.

    Args:
        argv (list[str] | None): 解析する引数リスト。None なら sys.argv を使う。

    Returns:
        argparse.Namespace: 解析結果（port / browser / no_browser）。
    """
    parser = argparse.ArgumentParser(description="スケジュール管理")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="N",
        help="待ち受けポート（省略時は空きポートを自動割当）",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="起動時にブラウザを開く",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="起動時にブラウザを開かない",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """ローカル Flask サーバーを起動し、必要に応じてブラウザを開く.

    Args:
        argv (list[str] | None): CLI 引数リスト。None なら sys.argv を使う。

    Returns:
        int: 終了コード。正常終了は 0、ポート指定が不正なら 2。
    """
    args = _parse_args(argv)
    host = "127.0.0.1"
    port = 0 if args.port is None else args.port
    if port < 0 or port > 65535:
        print("ポートは 0〜65535 で指定してください。", flush=True)
        return 2

    open_browser = is_frozen()
    if args.browser:
        open_browser = True
    if args.no_browser:
        open_browser = False

    server = make_server(host, port, app, threaded=True)
    actual_port = server.server_port
    url = f"http://{host}:{actual_port}/"

    print("スケジュール管理を起動しました。", flush=True)
    print(f"  URL: {url}", flush=True)
    print(f"  DB:  {DB_PATH}", flush=True)
    print("終了するには、このウィンドウを閉じるか Ctrl+C を押してください。", flush=True)

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
