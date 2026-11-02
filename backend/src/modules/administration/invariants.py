"""行政一致性檢查（A§0–A§2）：每個命令（含匯入）之後檢查整個工作區的行政資料。

檢查順序照 A§0 的整體驗證：筆數上限 → 組織 → 假員工 → 班次 → 申請 → 設備 → 借用 → 公告。
停用組織或員工時被下層資料阻擋，就是由這裡的「啟用中的資料須參照啟用中的上層」規則擋下：
- 子單位啟用中 → 上層不可停用（422 office_unit_inactive）
- 啟用的員工、未停用（retired）的設備、已排班的班次、待整理的申請、已預約的借用
  → 所屬單位不可停用（409 office_unit_inactive）
- 已排班的班次、待整理的申請、已預約的借用 → 員工不可停用（409 office_staff_inactive）
- 已預約的借用 → 設備須維持可借用（409 office_equipment_unavailable）

班次／出勤／借用的時段重疊與 change 鏈驗證由 Task 12 補上；申請狀態紀錄由 Task 13 補上。
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import text
from sqlmodel import Session, select

from src.core.problem import Problem, ensure
from src.modules.administration.entity import (
    CHANGE_LIMIT,
    RECORD_LIMITS,
    AdmEquipment,
    AdmNotice,
    AdmRequest,
    AdmReservation,
    AdmShift,
    AdmStaff,
    AdmUnit,
    by_seq,
)
from src.modules.administration.snapshot import enabled

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


def _check_limits(db: Session, wid: uuid.UUID) -> None:
    counts = db.execute(_COUNT_SQL, {"w": wid}).mappings().one()
    for name, limit in RECORD_LIMITS.items():
        ensure(counts[name] <= limit, 422, "office_record_limit", "行政紀錄超出上限")
    ensure(
        counts["changes"] <= CHANGE_LIMIT, 422, "office_change_limit", "更正與封存紀錄最多 200 筆"
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

    for shift in rows(AdmShift, AdmShift.status == "scheduled"):
        refs.active_unit(shift.unit_id, "已排班的班次須屬於啟用中的單位")
        refs.active_staff(shift.staff_id, shift.unit_id, "已排班的班次須由啟用中的示範員工負責")

    for request in rows(AdmRequest, AdmRequest.status == "submitted"):
        refs.active_unit(request.unit_id, "待整理的申請須屬於啟用中的單位")
        if request.staff_id is not None:
            refs.active_staff(
                request.staff_id, request.unit_id, "待整理的申請須屬於啟用中的示範員工"
            )

    equipment_rows = rows(AdmEquipment)
    equipment = {e.id: e for e in equipment_rows}
    for e in equipment_rows:
        unit = refs.unit(e.unit_id)
        if e.state != "retired":
            ensure(unit.active, 409, "office_unit_inactive", "未停用的設備須屬於啟用中的單位")
    _unique_codes(equipment_rows)

    for r in rows(AdmReservation, AdmReservation.status == "reserved"):
        item = equipment.get(r.equipment_id)
        if item is None:
            raise _missing()
        ensure(
            item.state == "available", 409, "office_equipment_unavailable", "設備仍有借用中的預約"
        )
        refs.active_unit(item.unit_id, "借用中的設備須屬於啟用中的單位")
        refs.active_staff(r.staff_id, None, "借用中的預約須由啟用中的示範員工負責")

    for n in rows(AdmNotice, AdmNotice.unit_id.is_not(None)):  # type: ignore[union-attr]
        refs.unit(n.unit_id)
