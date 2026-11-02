"""行政資料列查詢：限定在目前工作區，找不到時 404 office_record_missing（A§0）。"""

import uuid
from typing import Any

from sqlmodel import SQLModel

from src.core.problem import Problem, ensure
from src.modules.administration import validators as v
from src.modules.administration.entity import AdmStaff, AdmUnit
from src.platform.context import CommandContext
from src.platform.records import scoped_get


def row_by_id[T: SQLModel](
    ctx: CommandContext, model: type[T], row_id: Any, *, lock: bool = False
) -> T:
    """以 id 取得本工作區的資料列；其他工作區的資料一律視為不存在。"""
    row = scoped_get(ctx.db, model, ctx.workspace_id, v.uuid_value(row_id), lock=lock)
    if row is None:
        raise Problem(404, "office_record_missing", "找不到行政紀錄")
    return row


def active_unit(ctx: CommandContext, unit_id: Any) -> AdmUnit:
    unit = row_by_id(ctx, AdmUnit, unit_id)
    ensure(unit.active, 409, "office_unit_inactive", "請選啟用中的單位")
    return unit


def active_staff(ctx: CommandContext, staff_id: Any, unit_id: uuid.UUID | None = None) -> AdmStaff:
    """啟用中的示範員工，且其所屬單位也須啟用；指定 unit_id 時員工須屬於該單位。"""
    staff = row_by_id(ctx, AdmStaff, staff_id)
    ensure(staff.status == "active", 409, "office_staff_inactive", "請選啟用中的示範員工")
    active_unit(ctx, str(staff.unit_id))
    if unit_id is not None:
        ensure(staff.unit_id == unit_id, 422, "office_unit_mismatch", "示範員工與單位不符")
    return staff
