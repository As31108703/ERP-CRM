"""行政 CSV 匯出（A§6）：只匯出目前分頁的篩選結果。

格式：UTF-8 加 BOM、CRLF 換行、每格都加雙引號（內含引號加倍）。每列＝12 個範圍欄＋
分頁資料欄＋3 個共通欄。可能被試算表當成公式的格子前面加 `'`。
"""

import re
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from src.modules.administration import views
from src.modules.administration.views import (
    REQUEST_NAMES,
    STATUS_LABELS,
    TAB_LABELS,
    Desk,
    ViewParams,
    format_dt,
    net_minutes,
)

# JS 的 \s 也涵蓋 U+FEFF；Python 的 \s 不含，另外列出
_FORMULA = re.compile(r"[\s\ufeff\x00-\x1f]*[=+\-@]")

MODE = "SIM 流程練習"
TIMEZONE = "Asia/Taipei（UTC+08:00）"
SOURCE = "目前訪客工作區的模擬紀錄；僅匯出目前篩選結果"
SCOPE_HEADERS = (
    "模式",
    "工作區",
    "工作區版本",
    "資料類型",
    "組織範圍",
    "搜尋條件",
    "狀態篩選",
    "日期範圍",
    "時區",
    "產出時間",
    "篩選統計",
    "資料來源",
)
COMMON_HEADERS = ("建立時間（臺北）", "更新時間（臺北）", "更正與保留紀錄")
TIME_HEADERS = ("開始時間（臺北）", "結束時間（臺北）")
TAB_HEADERS: dict[str, tuple[str, ...]] = {
    "units": ("紀錄編號", "組織名稱", "類型", "所屬門市", "狀態"),
    "staff": ("紀錄編號", "假員工代號", "假員工暱稱", "組織", "職務稱呼", "狀態"),
    "shifts": (
        "紀錄編號",
        "假員工",
        "組織",
        *TIME_HEADERS,
        "休息分鐘",
        "原段淨分鐘",
        "有效分鐘",
        "狀態",
        "備註",
    ),
    "requests": (
        "紀錄編號",
        "申請類型",
        "組織",
        "假員工",
        "標題",
        "內容",
        "SIM 測試幣金額",
        *TIME_HEADERS,
        "狀態",
        "最新退回原因",
        "申請狀態紀錄",
    ),
    "equipment": ("紀錄編號", "設備代號", "設備名稱", "組織", "狀態"),
    "reservations": ("紀錄編號", "設備", "假員工", *TIME_HEADERS, "借用用途", "狀態"),
    "notices": (
        "紀錄編號",
        "公告標題",
        "內容",
        "公告對象",
        "置頂設定",
        "截止時間（臺北）",
        "公告狀態",
    ),
}
TAB_HEADERS["attendance"] = TAB_HEADERS["shifts"]

CHANGE_NAMES = {
    "shift.update": "班次時段更正",
    "attendance.update": "手動出勤更正",
    "attendance.void": "手動出勤作廢",
    "reservation.update": "設備預約更改",
    "notice.archive": "公告封存",
    "notice.restore": "公告還原",
}


def guard(value: str) -> str:
    """防公式注入：符合 `^[\\s\\x00-\\x1f]*[=+\\-@]` 或以 tab、CR 開頭的格子前面加 `'`。"""
    if _FORMULA.match(value) or value[:1] in ("\t", "\r"):
        return f"'{value}"
    return value


def _cell(raw: Any) -> str:
    value = "" if raw is None else str(raw)
    return '"' + guard(value).replace('"', '""') + '"'


def to_csv(rows: Sequence[Sequence[Any]]) -> str:
    return "\ufeff" + "".join(",".join(_cell(c) for c in row) + "\r\n" for row in rows)


def filename(tab: str, now: datetime) -> str:
    return f"erpcrm-admin-{tab}-{views.taipei_date(now)}.csv"


# --- 欄位內容 ------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "未填寫" if value is None or value == "" else str(value)


Field = tuple[str, str, Callable[[Any], str]]
_TIME_FIELDS: tuple[Field, ...] = (
    ("start_at", "開始時間", format_dt),
    ("end_at", "結束時間", format_dt),
)


def _history_fields(kind: str) -> tuple[Field, ...]:
    if kind.startswith("notice."):
        return (
            ("archived", "公告狀態", lambda x: "已封存" if x else "發布中"),
            ("pinned", "置頂設定", lambda x: "置頂" if x else "一般"),
            ("due_at", "截止時間", format_dt),
        )
    if kind == "reservation.update":
        return (*_TIME_FIELDS, ("purpose", "借用用途", _text))
    fields = (*_TIME_FIELDS, ("break_minutes", "休息分鐘", _text), ("note", "備註", _text))
    if kind.startswith("attendance."):
        fields = (*fields, ("voided", "出勤紀錄", lambda x: "已作廢" if x else "有效紀錄"))
    return fields


def _change_line(change: dict[str, Any]) -> str:
    before, after = change["before"], change["after"]
    diffs = "；".join(
        f"{label} {fmt(before.get(key))} → {fmt(after.get(key))}"
        for key, label, fmt in _history_fields(change["kind"])
    )
    return f"{format_dt(change['at'])} {CHANGE_NAMES[change['kind']]}：{change['reason']}；{diffs}"


class _Names:
    """CSV 備援名稱：缺組織「原組織」（null 為「全體」）、缺設備「原設備」、缺假員工「未指定」。"""

    def __init__(self, desk: Desk) -> None:
        self.desk = desk

    def unit(self, unit_id: str | None) -> str:
        if unit_id is None:
            return "全體"
        row = self.desk.units.get(unit_id)
        return row["name"] if row else "原組織"

    def staff(self, staff_id: str | None) -> str:
        return self.desk.staff_name(staff_id)

    def equipment(self, equipment_id: str) -> str:
        row = self.desk.equipment.get(equipment_id)
        return row["name"] if row else "原設備"


def _data_cells(tab: str, r: dict[str, Any], n: _Names) -> list[Any]:
    if tab == "units":
        parent = n.unit(r["parent_id"]) if r["parent_id"] else "獨立組織"
        kind = "門市" if r["kind"] == "branch" else "部門"
        return [r["id"], r["name"], kind, parent, "使用中" if r["active"] else "停用"]
    if tab == "staff":
        return [
            r["id"],
            r["code"],
            r["alias"],
            n.unit(r["unit_id"]),
            r["role_label"],
            STATUS_LABELS[r["status"]],
        ]
    if tab in ("shifts", "attendance"):
        net = net_minutes(r)
        if tab == "attendance":
            void, status = r["voided"], ("已作廢" if r["voided"] else "有效紀錄")
        else:
            void, status = r["status"] == "cancelled", STATUS_LABELS[r["status"]]
        return [
            r["id"],
            n.staff(r["staff_id"]),
            n.unit(r["unit_id"]),
            format_dt(r["start_at"]),
            format_dt(r["end_at"]),
            r["break_minutes"],
            net,
            0 if void else net,
            status,
            r["note"],
        ]
    if tab == "requests":
        whole, cents = divmod(r["amount_minor"], 100)
        transitions = "\n".join(
            f"{format_dt(t['at'])} {STATUS_LABELS[t['status']]}"
            + (f"：{t['note']}" if t["note"] else "")
            for t in r["transitions"]
        )
        return [
            r["id"],
            REQUEST_NAMES[r["type"]],
            n.unit(r["unit_id"]),
            n.staff(r["staff_id"]),
            r["title"],
            r["description"],
            f"{whole}.{cents:02d}",
            format_dt(r["start_at"]),
            format_dt(r["end_at"]),
            STATUS_LABELS[r["status"]],
            r["processing_note"],
            transitions,
        ]
    if tab == "equipment":
        return [r["id"], r["code"], r["name"], n.unit(r["unit_id"]), STATUS_LABELS[r["state"]]]
    if tab == "reservations":
        status = "已歸還" if r["status"] == "returned" else STATUS_LABELS[r["status"]]
        return [
            r["id"],
            n.equipment(r["equipment_id"]),
            n.staff(r["staff_id"]),
            format_dt(r["start_at"]),
            format_dt(r["end_at"]),
            r["purpose"],
            status,
        ]
    return [
        r["id"],
        r["title"],
        r["body"],
        n.unit(r["unit_id"]),
        "置頂" if r["pinned"] else "一般",
        format_dt(r["due_at"]),
        "已封存" if r["archived"] else "發布中",
    ]


def export(desk: Desk, p: ViewParams, *, company_name: str, version: int) -> tuple[str, str]:
    """回傳 (檔名, CSV 內容)。沒有符合的紀錄時只有表頭列。"""
    rows = views.filter_rows(desk, p)
    scope = [
        MODE,
        company_name,
        str(version),
        TAB_LABELS[p.tab],
        views.unit_filter(desk, p.unit),
        p.q or "未設定",
        views.status_scope(p),
        views.period(p),
        TIMEZONE,
        format_dt(p.now),
        views.summary(p.tab, rows),
        SOURCE,
    ]
    names = _Names(desk)
    history: dict[str, list[str]] = {}
    for change in desk["changes"]:
        history.setdefault(change["record_id"], []).append(_change_line(change))
    table: list[list[Any]] = [[*SCOPE_HEADERS, *TAB_HEADERS[p.tab], *COMMON_HEADERS]]
    for r in rows:
        tails = [
            format_dt(r["created_at"]),
            format_dt(r["updated_at"]),
            "\n".join(history.get(r["id"], [])),
        ]
        table.append([*scope, *_data_cells(p.tab, r, names), *tails])
    return filename(p.tab, p.now), to_csv(table)
