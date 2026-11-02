"""行政欄位驗證器（A§0）。失敗時拋出 Problem，錯誤碼照 A§0。"""

import re
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from src.core import clock
from src.core.problem import Problem, ensure
from src.platform.records import FINANCE_KEY_RE, PROTECTED_KEYS

INT_MAX = 1_000_000_000
DEFAULT_MAX_MINUTES = 48 * 60
LONG_MAX_MINUTES = 31 * 24 * 60
BREAK_MAX = 48 * 60

_FORBIDDEN_KEYS = {"__proto__", "prototype", "constructor"}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I | re.ASCII
)

# B§3.1 通用前置檢查：金融鍵名與保護欄位沿用 platform.records 的共用定義。
# 行政命令不套用 records.precheck 的整數正規化與產品／教學檢查（行政欄位型別較嚴格）。


def precheck(payload: dict[str, Any]) -> None:
    """行政命令執行前的通用檢查：金融鍵名回 simulation_required，保護欄位回 protected_field。"""
    for key in payload:
        ensure(
            not FINANCE_KEY_RE.search(key),
            422,
            "simulation_required",
            "此模擬工作台不處理真實金融資料",
        )
    for key in payload:
        ensure(key not in PROTECTED_KEYS, 422, "protected_field", "這個欄位由系統維護，不能指定")


def strict_keys(payload: Any, required: set[str], optional: set[str]) -> None:
    """只允許 required + optional 的鍵，且 required 必須齊全；否則 422 office_fields_invalid。"""
    ensure(isinstance(payload, dict), 422, "office_fields_invalid", "行政欄位格式不符")
    ensure(
        all(isinstance(k, str) and k not in _FORBIDDEN_KEYS for k in payload),
        422,
        "office_fields_invalid",
        "不允許此行政欄位",
    )
    allowed = required | optional
    ensure(
        all(k in allowed for k in payload) and required.issubset(payload),
        422,
        "office_fields_invalid",
        "行政欄位缺漏或包含不允許的欄位",
    )


def editable(payload: dict[str, Any]) -> None:
    """更新命令除了 id 之外至少要有一個欄位。"""
    ensure(len(payload) > 1, 422, "office_fields_invalid", "請指定要更新的欄位")


def text(v: Any, max: int = 100, allow_empty: bool = False) -> str:  # noqa: A002
    ensure(
        isinstance(v, str)
        and len(v) <= max
        and (allow_empty or v.strip() != "")
        and _CONTROL_RE.search(v) is None,
        422,
        "office_text_invalid",
        "行政文字缺漏或超出長度",
    )
    return v


def enum_value(v: Any, allowed: Iterable[str]) -> str:
    ensure(
        isinstance(v, str) and v in tuple(allowed),
        422,
        "office_state_invalid",
        "行政種類或狀態不符",
    )
    return v


def integer(v: Any, min: int = 0, max: int = INT_MAX) -> int:  # noqa: A002
    """範圍內整數；與 JSON 數字語意一致，1.0 視為 1，布林值不算整數。"""
    ok = False
    if isinstance(v, bool):
        ok = False
    elif isinstance(v, int):
        ok = True
    elif isinstance(v, float) and v.is_integer():
        v = int(v)
        ok = True
    ensure(ok and min <= v <= max, 422, "office_number_invalid", "行政數值須為範圍內整數")
    return int(v)


def boolean(v: Any, message: str = "行政布林欄位不符") -> bool:
    ensure(isinstance(v, bool), 422, "office_fields_invalid", message)
    return v


def uuid_value(v: Any) -> str:
    """UUID 字串（版本 1–8），回傳小寫正規形式；否則 422 office_id_invalid。"""
    ensure(
        isinstance(v, str) and _UUID_RE.fullmatch(v) is not None,
        422,
        "office_id_invalid",
        "行政識別格式不符",
    )
    return str(uuid.UUID(v))


def optional_uuid(v: Any) -> str | None:
    return None if v is None else uuid_value(v)


def instant(v: Any, *, minute_aligned: bool = False) -> datetime:
    return clock.parse_instant(v, minute_aligned=minute_aligned)


def optional_instant(v: Any) -> datetime | None:
    return None if v is None else instant(v)


def interval(
    start: Any, end: Any, *, max_minutes: int = DEFAULT_MAX_MINUTES
) -> tuple[datetime, datetime]:
    """半開區間 [start, end)：兩端須對齊整分鐘，end > start 且長度不超過 max_minutes。"""
    s = instant(start, minute_aligned=True)
    e = instant(end, minute_aligned=True)
    label = "48 小時" if max_minutes == DEFAULT_MAX_MINUTES else "31 天"
    ensure(
        e > s and (e - s).total_seconds() <= max_minutes * 60,
        422,
        "office_interval_invalid",
        f"結束須晚於開始，單筆時段最多 {label}",
    )
    return s, e


def break_minutes(v: Any, start: datetime, end: datetime) -> int:
    """休息分鐘：0–2880 的整數，且須少於整段時間的分鐘數。"""
    minutes = integer(v, 0, BREAK_MAX)
    if minutes * 60 >= (end - start).total_seconds():
        raise Problem(422, "office_break_invalid", "休息分鐘須少於整段時間")
    return minutes
