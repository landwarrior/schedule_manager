"""Schedule manager web application."""

from __future__ import annotations

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from calendar_util import (
    DECADE_LABELS,
    PHASES_WITH_EFFORT,
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
from db import init_db
from models import (
    add_holiday,
    create_project,
    delete_holiday,
    delete_project,
    get_project,
    get_settings,
    list_allocations,
    list_holiday_dates,
    list_holidays,
    list_projects,
    allocated_totals_by_project_phase,
    set_allocation,
    update_project,
    update_settings,
    update_theme,
)

app = Flask(__name__)
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
    }


def _parse_effort(raw: str | None) -> float:
    if raw is None or str(raw).strip() == "":
        return 0.0
    value = round_effort(float(raw))
    if not is_valid_effort(value):
        raise ValueError("工数は 0.1 刻みで入力してください")
    return value


def _parse_decade(raw: str | None) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    value = int(raw)
    if value not in (1, 2, 3):
        raise ValueError("旬が不正です")
    return value


def _form_totals(form) -> dict[str, float]:
    return {key: _parse_effort(form.get(f"total_{key}")) for key, _ in PHASES_WITH_EFFORT}


def _form_test_t(form) -> dict:
    start_raw = (form.get("test_t_start_ym") or "").strip()
    end_raw = (form.get("test_t_end_ym") or "").strip()
    return {
        "start_ym": normalize_ym(start_raw) if start_raw else None,
        "start_decade": _parse_decade(form.get("test_t_start_decade")),
        "end_ym": normalize_ym(end_raw) if end_raw else None,
        "end_decade": _parse_decade(form.get("test_t_end_decade")),
    }


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
    for (project_id, phase, ym, decade), effort in allocations.items():
        if (ym, decade) in period_totals:
            period_totals[(ym, decade)] = round_effort(
                period_totals[(ym, decade)] + effort
            )

    project_rows = []
    for project in projects:
        phases = []
        for phase_key, phase_label in PHASES_WITH_EFFORT:
            cells = []
            allocated = allocated_sums.get((project["id"], phase_key), 0.0)
            total = project["totals"].get(phase_key, 0.0)
            for ym, decade in columns:
                effort = allocations.get((project["id"], phase_key, ym, decade), 0.0)
                cells.append(
                    {
                        "ym": ym,
                        "decade": decade,
                        "effort": effort,
                    }
                )
            phases.append(
                {
                    "key": phase_key,
                    "label": phase_label,
                    "total": total,
                    "allocated": round_effort(allocated),
                    "diff": round_effort(total - allocated),
                    "cells": cells,
                }
            )

        test_t = project["test_t"]
        test_t_cells = []
        for ym, decade in columns:
            active = is_period_in_range(
                ym,
                decade,
                test_t.get("start_ym"),
                test_t.get("start_decade"),
                test_t.get("end_ym"),
                test_t.get("end_decade"),
            )
            test_t_cells.append({"ym": ym, "decade": decade, "active": active})

        project_rows.append(
            {
                "id": project["id"],
                "name": project["name"],
                "phases": phases,
                "test_t_cells": test_t_cells,
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

    return render_template(
        "schedule.html",
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
        phase = data["phase"]
        year_month = data["year_month"]
        decade = int(data["decade"])
        effort = _parse_effort(str(data.get("effort", 0)))
        parse_ym(year_month)
        set_allocation(project_id, phase, year_month, decade, effort)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    settings = get_settings()
    holidays = list_holiday_dates()
    # Recalculate period total for the changed cell using all projects in that period
    with_period = list_allocations(year_month, year_month)
    period_total = round_effort(
        sum(
            e
            for (_pid, _phase, ym, d), e in with_period.items()
            if ym == year_month and d == decade
        )
    )
    cap = capacity(year_month, decade, holidays, settings["member_count"])
    biz = business_days(year_month, decade, holidays)
    safety_rate = float(
        settings["safety_rate"] if settings["safety_rate"] is not None else 80
    )
    status = allocation_status(period_total, cap, safety_rate)
    allocated_sums = allocated_totals_by_project_phase()
    project = get_project(project_id)
    phase_allocated = round_effort(allocated_sums.get((project_id, phase), 0.0))
    phase_total = project["totals"].get(phase, 0.0) if project else 0.0

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


@app.route("/projects")
def projects_list():
    projects = list_projects()
    allocated = allocated_totals_by_project_phase()
    return render_template(
        "projects.html",
        projects=projects,
        allocated=allocated,
        phases=PHASES_WITH_EFFORT,
        decade_labels=DECADE_LABELS,
    )


@app.route("/projects/new", methods=["GET", "POST"])
def projects_new():
    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            if not name:
                raise ValueError("プロジェクト名は必須です")
            totals = _form_totals(request.form)
            test_t = _form_test_t(request.form)
            create_project(name, totals, test_t)
            flash("プロジェクトを作成しました", "ok")
            return redirect(url_for("projects_list"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template(
        "project_form.html",
        mode="new",
        project=None,
        phases=PHASES_WITH_EFFORT,
        decade_labels=DECADE_LABELS,
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
            totals = _form_totals(request.form)
            test_t = _form_test_t(request.form)
            update_project(project_id, name, totals, test_t)
            flash("プロジェクトを更新しました", "ok")
            return redirect(url_for("projects_list"))
        except ValueError as exc:
            flash(str(exc), "error")
            project = get_project(project_id)
    return render_template(
        "project_form.html",
        mode="edit",
        project=project,
        phases=PHASES_WITH_EFFORT,
        decade_labels=DECADE_LABELS,
    )


@app.post("/projects/<int:project_id>/delete")
def projects_delete(project_id: int):
    delete_project(project_id)
    flash("プロジェクトを削除しました", "ok")
    return redirect(url_for("projects_list"))


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
            update_settings(member_count, display_from, display_to, safety_rate, theme)
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
