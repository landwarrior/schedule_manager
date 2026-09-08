"""上旬・中旬・下旬の期間と営業日まわりのヘルパー."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date

DECADE_LABELS = {1: "上旬", 2: "中旬", 3: "下旬"}
PHASE_INPUT_MODES = ("period", "effort")
PHASE_COLORS = ("cyan", "orange", "green", "lavender")
PHASE_COLOR_LABELS = {
    "cyan": "水色",
    "orange": "橙色",
    "green": "緑色",
    "lavender": "藤色",
}
DEFAULT_PHASES = (
    ("design", "設計", "effort", "cyan", 1),
    ("impl", "実装", "effort", "cyan", 2),
    ("unit", "単体テスト", "effort", "cyan", 3),
    ("integration", "結合試験", "period", "orange", 4),
    ("release", "本番リリース", "effort", "cyan", 5),
)


def decade_day_range(year: int, month: int, decade: int) -> tuple[int, int]:
    """指定月の旬に対応する日付範囲（開始日・終了日、両端を含む）を返す.

    Args:
        year (int): 対象の年。
        month (int): 対象の月（1〜12）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。

    Returns:
        tuple[int, int]: (開始日, 終了日) のタプル。

    Raises:
        ValueError: decade が 1, 2, 3 以外の場合。
    """
    last_day = calendar.monthrange(year, month)[1]
    if decade == 1:
        return 1, min(10, last_day)
    if decade == 2:
        return 11, min(20, last_day)
    if decade == 3:
        return 21, last_day
    raise ValueError(f"invalid decade: {decade}")


def parse_ym(ym: str) -> tuple[int, int]:
    """YYYY-MM 形式の文字列を (年, 月) のタプルに変換する.

    Args:
        ym (str): YYYY-MM 形式の年月文字列。

    Returns:
        tuple[int, int]: (年, 月) のタプル。
    """
    year_s, month_s = ym.split("-")
    return int(year_s), int(month_s)


def format_ym(year: int, month: int) -> str:
    """年・月を YYYY-MM 形式の文字列に整形する.

    Args:
        year (int): 年。
        month (int): 月（1〜12）。

    Returns:
        str: YYYY-MM 形式の文字列。
    """
    return f"{year:04d}-{month:02d}"


def normalize_ym(value: str | None) -> str:
    """YYYY-MM または YYYY/MM を受け取り、YYYY-MM に正規化する.

    Args:
        value (str | None): 年月を表す文字列（YYYY-MM / YYYY/MM）。

    Returns:
        str: YYYY-MM 形式の文字列。

    Raises:
        ValueError: 未入力、または形式・月の値が不正な場合。
    """
    if value is None:
        raise ValueError("月が未入力です")
    text = value.strip().replace("/", "-")
    year, month = parse_ym(text)
    if month < 1 or month > 12:
        raise ValueError("月の形式が不正です（YYYY-MM）")
    return format_ym(year, month)


def normalize_date(value: str | None) -> str:
    """YYYY-MM-DD または YYYY/MM/DD を受け取り、YYYY-MM-DD に正規化する.

    Args:
        value (str | None): 日付を表す文字列（YYYY-MM-DD / YYYY/MM/DD）。

    Returns:
        str: YYYY-MM-DD 形式の文字列。

    Raises:
        ValueError: 未入力、または形式・日付が不正な場合。
    """
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
    """from_ym から to_ym まで（両端を含む）の YYYY-MM を並べたリストを返す.

    Args:
        from_ym (str): 開始年月（YYYY-MM）。
        to_ym (str): 終了年月（YYYY-MM）。

    Returns:
        list[str]: 年月文字列のリスト（昇順）。
    """
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
    """年月と旬から一意な文字列キーを作る.

    Args:
        ym (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。

    Returns:
        str: ``{ym}:{decade}`` 形式のキー文字列。
    """
    return f"{ym}:{decade}"


def period_tuple(ym: str, decade: int) -> tuple[str, int]:
    """(ym, decade) のタプルとして返す.

    Args:
        ym (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。

    Returns:
        tuple[str, int]: (ym, decade) のタプル。
    """
    return ym, decade


def compare_periods(a_ym: str, a_decade: int, b_ym: str, b_decade: int) -> int:
    """2 つの期間（年月＋旬）を比較する.

    Args:
        a_ym (str): 比較元の年月（YYYY-MM）。
        a_decade (int): 比較元の旬。
        b_ym (str): 比較先の年月（YYYY-MM）。
        b_decade (int): 比較先の旬。

    Returns:
        int: a < b なら -1、等しければ 0、a > b なら 1。
    """
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
    """(ym, decade) が開始期間〜終了期間の範囲内かを判定する.

    Args:
        ym (str): 判定対象の年月（YYYY-MM）。
        decade (int): 判定対象の旬。
        start_ym (str | None): 期間開始の年月。未設定なら False を返す。
        start_decade (int | None): 期間開始の旬。
        end_ym (str | None): 期間終了の年月。未設定なら False を返す。
        end_decade (int | None): 期間終了の旬。

    Returns:
        bool: 範囲内なら True。開始・終了のいずれかが未設定でも False。
    """
    if not start_ym or not start_decade or not end_ym or not end_decade:
        return False
    if compare_periods(ym, decade, start_ym, start_decade) < 0:
        return False
    if compare_periods(ym, decade, end_ym, end_decade) > 0:  # noqa: SIM103
        return False
    return True


def business_days(ym: str, decade: int, holidays: Iterable[str]) -> int:
    """旬内の営業日数を数える（土日と祝日マスタの日付を除く）.

    Args:
        ym (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        holidays (Iterable[str]): 祝日の日付文字列（YYYY-MM-DD）の集合。

    Returns:
        int: 営業日数。
    """
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
    """旬のキャパシティ（営業日数 × メンバー人数）を返す.

    Args:
        ym (str): 年月（YYYY-MM）。
        decade (int): 旬（1=上旬, 2=中旬, 3=下旬）。
        holidays (Iterable[str]): 祝日の日付文字列（YYYY-MM-DD）の集合。
        member_count (int): メンバー人数。

    Returns:
        float: キャパシティ（人日）。
    """
    return business_days(ym, decade, holidays) * member_count


def allocation_status(allocated: float, capacity_value: float, planned_utilization_percent: float) -> str:
    """キャパシティ超過度合いから表示色用のステータスを返す.

    - ``"over"``: 割当工数がキャパシティ以上
    - ``"warn"``: 割当工数が キャパシティ × 計画稼働率(%) / 100 を超過
    - ``""``: 上記以外

    Args:
        allocated (float): 割当工数の合計（人日）。
        capacity_value (float): 旬のキャパシティ（人日）。
        planned_utilization_percent (float): 計画稼働率（パーセント）。

    Returns:
        str: ``""`` / ``"warn"`` / ``"over"`` のいずれか。
    """
    allocated = round_effort(allocated)
    capacity_value = float(capacity_value)
    threshold = round_effort(capacity_value * float(planned_utilization_percent) / 100.0)
    if allocated >= capacity_value:
        return "over"
    if allocated > threshold:
        return "warn"
    return ""


def round_effort(value: float) -> float:
    """工数を小数 1 桁（0.1 人日刻み）に丸める.

    Args:
        value (float): 工数（人日）。

    Returns:
        float: 0.1 刻みに丸めた工数。
    """
    return round(value + 1e-9, 1)


def is_valid_effort(value: float) -> bool:
    """工数が 0 以上かつ 0.1 の倍数かを判定する.

    Args:
        value (float): 工数（人日）。

    Returns:
        bool: 有効な工数なら True。
    """
    if value < 0:
        return False
    tenths = round(value * 10)
    return abs(value * 10 - tenths) < 1e-9


def normalize_phase_input_mode(value: str | None) -> str:
    """工程の入力方式を正規化する.

    Args:
        value (str | None): 入力方式（``"period"`` / ``"effort"``）。

    Returns:
        str: 有効な入力方式。不明な値は ``"effort"`` にフォールバック。
    """
    if value in PHASE_INPUT_MODES:
        return value
    return "effort"


def normalize_phase_color(value: str | None) -> str:
    """工程の色を正規化する.

    Args:
        value (str | None): 色名（cyan / orange / green / lavender）。

    Returns:
        str: 有効な色名。不明な値は ``"cyan"`` にフォールバック。
    """
    if value in PHASE_COLORS:
        return value
    return "cyan"
