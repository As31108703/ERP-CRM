"""設備借用：建立、附理由更正、歸還與取消（A§2）。設備與借用人不可變更。"""

import uuid
from typing import Any

from src.core import clock
from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration import validators as v
from src.modules.administration.corrections import correct_record
from src.modules.administration.entity import AdmEquipment, AdmReservation
from src.modules.administration.lookup import active_staff, active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.shifts import correction_fields
from src.platform.context import CommandContext

RESERVATION_FIELDS = ("start_at", "end_at", "purpose")


def create_reservation(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """設備須可借用且所屬單位啟用；借用人須啟用，但不必屬於設備的單位。最長 31 天。"""
    p = parse("office.reservation.create", payload)
    equipment = row_by_id(ctx, AdmEquipment, p["equipment_id"])
    ensure(equipment.state == "available", 409, "office_equipment_unavailable", "設備目前不可借用")
    active_unit(ctx, str(equipment.unit_id))
    staff = active_staff(ctx, p["staff_id"])
    start, end = v.interval(p["start_at"], p["end_at"], max_minutes=v.LONG_MAX_MINUTES)
    row = AdmReservation(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        equipment_id=equipment.id,
        staff_id=staff.id,
        start_at=start,
        end_at=end,
        purpose=v.text(p.get("purpose", ""), 1000, allow_empty=True),
        status="reserved",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def _reserved(ctx: CommandContext, row_id: Any, message: str) -> AdmReservation:
    row = row_by_id(ctx, AdmReservation, row_id, lock=True)
    ensure(row.status == "reserved", 409, "office_transition_invalid", message)
    return row


def update_reservation(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.reservation.update", payload)
    row = _reserved(ctx, p["id"], "只有借用中的預約可以更正")
    correction_fields(p, RESERVATION_FIELDS)
    start, end = v.interval(
        p.get("start_at", clock.iso(row.start_at)),
        p.get("end_at", clock.iso(row.end_at)),
        max_minutes=v.LONG_MAX_MINUTES,
    )
    edits: dict[str, Any] = {"start_at": start, "end_at": end}
    if "purpose" in p:
        edits["purpose"] = v.text(p["purpose"], 1000, allow_empty=True)
    return correct_record(ctx, "reservations", row.id, "reservation.update", edits, p["reason"])


def _close(ctx: CommandContext, payload: dict[str, Any], status: str) -> str | None:
    action = "office.reservation.return" if status == "returned" else "office.reservation.cancel"
    p = parse(action, payload)
    row = _reserved(ctx, p["id"], "只有借用中的預約可以歸還或取消")
    row.status = status
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)


def return_reservation(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    return _close(ctx, payload, "returned")


def cancel_reservation(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    return _close(ctx, payload, "cancelled")
