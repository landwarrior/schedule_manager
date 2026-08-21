"""Business-day and period helpers for early / mid / late month decades."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Iterable

DECADE_LABELS = {1: "上旬", 2: "中旬", 3: "下旬"}
PHASES_WITH_EFFORT = (
    ("design", "設計"),
    ("impl", "実装"),
    ("unit", "単体・内部結合"),
    ("release", "本番リリース"),
)
PHASE_KEYS = [key for key, _ in PHASES_WITH_EFFORT]


def decade_day_range(year: int, month: int, decade: int) -> tuple[int, int]:
    last_day = calendar.monthrange(year, month)[1]
    if decade == 1:
        return 1, min(10, last_day)
    if decade == 2:
        return 11, min(20, last_day)
    if decade == 3:
        return 21, last_day
    raise ValueError(f"invalid decade: {decade}")


def parse_ym(ym: str) -> tuple[int, int]:
    year_s, month_s = ym.split("-")
    return int(year_s), int(month_s)


def format_ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def normalize_ym(value: str | None) -> str:
    """Accept YYYY-MM or YYYY/MM and return YYYY-MM."""
    if value is None:
        raise ValueError("月が未入力です")
    text = value.strip().replace("/", "-")
    year, month = parse_ym(text)
    if month < 1 or month > 12:
        raise ValueError("月の形式が不正です（YYYY-MM）")
    return format_ym(year, month)


def normalize_date(value: str | None) -> str:
    """Accept YYYY-MM-DD or YYYY/MM/DD and return YYYY-MM-DD."""
    if value is None:
        raise ValueError("日付が未入力です")
    text = value.strip().replace("/", "-")
    parts = text.split("-")
    if len(parts) != 3:
        raise ValueError("日付の形式が不正です（YYYY-MM-DD）")
    year, month, day = (int(parts[0]), int(parts[1]), int(parts[2]))
    parsed = date(year, month, day)
    return parsed.isoformat()


def iter_months(from_ym: str, to_ym: str) -> list[str]:
    year, month = parse_ym(from_ym)
    end_year, end_month = parse_ym(to_ym)
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(format_ym(year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def period_key(ym: str, decade: int) -> str:
    return f"{ym}:{decade}"


def period_tuple(ym: str, decade: int) -> tuple[str, int]:
    return ym, decade


def compare_periods(a_ym: str, a_decade: int, b_ym: str, b_decade: int) -> int:
    a = (parse_ym(a_ym)[0], parse_ym(a_ym)[1], a_decade)
    b = (parse_ym(b_ym)[0], parse_ym(b_ym)[1], b_decade)
    return (a > b) - (a < b)


def is_period_in_range(
    ym: str,
    decade: int,
    start_ym: str | None,
    start_decade: int | None,
    end_ym: str | None,
    end_decade: int | None,
) -> bool:
    if not start_ym or not start_decade or not end_ym or not end_decade:
        return False
    if compare_periods(ym, decade, start_ym, start_decade) < 0:
        return False
    if compare_periods(ym, decade, end_ym, end_decade) > 0:
        return False
    return True


def business_days(ym: str, decade: int, holidays: Iterable[str]) -> int:
    """Count weekdays in the decade excluding holiday dates (YYYY-MM-DD)."""
    year, month = parse_ym(ym)
    start_day, end_day = decade_day_range(year, month, decade)
    holiday_set = set(holidays)
    count = 0
    for day in range(start_day, end_day + 1):
        d = date(year, month, day)
        if d.weekday() >= 5:
            continue
        if d.isoformat() in holiday_set:
            continue
        count += 1
    return count


def capacity(ym: str, decade: int, holidays: Iterable[str], member_count: int) -> float:
    return business_days(ym, decade, holidays) * member_count


def allocation_status(allocated: float, capacity_value: float, safety_rate_percent: float) -> str:
    """Return '' | 'warn' | 'over' for capacity coloring.

    - over: allocated >= capacity
    - warn: allocated > capacity * safety_rate / 100
    """
    allocated = round_effort(allocated)
    capacity_value = float(capacity_value)
    threshold = round_effort(capacity_value * float(safety_rate_percent) / 100.0)
    if allocated >= capacity_value:
        return "over"
    if allocated > threshold:
        return "warn"
    return ""


def round_effort(value: float) -> float:
    return round(value + 1e-9, 1)


def is_valid_effort(value: float) -> bool:
    if value < 0:
        return False
    # Allow 0.1 increments
    tenths = round(value * 10)
    return abs(value * 10 - tenths) < 1e-9
