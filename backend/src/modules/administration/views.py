"""行政檢視（唯讀）：篩選列表、篩選統計、待辦概覽、入門路線與出勤差異（A§4、A§5）。

所有計算都以快照輸出形式（`snapshot.administration`）的資料列為準，前端列表與 CSV
匯出共用 `filter_rows`，因此畫面與匯出的範圍一定相同。日期與週次一律以台北日曆判斷。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from src.core import clock
from src.core.money import format_sim
from src.core.problem import ensure
from src.modules.administration import snapshot
from src.modules.administration import validators as v
from src.modules.administration.snapshot import REQUEST_STATUSES, REQUEST_TYPES
from src.platform.context import CommandContext

TABS = (
    "units",
    "staff",
    "shifts",
    "attendance",
    "requests",
    "equipment",
    "reservations",
    "notices",
)
TAB_LABELS = {
    "units": "組織",
    "staff": "假員工",
    "shifts": "週班表",
    "attendance": "手動出勤",
    "requests": "申請",
    "equipment": "設備",
    "reservations": "借用",
    "notices": "公告",
}
# A§7 狀態標籤
STATUS_LABELS = {
    "active": "使用中",
    "inactive": "停用",
    "scheduled": "已排班",
    "completed": "已結束",
    "cancelled": "已取消",
    "draft": "草稿",
    "submitted": "待整理",
    "returned": "退回補件",
    "withdrawn": "已撤回",
    "prepared_unreviewed": "整理完成（未覆核）",
    "available": "可借用",
    "maintenance": "維修中",
    "retired": "已停用",
    "reserved": "已預約",
    "reservation_returned": "已歸還",
    "recorded": "有效紀錄",
    "voided": "已作廢",
    "archived": "已封存",
}
REQUEST_NAMES = {"leave": "請假", "purchase": "請購", "expense": "費用", "general": "一般申請"}

ALL = "all"
# 各分頁的狀態篩選選項（A§5）；第一個以外的預設都是 all
STATUS_OPTIONS: dict[str, tuple[str, ...]] = {
    "units": (ALL, "active", "inactive"),
    "staff": (ALL, "active", "inactive"),
    "shifts": (ALL, "scheduled", "completed", "cancelled"),
    "attendance": ("active", "voided", ALL),
    "requests": (ALL, *REQUEST_STATUSES),
    "equipment": (ALL, "available_now", "available", "maintenance", "retired"),
    "reservations": (ALL, "reserved", "returned", "cancelled"),
    "notices": ("active", "archived", ALL),
}
DEFAULT_STATUS = {"attendance": "active", "notices": "active"}
WEEK_TABS = ("shifts", "attendance")
QUERY_MAX = 120

_FIELDS_INVALID = "office_fields_invalid"


# --- 時間工具 --------------------------------------------------------------------------


def instant(value: str) -> datetime:
    """快照輸出的 ISO 字串轉回 datetime（UTC）。"""
    return datetime.fromisoformat(value)


def taipei_date(value: str | datetime) -> str:
    dt = instant(value) if isinstance(value, str) else value
    return dt.astimezone(clock.TAIPEI).date().isoformat()


def monday_of(day: str) -> str:
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def add_days(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def format_dt(value: str | datetime | None) -> str:
    """台北時間 `YYYY-MM-DD HH:MM`；沒有值時為「未設定」。"""
    if not value:
        return "未設定"
    dt = instant(value) if isinstance(value, str) else value
    return dt.astimezone(clock.TAIPEI).strftime("%Y-%m-%d %H:%M")


def net_minutes(row: Mapping[str, Any]) -> int:
    """`max(0, round((end − start) / 60000) − break)`；四捨五入同 JS Math.round（.5 進位）。"""
    ms = (instant(row["end_at"]) - instant(row["start_at"])) // timedelta(milliseconds=1)
    return max(0, (ms + 30_000) // 60_000 - row["break_minutes"])


# --- 資料 -----------------------------------------------------------------------------


class Desk:
    """一個工作區的行政資料（快照輸出形式）與常用查表。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.units = {r["id"]: r for r in data["units"]}
        self.staff = {r["id"]: r for r in data["staff"]}
        self.equipment = {r["id"]: r for r in data["equipment"]}
        self.active_unit_ids = {r["id"] for r in data["units"] if r["active"]}

    def __getitem__(self, name: str) -> list[dict[str, Any]]:
        return self.data[name]

    def unit_name(self, unit_id: str | None) -> str:
        """畫面與搜尋用：找不到（含 null）時為「全體」。"""
        row = self.units.get(unit_id) if unit_id else None
        return row["name"] if row else "全體"

    def staff_name(self, staff_id: str | None) -> str:
        row = self.staff.get(staff_id) if staff_id else None
        return row["alias"] if row else "未指定"

    def equipment_name(self, equipment_id: str) -> str:
        row = self.equipment.get(equipment_id)
        return row["name"] if row else "未找到設備"

    def equipment_unit(self, equipment_id: str) -> str | None:
        row = self.equipment.get(equipment_id)
        return row["unit_id"] if row else None

    def active_staff(self) -> list[dict[str, Any]]:
        return [
            r
            for r in self.data["staff"]
            if r["status"] == "active" and r["unit_id"] in self.active_unit_ids
        ]

    def available_now(self, now: datetime) -> list[dict[str, Any]]:
        """使用中組織內、狀態可借用、且目前沒有進行中預約（start ≤ now < end）的設備。"""
        busy = {
            r["equipment_id"]
            for r in self.data["reservations"]
            if r["status"] == "reserved" and instant(r["start_at"]) <= now < instant(r["end_at"])
        }
        return [
            r
            for r in self.data["equipment"]
            if r["unit_id"] in self.active_unit_ids
            and r["state"] == "available"
            and r["id"] not in busy
        ]


def load(ctx: CommandContext) -> Desk:
    """讀取前的閘：沒有工作區 409、未啟用行政模組 403，與寫入命令一致。"""
    workspace = ctx.require_workspace()
    ensure(snapshot.MODULE in workspace.modules, 403, "module_disabled", "模組未啟用")
    return Desk(snapshot.administration(ctx.db, ctx.workspace_id))


# --- 查詢參數 -------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewParams:
    tab: str
    unit: str | None
    q: str
    status: str
    type: str
    week: str
    now: datetime


def parse_now(query: Mapping[str, str], default: datetime) -> datetime:
    raw = query.get("now")
    return clock.parse_instant(raw) if raw else default


def parse_week(query: Mapping[str, str], now: datetime) -> str:
    raw = query.get("week")
    if not raw:
        return monday_of(taipei_date(now))
    return clock.taipei_monday(raw).date().isoformat()


def parse_unit(query: Mapping[str, str]) -> str | None:
    raw = query.get("unit")
    return v.uuid_value(raw) if raw else None


def parse_params(query: Mapping[str, str], default_now: datetime) -> ViewParams:
    """`tab` 必填；`status` 與 `type` 不在該分頁選項內、搜尋超過 120 字時 422。"""
    tab = query.get("tab", "")
    ensure(tab in TABS, 422, _FIELDS_INVALID, "請選擇行政資料類型")
    q = query.get("q", "")
    ensure(len(q) <= QUERY_MAX, 422, _FIELDS_INVALID, "搜尋條件最多 120 字")
    status = query.get("status") or DEFAULT_STATUS.get(tab, ALL)
    ensure(status in STATUS_OPTIONS[tab], 422, _FIELDS_INVALID, "狀態篩選不符")
    kind = query.get("type") or ALL
    allowed = (ALL, *REQUEST_TYPES) if tab == "requests" else (ALL,)
    ensure(kind in allowed, 422, _FIELDS_INVALID, "申請類型篩選不符")
    now = parse_now(query, default_now)
    return ViewParams(
        tab=tab,
        unit=parse_unit(query),
        q=q,
        status=status,
        type=kind,
        week=parse_week(query, now),
        now=now,
    )


# --- 篩選與排序（A§5） ----------------------------------------------------------------


def _sorted(rows: list[dict[str, Any]], key: str, *, reverse: bool) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: instant(r[key]), reverse=reverse)


def filter_rows(desk: Desk, p: ViewParams) -> list[dict[str, Any]]:
    """目前分頁的篩選結果；前端列表、篩選統計與 CSV 匯出共用。"""
    needle = p.q.strip().lower()

    def hit(text: str) -> bool:
        return needle in text.lower()

    def in_unit(unit_id: str | None) -> bool:
        return p.unit is None or unit_id == p.unit

    def in_week(row: dict[str, Any]) -> bool:
        return p.week <= taipei_date(row["start_at"]) < add_days(p.week, 7)

    def status_is(value: str) -> bool:
        return p.status == ALL or value == p.status

    tab = p.tab
    if tab == "units":
        return [
            r
            for r in desk["units"]
            if in_unit(r["id"])
            and hit(f"{r['name']} {desk.unit_name(r['parent_id'])}")
            and status_is("active" if r["active"] else "inactive")
        ]
    if tab == "staff":
        return [
            r
            for r in desk["staff"]
            if in_unit(r["unit_id"])
            and hit(f"{r['code']} {r['alias']} {r['role_label']}")
            and status_is(r["status"])
        ]
    if tab in WEEK_TABS:
        rows = [
            r
            for r in desk[tab]
            if in_week(r)
            and in_unit(r["unit_id"])
            and hit(f"{desk.staff_name(r['staff_id'])} {r['note']}")
            and (
                status_is(r["status"])
                if tab == "shifts"
                else status_is("voided" if r["voided"] else "active")
            )
        ]
        return _sorted(rows, "start_at", reverse=tab == "attendance")
    if tab == "requests":
        rows = [
            r
            for r in desk["requests"]
            if in_unit(r["unit_id"])
            and hit(
                " ".join(
                    [
                        r["title"],
                        r["description"],
                        desk.staff_name(r["staff_id"]),
                        r["processing_note"],
                        " ".join(t["note"] for t in r["transitions"]),
                    ]
                )
            )
            and (p.type == ALL or r["type"] == p.type)
            and status_is(r["status"])
        ]
        return _sorted(rows, "updated_at", reverse=True)
    if tab == "equipment":
        available = {r["id"] for r in desk.available_now(p.now)}
        return [
            r
            for r in desk["equipment"]
            if in_unit(r["unit_id"])
            and hit(f"{r['code']} {r['name']}")
            and (r["id"] in available if p.status == "available_now" else status_is(r["state"]))
        ]
    if tab == "reservations":
        rows = [
            r
            for r in desk["reservations"]
            if (p.unit is None or desk.equipment_unit(r["equipment_id"]) == p.unit)
            and hit(
                f"{desk.equipment_name(r['equipment_id'])} "
                f"{desk.staff_name(r['staff_id'])} {r['purpose']}"
            )
            and status_is(r["status"])
        ]
        return _sorted(rows, "start_at", reverse=True)
    # notices：全體公告不受單位篩選影響；發布中的置頂公告在前，其餘依更新時間由新到舊
    rows = [
        r
        for r in desk["notices"]
        if (p.unit is None or r["unit_id"] is None or r["unit_id"] == p.unit)
        and hit(f"{r['title']} {r['body']}")
        and status_is("archived" if r["archived"] else "active")
    ]
    rows = _sorted(rows, "updated_at", reverse=True)
    return sorted(rows, key=lambda r: not (r["pinned"] and not r["archived"]))


def status_scope(p: ViewParams) -> str:
    """篩選列與 CSV「狀態篩選」欄的文字。"""
    s = p.status
    if p.tab == "attendance":
        return {"all": "有效與作廢", "voided": "已作廢"}.get(s, "有效紀錄")
    if p.tab == "notices":
        return {"all": "發布中與封存", "archived": "已封存"}.get(s, "發布中")
    if p.tab == "requests":
        kind = REQUEST_NAMES[p.type] if p.type != ALL else "全部類型"
        status = STATUS_LABELS[s] if s != ALL else "全部狀態"
        return f"{kind}／{status}"
    if s == ALL:
        return "全部狀態"
    if p.tab == "equipment" and s == "available_now":
        return "目前可用"
    if p.tab == "reservations" and s == "returned":
        return "已歸還"
    return STATUS_LABELS[s]


def period(p: ViewParams) -> str:
    if p.tab in WEEK_TABS:
        return f"{p.week} 至 {add_days(p.week, 6)}（依開始日歸週）"
    return "全部日期"


def summary(tab: str, rows: list[dict[str, Any]]) -> str:
    """篩選統計（A§6）：班次與出勤算分鐘、申請算金額、公告分發布中與封存，其餘算筆數。"""
    if tab == "shifts":
        valid = [r for r in rows if r["status"] != "cancelled"]
        minutes = sum(net_minutes(r) for r in valid)
        cancelled = len(rows) - len(valid)
        return (
            f"目前篩選的有效班次 {len(valid)} 筆，共 {minutes} 分鐘；"
            f"另保留 {cancelled} 筆取消紀錄。"
        )
    if tab == "attendance":
        valid = [r for r in rows if not r["voided"]]
        minutes = sum(net_minutes(r) for r in valid)
        voided = len(rows) - len(valid)
        return (
            f"目前篩選的有效出勤 {len(valid)} 筆，共 {minutes} 分鐘；"
            f"另保留 {voided} 筆作廢紀錄，作廢不計入。"
        )
    if tab == "requests":
        total = format_sim(sum(r["amount_minor"] for r in rows))
        return f"目前篩選的申請登錄合計 {total}。此為模擬登錄金額，不代表核准或支付。"
    if tab == "notices":
        archived = sum(1 for r in rows if r["archived"])
        return (
            f"目前篩選 {len(rows) - archived} 則發布中公告、{archived} 則封存公告。"
            "封存公告不列入最近截止與置頂。"
        )
    return f"目前篩選共 {len(rows)} 筆模擬紀錄。"


def rows_view(desk: Desk, p: ViewParams) -> dict[str, Any]:
    rows = filter_rows(desk, p)
    return {
        "rows": rows,
        "summary": summary(p.tab, rows),
        "status_scope": status_scope(p),
        "period": period(p),
    }


# --- 出勤差異（A§4） ------------------------------------------------------------------


def attendance_diff(desk: Desk, week: str, unit: str | None) -> list[dict[str, Any]]:
    """選定週（依台北開始日）未取消班次與未作廢出勤的淨分鐘，每位有紀錄的假員工一列。"""
    end = add_days(week, 7)

    def in_week(row: dict[str, Any]) -> bool:
        return week <= taipei_date(row["start_at"]) < end

    shifts = [r for r in desk["shifts"] if r["status"] != "cancelled" and in_week(r)]
    attendance = [r for r in desk["attendance"] if not r["voided"] and in_week(r)]
    out: list[dict[str, Any]] = []
    for person in desk["staff"]:
        if unit is not None and person["unit_id"] != unit:
            continue
        mine_s = [r for r in shifts if r["staff_id"] == person["id"]]
        mine_a = [r for r in attendance if r["staff_id"] == person["id"]]
        if not mine_s and not mine_a:
            continue
        scheduled = sum(net_minutes(r) for r in mine_s)
        recorded = sum(net_minutes(r) for r in mine_a)
        out.append(
            {
                "staff_id": person["id"],
                "alias": person["alias"],
                "scheduled": scheduled,
                "recorded": recorded,
                "diff": recorded - scheduled,
            }
        )
    return out


# --- 待辦概覽與入門路線（A§4、A§5） ----------------------------------------------------

UNIT_REASON = "先新增一個使用中的門市或部門。"
PEOPLE_REASON = "先新增使用中組織與假員工。"


def onboarding(desk: Desk) -> dict[str, Any]:
    has_unit = bool(desk.active_unit_ids)
    has_staff = bool(desk.active_staff())
    steps = [
        ("unit", "建立組織", "至少一個使用中的門市或部門。", has_unit, ""),
        (
            "staff",
            "加入假員工",
            "至少一位使用中假員工，對應使用中組織。",
            has_staff,
            "" if has_unit else UNIT_REASON,
        ),
        (
            "shift",
            "排第一個班次",
            "至少一筆未取消班次，開始這週的流程練習。",
            any(r["status"] != "cancelled" for r in desk["shifts"]),
            "" if has_staff else PEOPLE_REASON,
        ),
    ]
    out = []
    for step_id, label, detail, done, reason in steps:
        if not done:
            button = label
        elif step_id == "shift":
            button = "新增另一個班次"
        else:
            button = f"再{label}"
        out.append(
            {
                "id": step_id,
                "label": label,
                "detail": detail,
                "done": done,
                "reason": reason,
                "button": button,
            }
        )
    completed = sum(1 for s in out if s["done"])
    rest = f" · 尚需 {3 - completed} 步" if completed < 3 else " · 可繼續出勤、申請與設備借用"
    return {
        "steps": out,
        "completed": completed,
        "open": completed < 3,
        "summary": f"已完成 {completed}／3 步{rest}",
    }


def overview(desk: Desk, now: datetime, week: str, unit: str | None) -> dict[str, Any]:
    requests = desk["requests"]
    submitted = sum(1 for r in requests if r["status"] == "submitted")
    returned = sum(1 for r in requests if r["status"] == "returned")
    differences = sum(1 for r in attendance_diff(desk, week, unit) if r["diff"] != 0)
    upcoming = sorted(
        (r for r in desk["notices"] if not r["archived"] and r["due_at"]),
        key=lambda r: instant(r["due_at"]),
    )
    deadline = next((r for r in upcoming if instant(r["due_at"]) >= now), None)
    current_week = week == monday_of(taipei_date(now))
    tiles = [
        {
            "id": "requests",
            "label": "申請待整理",
            "value": submitted,
            "unit": "件",
            "sub": f"{returned} 件待補件",
            "target": {"tab": "requests", "unit": None, "type": ALL, "status": "submitted"},
        },
        {
            "id": "equipment",
            "label": "目前可用設備",
            "value": len(desk.available_now(now)),
            "unit": "件",
            "sub": "依設備狀態與目前預約計算",
            "target": {"tab": "equipment", "unit": None, "status": "available_now"},
        },
        {
            "id": "attendance",
            "label": "本週出勤差異" if current_week else "選定週出勤差異",
            "value": differences,
            "unit": "人",
            "sub": "排班與手動紀錄的分鐘差",
            "target": {"tab": "attendance", "status": "active"},
        },
        {
            "id": "notice",
            "label": "最近公告截止",
            "value": taipei_date(deadline["due_at"])[5:] if deadline else None,
            "unit": None,
            "sub": deadline["title"] if deadline else "還沒有即將截止的公告",
            "target": {
                "tab": "notices",
                "unit": None,
                "status": "active",
                "q": deadline["title"] if deadline else None,
            },
        },
    ]
    return {
        "now": clock.iso(now),
        "week": week,
        "tiles": tiles,
        "onboarding": onboarding(desk),
        "demo_empty": all(not desk[t] for t in TABS) and not desk["changes"],
        "counts": {t: len(desk[t]) for t in TABS},
    }


def unit_filter(desk: Desk, unit: str | None) -> str:
    """CSV「組織範圍」欄：未篩選為「全部組織」，篩選的組織已不存在時為「原組織」。"""
    if unit is None:
        return "全部組織"
    row = desk.units.get(unit)
    return row["name"] if row else "原組織"
