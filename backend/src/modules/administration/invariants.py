"""行政一致性檢查（A§0–A§2）：每個命令（含匯入）之後檢查整個工作區的行政資料。

檢查順序照 A§0 的整體驗證：筆數上限 → 組織 → 假員工 → 班次 → 申請 → 設備 → 借用 → 公告。
停用組織或員工時被下層資料阻擋，就是由這裡的「啟用中的資料須參照啟用中的上層」規則擋下：
- 子單位啟用中 → 上層不可停用（422 office_unit_inactive）
- 啟用的員工、未停用（retired）的設備、已排班的班次、待整理的申請、已預約的借用
  → 所屬單位不可停用（409 office_unit_inactive）
- 已排班的班次、待整理的申請、已預約的借用 → 員工不可停用（409 office_staff_inactive）
- 已預約的借用 → 設備須維持可借用（409 office_equipment_unavailable）

時段（A§1）：班次與出勤的員工須屬於同一單位（422 office_unit_mismatch）；同一員工的非取消班次、
同一員工的非作廢出勤、同一設備借用中的預約，各自不可重疊（半開區間，409 office_time_conflict）。

change 鏈（A§2 validateChanges，422 office_change_invalid）：每筆更正只能改該種類允許的欄位且須有
實際變更；同一筆資料的更正前後相接；最新一筆與現有資料相符（只差之後仍可變的欄位）。

申請（A§1 Request、A§2 狀態紀錄）：單位存在、員工屬於該單位；請假須有員工與起訖且金額為 0
（422 office_leave_invalid）；請購與費用金額至少 1；退回須有處理原因；待整理的申請須屬於啟用中的
單位與員工。狀態紀錄 1–50 筆（422 office_transition_limit），從建立時的草稿開始、時間不倒退且不晚於
updated_at、每一步符合流程、只有退回帶原因、最後狀態與 processing_note 與紀錄相符
（422 office_transition_invalid）。
"""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlmodel import Session, select

from src.core import clock
from src.core.problem import Problem, ensure
from src.modules.administration import validators as v
from src.modules.administration.entity import (
    CHANGE_COLLECTIONS,
    CHANGE_LIMIT,
    RECORD_LIMITS,
    TRANSITION_LIMIT,
    AdmAttendance,
    AdmChange,
    AdmEquipment,
    AdmNotice,
    AdmRequest,
    AdmRequestTransition,
    AdmReservation,
    AdmShift,
    AdmStaff,
    AdmUnit,
    by_seq,
)
from src.modules.administration.snapshot import enabled, row_out

_TABLES = {
    "units": "adm_unit",
    "staff": "adm_staff",
    "shifts": "adm_shift",
    "attendance": "adm_attendance",
    "requests": "adm_request",
    "equipment": "adm_equipment",
    "reservations": "adm_reservation",
    "notices": "adm_notice",
    "changes": "adm_change",
}
_COUNT_SQL = text(
    "SELECT "
    + ", ".join(
        f"(SELECT count(*) FROM {table} WHERE workspace_id = :w) AS {name}"
        for name, table in _TABLES.items()
    )
)


def _missing() -> Problem:
    return Problem(404, "office_record_missing", "找不到行政紀錄")


def counts(db: Session, wid: uuid.UUID) -> dict[str, int]:
    """各集合（含 changes）目前的筆數；作廢、取消、封存的資料也計入。"""
    return dict(db.execute(_COUNT_SQL, {"w": wid}).mappings().one())


def _check_limits(db: Session, wid: uuid.UUID) -> None:
    counts_ = counts(db, wid)
    for name, limit in RECORD_LIMITS.items():
        ensure(counts_[name] <= limit, 422, "office_record_limit", "行政紀錄超出上限")
    ensure(
        counts_["changes"] <= CHANGE_LIMIT, 422, "office_change_limit", "更正與封存紀錄最多 200 筆"
    )


def _check_units(units: dict[uuid.UUID, AdmUnit]) -> None:
    for row in units.values():
        if row.parent_id is None:
            continue
        parent = units.get(row.parent_id)
        if parent is None:
            raise _missing()
        ensure(parent.id != row.id, 422, "office_unit_cycle", "單位不可從屬自身")
        if row.active:
            ensure(parent.active, 422, "office_unit_inactive", "啟用的子單位須有啟用的上層單位")
        visited = {row.id}
        parent_id: uuid.UUID | None = row.parent_id
        while parent_id is not None:
            ensure(parent_id not in visited, 422, "office_unit_cycle", "單位層級不可循環")
            visited.add(parent_id)
            current = units.get(parent_id)
            if current is None:
                raise _missing()
            parent_id = current.parent_id


def _unique_codes(rows: Iterable[AdmStaff] | Iterable[AdmEquipment]) -> None:
    codes: set[str] = set()
    for row in rows:
        code = row.code.strip().lower()
        ensure(code not in codes, 422, "office_code_duplicate", "行政代碼不可重複")
        codes.add(code)


class _Refs:
    """已載入的單位與員工，提供「須為啟用中」的參照檢查。"""

    def __init__(self, units: dict[uuid.UUID, AdmUnit], staff: dict[uuid.UUID, AdmStaff]) -> None:
        self.units = units
        self.staff = staff

    def unit(self, unit_id: uuid.UUID) -> AdmUnit:
        unit = self.units.get(unit_id)
        if unit is None:
            raise _missing()
        return unit

    def active_unit(self, unit_id: uuid.UUID, message: str) -> None:
        ensure(self.unit(unit_id).active, 409, "office_unit_inactive", message)

    def member(self, staff_id: uuid.UUID, unit_id: uuid.UUID) -> None:
        """員工存在且屬於該單位（不論啟用狀態；歷史班次與出勤也適用）。"""
        staff = self.staff.get(staff_id)
        if staff is None:
            raise _missing()
        ensure(
            staff.unit_id == unit_id, 422, "office_unit_mismatch", "排班或出勤的示範員工與單位不符"
        )

    def active_staff(self, staff_id: uuid.UUID, unit_id: uuid.UUID | None, message: str) -> None:
        staff = self.staff.get(staff_id)
        if staff is None:
            raise _missing()
        ensure(staff.status == "active", 409, "office_staff_inactive", message)
        self.active_unit(staff.unit_id, "示範員工所屬單位須為啟用中")
        if unit_id is not None:
            ensure(staff.unit_id == unit_id, 422, "office_unit_mismatch", "示範員工與單位不符")


def check(db: Session, workspace_id: str) -> None:
    """ModuleSpec.invariants：未啟用行政模組時不檢查。"""
    if not enabled(db, workspace_id):
        return
    wid = uuid.UUID(workspace_id)
    _check_limits(db, wid)

    def rows(model, *conditions):  # type: ignore[no-untyped-def]
        stmt = select(model).where(model.workspace_id == wid, *conditions).order_by(by_seq(model))
        return list(db.exec(stmt))

    units = {u.id: u for u in rows(AdmUnit)}
    _check_units(units)

    staff_rows = rows(AdmStaff)
    refs = _Refs(units, {s.id: s for s in staff_rows})
    for s in staff_rows:
        unit = refs.unit(s.unit_id)
        if s.status == "active":
            ensure(unit.active, 409, "office_unit_inactive", "啟用中的示範員工須屬於啟用中的單位")
    _unique_codes(staff_rows)

    shifts = rows(AdmShift)
    attendance = rows(AdmAttendance)
    for segment in (*shifts, *attendance):
        refs.unit(segment.unit_id)
        refs.member(segment.staff_id, segment.unit_id)
    for shift in shifts:
        if shift.status == "scheduled":
            refs.active_unit(shift.unit_id, "已排班的班次須屬於啟用中的單位")
            refs.active_staff(shift.staff_id, shift.unit_id, "已排班的班次須由啟用中的示範員工負責")
    _no_overlap([x for x in shifts if x.status != "cancelled"], lambda x: x.staff_id)
    _no_overlap([x for x in attendance if not x.voided], lambda x: x.staff_id)

    transitions = _transitions(db, wid)
    for request in rows(AdmRequest):
        _check_request(request, transitions.get(request.id, []), refs)

    equipment_rows = rows(AdmEquipment)
    equipment = {e.id: e for e in equipment_rows}
    for e in equipment_rows:
        unit = refs.unit(e.unit_id)
        if e.state != "retired":
            ensure(unit.active, 409, "office_unit_inactive", "未停用的設備須屬於啟用中的單位")
    _unique_codes(equipment_rows)

    reservations = rows(AdmReservation)
    for r in reservations:
        item = equipment.get(r.equipment_id)
        if item is None or r.staff_id not in refs.staff:
            raise _missing()
        if r.status != "reserved":
            continue
        ensure(
            item.state == "available", 409, "office_equipment_unavailable", "設備仍有借用中的預約"
        )
        refs.active_unit(item.unit_id, "借用中的設備須屬於啟用中的單位")
        refs.active_staff(r.staff_id, None, "借用中的預約須由啟用中的示範員工負責")
    _no_overlap([r for r in reservations if r.status == "reserved"], lambda r: r.equipment_id)

    notices = rows(AdmNotice)
    for n in notices:
        if n.unit_id is not None:
            refs.unit(n.unit_id)

    tracked = {
        "shifts": shifts,
        "attendance": attendance,
        "reservations": reservations,
        "notices": notices,
    }
    _check_changes(rows(AdmChange), tracked)


# --- 申請與狀態紀錄 -----------------------------------------------------------------

# 狀態 → 可轉移到的狀態；returned → draft 只經由編輯
LIFECYCLE: dict[str, tuple[str, ...]] = {
    "draft": ("submitted", "withdrawn"),
    "submitted": ("returned", "withdrawn", "prepared_unreviewed"),
    "returned": ("draft", "submitted", "withdrawn"),
    "withdrawn": (),
    "prepared_unreviewed": (),
}


def _transitions(db: Session, wid: uuid.UUID) -> dict[uuid.UUID, list[AdmRequestTransition]]:
    stmt = (
        select(AdmRequestTransition)
        .where(AdmRequestTransition.workspace_id == wid)
        .order_by(AdmRequestTransition.request_id, AdmRequestTransition.seq)  # type: ignore[arg-type]
    )
    out: dict[uuid.UUID, list[AdmRequestTransition]] = defaultdict(list)
    for t in db.exec(stmt):
        out[t.request_id].append(t)
    return out


def _transition_invalid(message: str) -> Problem:
    return Problem(422, "office_transition_invalid", message)


def _check_history(request: AdmRequest, history: list[AdmRequestTransition]) -> None:
    """狀態紀錄（A§2 transition-history rules），時間一律以毫秒精度比較。"""
    ensure(
        1 <= len(history) <= TRANSITION_LIMIT,
        422,
        "office_transition_limit",
        "每份申請須有狀態紀錄，最多 50 筆",
    )
    created, updated = _instant(request.created_at), _instant(request.updated_at)
    previous_at = created
    previous_status: str | None = None
    latest_reason = ""
    for entry in history:
        at = _instant(entry.at)
        if not (previous_at <= at <= updated):
            raise _transition_invalid("申請狀態紀錄時間不符")
        if previous_status is None:
            if not (entry.status == "draft" and at == created):
                raise _transition_invalid("申請狀態紀錄須從建立時的草稿開始")
        elif entry.status not in LIFECYCLE.get(previous_status, ()):
            raise _transition_invalid("申請狀態紀錄流程不符")
        if entry.status == "returned":
            latest_reason = v.text(entry.note, 1000)
        elif entry.note != "":
            raise _transition_invalid("只有退回紀錄可包含處理原因")
        previous_at, previous_status = at, entry.status
    if previous_status != request.status or request.processing_note != latest_reason:
        raise _transition_invalid("申請狀態或最新退回原因與紀錄不符")


def _check_request(request: AdmRequest, history: list[AdmRequestTransition], refs: _Refs) -> None:
    refs.unit(request.unit_id)
    if request.staff_id is not None:
        staff = refs.staff.get(request.staff_id)
        if staff is None:
            raise _missing()
        ensure(
            staff.unit_id == request.unit_id,
            422,
            "office_unit_mismatch",
            "申請的示範員工與單位不符",
        )
    _check_history(request, history)
    if request.type == "leave":
        ensure(
            request.staff_id is not None
            and request.start_at is not None
            and request.amount_minor == 0,
            422,
            "office_leave_invalid",
            "請假須指定示範員工與起訖時間，金額須為 0",
        )
    if request.type in ("purchase", "expense"):
        v.integer(request.amount_minor, 1)
    if request.status == "returned":
        v.text(request.processing_note, 1000)
    if request.status == "submitted":
        refs.active_unit(request.unit_id, "待整理的申請須屬於啟用中的單位")
        if request.staff_id is not None:
            refs.active_staff(
                request.staff_id, request.unit_id, "待整理的申請須屬於啟用中的示範員工"
            )


# --- 時段重疊 -----------------------------------------------------------------------


class _Segment(Protocol):
    start_at: datetime
    end_at: datetime


def _no_overlap[T: _Segment](segments: Sequence[T], key: Callable[[T], uuid.UUID]) -> None:
    """同一組（員工或設備）的時段依開始時間排序後，前一段須在下一段開始前（含）結束。"""
    groups: dict[uuid.UUID, list[T]] = defaultdict(list)
    for segment in segments:
        groups[key(segment)].append(segment)
    for group in groups.values():
        group.sort(key=lambda x: x.start_at)
        for prev, nxt in zip(group, group[1:], strict=False):
            ensure(
                prev.end_at <= nxt.start_at,
                409,
                "office_time_conflict",
                "同一示範員工或設備的時段重疊",
            )


# --- change 鏈（A§2 validateChanges） ------------------------------------------------

_SEGMENT_EDITABLE = ("start_at", "end_at", "break_minutes", "note", "updated_at")
_NOTICE_EDITABLE = ("title", "body", "unit_id", "pinned", "due_at", "updated_at")
# kind → (前置條件, 允許不同的欄位, 前置條件不符時的訊息)
_KIND_RULES: dict[str, tuple[Callable[[dict, dict], bool], tuple[str, ...], str]] = {
    "shift.update": (
        lambda b, a: b["status"] == "scheduled" and a["status"] == "scheduled",
        _SEGMENT_EDITABLE,
        "只有已排定班次可更正",
    ),
    "attendance.update": (
        lambda b, a: not _flag(b, "voided") and not _flag(a, "voided"),
        _SEGMENT_EDITABLE,
        "已作廢出勤不可更正",
    ),
    "attendance.void": (
        lambda b, a: not _flag(b, "voided") and _flag(a, "voided"),
        ("voided", "updated_at"),
        "出勤作廢紀錄不符",
    ),
    "reservation.update": (
        lambda b, a: b["status"] == "reserved" and a["status"] == "reserved",
        ("start_at", "end_at", "purpose", "updated_at"),
        "只有借用中的預約可更正",
    ),
    "notice.archive": (
        lambda b, a: not _flag(b, "archived") and _flag(a, "archived"),
        ("archived", "updated_at"),
        "公告封存紀錄不符",
    ),
    "notice.restore": (
        lambda b, a: _flag(b, "archived") and not _flag(a, "archived"),
        ("archived", "updated_at"),
        "公告封存紀錄不符",
    ),
}
# 兩筆更正之間可能被一般操作改動的欄位（公告可一般編輯）
_INTERVENING = {"notices": _NOTICE_EDITABLE}
# 最新一筆更正之後仍可能變動的欄位
_LATER = {
    "notices": _NOTICE_EDITABLE,
    "attendance": (),
    "shifts": ("status", "updated_at"),
    "reservations": ("status", "updated_at"),
}


def _flag(row: dict[str, Any], key: str) -> Any:
    """舊資料可能缺少 voided／archived，一律視為 false。"""
    return row.get(key, False) if key in ("voided", "archived") else row.get(key)


def _same(a: dict[str, Any], b: dict[str, Any], ignore: Iterable[str] = ()) -> bool:
    skip = set(ignore)
    return all(_flag(a, k) == _flag(b, k) for k in set(a) | set(b) if k not in skip)


def _instant(value: str | datetime) -> datetime:
    """比較用的時間：一律截到毫秒（快照輸出的精度）。"""
    return clock.parse_instant(clock.iso(value) if isinstance(value, datetime) else value)


def _invalid(message: str) -> Problem:
    return Problem(422, "office_change_invalid", message)


def _check_changes(changes: list[AdmChange], tracked: dict[str, list[Any]]) -> None:
    current = {
        name: {row.id: row_out(name, row) for row in collection}
        for name, collection in tracked.items()
    }
    previous_at: datetime | None = None
    latest: dict[uuid.UUID, AdmChange] = {}
    for change in changes:
        if change.kind not in CHANGE_COLLECTIONS:
            raise _invalid("更正紀錄種類不符")
        name = CHANGE_COLLECTIONS[change.kind]
        row = current[name].get(change.record_id)
        if row is None:
            raise _missing()
        before, after = change.before, change.after
        try:
            at = _instant(change.at)
            in_order = (
                (previous_at is None or at >= previous_at)
                and _instant(before["updated_at"]) <= at
                and _instant(after["updated_at"]) == at
                and at <= _instant(row["updated_at"])
            )
        except (KeyError, TypeError, Problem):
            raise _invalid("更正紀錄時間不符") from None
        if not in_order:
            raise _invalid("更正紀錄時間不符")
        previous_at = at
        record_id = str(change.record_id)
        if not (
            before.get("id") == record_id
            and after.get("id") == record_id
            and before.get("created_at") == row["created_at"]
            and after.get("created_at") == row["created_at"]
        ):
            raise _invalid("更正紀錄來源不符")
        owners = ("staff_id", "equipment_id") + (() if name == "notices" else ("unit_id",))
        for field in owners:
            if field in before and not (before[field] == row[field] == after.get(field)):
                raise _invalid("更正紀錄不得改變所屬對象")
        precondition, allowed, message = _KIND_RULES[change.kind]
        if not precondition(before, after):
            raise _invalid(message)
        if not _same(before, after, allowed) or _same(before, after, ("updated_at",)):
            raise _invalid("更正紀錄包含不可修改的欄位或沒有實際變更")
        prior = latest.get(change.record_id)
        if prior is not None:
            intervening = _INTERVENING.get(name, ("updated_at",))
            if not _same(prior.after, before, intervening) or _instant(
                before["updated_at"]
            ) < _instant(prior.at):
                raise _invalid("更正紀錄前後不連續")
        latest[change.record_id] = change
    for record_id, change in latest.items():
        name = CHANGE_COLLECTIONS[change.kind]
        if not _same(change.after, current[name][record_id], _LATER[name]):
            raise _invalid("最新更正紀錄與現有資料不符")
