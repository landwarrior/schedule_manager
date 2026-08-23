"""Schedule manager web application."""

from __future__ import annotations

import argparse
import threading
import webbrowser

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
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
    allocated_totals_by_project_phase,
    create_phase_definition,
    create_project,
    delete_holiday,
    delete_phase_definition,
    delete_project,
    get_phase_definition,
    get_project,
    get_settings,
    list_allocations,
    list_holiday_dates,
    list_holidays,
    list_phase_definitions,
    list_projects,
    phase_input_mode_label,
    reorder_phase_definitions,
    reorder_projects,
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
    theme = (raw or "system").strip().lower()
    if theme not in THEME_CHOICES:
        raise ValueError("テーマの指定が不正です")
    return theme


@app.context_processor
def inject_theme():
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
    if raw is None:
        raise ValueError(message)
    text = raw.strip()
    if not text:
        raise ValueError(message)
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(message) from exc


def _parse_project_phases(form) -> list[dict]:
    order_raw = (form.get("phase_order") or "").strip()
    if not order_raw:
        raise ValueError("工程の並び順が不正です")
    phase_ids = [int(part) for part in order_raw.split(",") if part.strip()]
    if not phase_ids:
        raise ValueError("工程の並び順が不正です")

    configs: list[dict] = []
    enabled_count = 0
    for phase_id in phase_ids:
        phase = get_phase_definition(phase_id)
        if phase is None:
            raise ValueError("工程が不正です")
        enabled = form.get(f"enabled_{phase_id}") == "1"
        if enabled:
            enabled_count += 1
        config: dict = {"phase_id": phase_id, "enabled": enabled}
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


def _build_schedule_phase_rows(project: dict, columns, allocations, allocated_sums) -> list[dict]:
    rows = []
    for phase in project["phases"]:
        if not phase.get("enabled", True):
            continue
        phase_id = phase["phase_id"]
        if phase["input_mode"] == "effort":
            cells = []
            allocated = allocated_sums.get((project["id"], phase_id), 0.0)
            total = float(phase["total_effort"] or 0.0)
            for ym, decade in columns:
                effort = allocations.get((project["id"], phase_id, ym, decade), 0.0)
                cells.append({"ym": ym, "decade": decade, "effort": effort, "active": effort > 0})
            rows.append(
                {
                    "id": phase_id,
                    "name": phase["name"],
                    "input_mode": "effort",
                    "color": phase["color"],
                    "total": total,
                    "allocated": round_effort(allocated),
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
def schedule():
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
    safety_rate = float(settings["safety_rate"] if settings["safety_rate"] is not None else 80)

    capacities = {
        (ym, decade): {
            "business_days": business_days(ym, decade, holidays),
            "capacity": capacity(ym, decade, holidays, member_count),
        }
        for ym, decade in columns
    }

    projects = list_projects()
    allocations = list_allocations(display_from, display_to)
    allocated_sums = allocated_totals_by_project_phase()

    period_totals: dict[tuple[str, int], float] = {(ym, d): 0.0 for ym, d in columns}
    for (_project_id, _phase_id, ym, decade), effort in allocations.items():
        if (ym, decade) in period_totals:
            period_totals[(ym, decade)] = round_effort(period_totals[(ym, decade)] + effort)

    project_rows = []
    for project in projects:
        phases = _build_schedule_phase_rows(project, columns, allocations, allocated_sums)
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
        status = allocation_status(allocated, cap["capacity"], safety_rate)
        summary.append(
            {
                "ym": ym,
                "decade": decade,
                "business_days": cap["business_days"],
                "capacity": cap["capacity"],
                "allocated": allocated,
                "status": status,
                "warn_threshold": round_effort(cap["capacity"] * safety_rate / 100.0),
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
        safety_rate=safety_rate,
    )


@app.post("/api/allocations")
def api_set_allocation():
    data = request.get_json(force=True, silent=True) or {}
    try:
        project_id = int(data["project_id"])
        phase_id = int(data["phase_id"])
        year_month = data["year_month"]
        decade = int(data["decade"])
        effort = _parse_effort(str(data.get("effort", 0)))
        parse_ym(year_month)
        set_allocation(project_id, phase_id, year_month, decade, effort)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    settings = get_settings()
    holidays = list_holiday_dates()
    with_period = list_allocations(year_month, year_month)
    period_total = round_effort(
        sum(e for (_pid, _phase, ym, d), e in with_period.items() if ym == year_month and d == decade)
    )
    cap = capacity(year_month, decade, holidays, settings["member_count"])
    biz = business_days(year_month, decade, holidays)
    safety_rate = float(settings["safety_rate"] if settings["safety_rate"] is not None else 80)
    status = allocation_status(period_total, cap, safety_rate)
    allocated_sums = allocated_totals_by_project_phase()
    project = get_project(project_id)
    phase_total = 0.0
    if project:
        for phase in project["phases"]:
            if phase["phase_id"] == phase_id:
                phase_total = float(phase["total_effort"] or 0.0)
                break
    phase_allocated = round_effort(allocated_sums.get((project_id, phase_id), 0.0))

    return jsonify(
        {
            "ok": True,
            "effort": effort,
            "period": {
                "year_month": year_month,
                "decade": decade,
                "allocated": period_total,
                "capacity": cap,
                "business_days": biz,
                "status": status,
            },
            "phase": {
                "allocated": phase_allocated,
                "total": phase_total,
                "diff": round_effort(phase_total - phase_allocated),
            },
        }
    )


@app.route("/projects", methods=["GET", "POST"])
def projects_list():
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
def projects_new():
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
def projects_edit(project_id: int):
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
def projects_delete(project_id: int):
    delete_project(project_id)
    flash("プロジェクトを削除しました", "ok")
    return redirect(url_for("projects_list"))


@app.route("/phases", methods=["GET", "POST"])
def phases_page():
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
def phases_delete(phase_id: int):
    try:
        delete_phase_definition(phase_id)
        flash("工程を削除しました", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("phases_page"))


@app.route("/holidays", methods=["GET", "POST"])
def holidays():
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
def holidays_update(date_str: str):
    try:
        name = (request.form.get("name") or "").strip()
        update_holiday(date_str, name)
        flash("祝日を更新しました", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("holidays"))


@app.post("/holidays/<date_str>/delete")
def holidays_delete(date_str: str):
    delete_holiday(date_str)
    flash("祝日を削除しました", "ok")
    return redirect(url_for("holidays"))


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        try:
            member_count = int(request.form.get("member_count") or "1")
            if member_count < 1:
                raise ValueError("メンバー人数は 1 以上にしてください")
            safety_rate = float(request.form.get("safety_rate") or "80")
            if safety_rate <= 0 or safety_rate > 100:
                raise ValueError("安全率は 1〜100 の範囲で指定してください")
            display_from = normalize_ym(request.form.get("display_from"))
            display_to = normalize_ym(request.form.get("display_to"))
            if display_from > display_to:
                raise ValueError("表示開始月は終了月以前にしてください")
            theme = _normalize_theme(request.form.get("theme"))
            contract_name = (request.form.get("contract_name") or "").strip()
            update_settings(contract_name, member_count, display_from, display_to, safety_rate, theme)
            flash("設定を保存しました", "ok")
            return redirect(url_for("settings_page"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("settings.html", settings=get_settings())


@app.post("/settings/theme")
def settings_theme():
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
