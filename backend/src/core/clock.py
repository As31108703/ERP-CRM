"""時間工具：儲存與輸出用 UTC，週次以台北時間、週一為一週的第一天。"""

import re
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.core.problem import Problem, ensure

TAIPEI = ZoneInfo("Asia/Taipei")

# 只接受 ASCII 數字：YYYY-MM-DDTHH:MM:SS(.f{1,3})?(Z|±HH:MM)
_INSTANT_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|([+-])(\d{2}):(\d{2}))",
    re.ASCII,
)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

_TIME_INVALID = "office_time_invalid"
_WEEK_INVALID = "office_week_invalid"


def utcnow() -> datetime:
    """目前時間（UTC）。測試可用 monkeypatch 取代 `clock.utcnow`。"""
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """輸出 UTC、毫秒精度的 ISO 8601 字串，例如 `2026-11-02T01:00:00.000Z`。"""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("iso() 需要帶時區的 datetime")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_instant(s: str, *, minute_aligned: bool = False) -> datetime:
    """解析含時區的 ISO 日期時間，回傳 UTC datetime。

    不合法（格式、範圍、日期溢位如 2 月 30 日、時差超過 ±14:00）時拋出 422 office_time_invalid；
    minute_aligned 時秒數須為 00 且小數為 0。
    """
    ensure(isinstance(s, str), 422, _TIME_INVALID, "請填含時區的 ISO 日期時間")
    m = _INSTANT_RE.fullmatch(s)
    ensure(m is not None, 422, _TIME_INVALID, "請填含時區的 ISO 日期時間")
    year, month, day, hour, minute, second, fraction, zone, sign, zh, zm = m.groups()
    off_h, off_m = int(zh or 0), int(zm or 0)
    ensure(
        int(year) >= 1
        and int(hour) <= 23
        and int(minute) <= 59
        and int(second) <= 59
        and off_h <= 14
        and off_m <= 59
        and (off_h != 14 or off_m == 0),
        422,
        _TIME_INVALID,
        "日期時間不合法",
    )
    offset = timedelta(hours=off_h, minutes=off_m)
    if sign == "-":
        offset = -offset
    micro = int((fraction or "0").ljust(6, "0"))
    try:
        local = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            micro,
            tzinfo=UTC if zone == "Z" else timezone(offset),
        )
        result = local.astimezone(UTC)
    except (ValueError, OverflowError):
        # 月份或日期溢位（例如 2 月 30 日），或換算 UTC 後超出可表示範圍
        raise Problem(422, _TIME_INVALID, "日期時間不合法") from None
    if minute_aligned:
        ensure(
            second == "00" and micro == 0,
            422,
            _TIME_INVALID,
            "排班、出勤與借用時間須對齊整分鐘",
        )
    return result


def taipei_monday(s: str) -> datetime:
    """`YYYY-MM-DD` 且為台北日曆的週一，回傳該日台北 00:00；否則 422 office_week_invalid。"""
    ensure(
        isinstance(s, str) and _DATE_RE.fullmatch(s) is not None,
        422,
        _WEEK_INVALID,
        "週日期須使用 YYYY-MM-DD",
    )
    try:
        start = parse_instant(f"{s}T00:00:00+08:00").astimezone(TAIPEI)
    except Problem:
        raise Problem(422, _WEEK_INVALID, "週日期不合法") from None
    ensure(start.weekday() == 0, 422, _WEEK_INVALID, "週起始日期須為週一")
    return start
