"""班次：建立、附理由更正、取消、完成與複製整週（A§2）。

班次與手動出勤共用「時段」欄位（staff_id、unit_id、start_at、end_at、break_minutes、note），
建立與更正的驗證也共用，出勤模組直接引用這裡的 segment_values／segment_edits。
"""

import uuid
from datetime import UTC, timedelta
from typing import Any

from sqlmodel import col, select

from src.core import clock
from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration import validators as v
from src.modules.administration.corrections import correct_record
from src.modules.administration.entity import AdmShift, by_seq
from src.modules.administration.lookup import active_staff, active_unit, row_by_id
from src.modules.administration.schema import parse
from src.platform.context import CommandContext

SEGMENT_FIELDS = ("start_at", "end_at", "break_minutes", "note")


def segment_values(ctx: CommandContext, p: dict[str, Any]) -> dict[str, Any]:
    """新時段：單位與員工須啟用且員工屬於該單位；最長 48 小時、對齊整分鐘。"""
    unit = active_unit(ctx, p["unit_id"])
    staff = active_staff(ctx, p["staff_id"], unit.id)
    start, end = v.interval(p["start_at"], p["end_at"])
    return {
        "staff_id": staff.id,
        "unit_id": unit.id,
        "start_at": start,
        "end_at": end,
        "break_minutes": v.break_minutes(p.get("break_minutes", 0), start, end),
        "note": v.text(p.get("note", ""), 1000, allow_empty=True),
    }


def correction_fields(p: dict[str, Any], fields: tuple[str, ...]) -> None:
    ensure(
        any(key in p for key in fields),
        422,
        "office_fields_invalid",
        "請指定要更正的欄位並填寫理由",
    )


def segment_edits(row: Any, p: dict[str, Any]) -> dict[str, Any]:
    """更正後的時段：未提供的欄位沿用現值，休息分鐘依新的起訖重新檢查。"""
    correction_fields(p, SEGMENT_FIELDS)
    start, end = v.interval(
        p.get("start_at", clock.iso(row.start_at)), p.get("end_at", clock.iso(row.end_at))
    )
    edits: dict[str, Any] = {
        "start_at": start,
        "end_at": end,
        "break_minutes": v.break_minutes(p.get("break_minutes", row.break_minutes), start, end),
    }
    if "note" in p:
        edits["note"] = v.text(p["note"], 1000, allow_empty=True)
    return edits


def create_shift(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.shift.create", payload)
    row = AdmShift(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        **segment_values(ctx, p),
        status="scheduled",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def _scheduled(ctx: CommandContext, row_id: Any, message: str) -> AdmShift:
    row = row_by_id(ctx, AdmShift, row_id, lock=True)
    ensure(row.status == "scheduled", 409, "office_transition_invalid", message)
    return row


def update_shift(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.shift.update", payload)
    row = _scheduled(ctx, p["id"], "只有已排定的班次可以更正")
    edits = segment_edits(row, p)
    return correct_record(ctx, "shifts", row.id, "shift.update", edits, p["reason"])


def _finish(ctx: CommandContext, payload: dict[str, Any], status: str) -> str | None:
    p = parse("office.shift.cancel" if status == "cancelled" else "office.shift.complete", payload)
    row = _scheduled(ctx, p["id"], "只有已排定的班次可以取消或標記完成")
    if status == "completed":
        ensure(
            row.end_at <= ctx.now,
            409,
            "office_shift_not_finished",
            "班次尚未到結束時間，不能標記完成",
        )
    row.status = status
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)


def cancel_shift(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """取消後釋出時段。"""
    return _finish(ctx, payload, "cancelled")


def complete_shift(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """只改班次狀態，不會建立出勤紀錄。"""
    return _finish(ctx, payload, "completed")


def copy_week(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """把來源週（台北週一 00:00 起 7 天，依開始時間判斷）非取消的班次複製到目標週。

    已完成的班次也會複製；複本一律為 scheduled、新的識別與時間戳。整批與既有資料一起由
    invariants 檢查（重疊 409 office_time_conflict、超過 200 筆 office_record_limit），
    任何一筆失敗就整批不寫入。回傳第一筆複本的 id。
    """
    p = parse("office.shift.copy_week", payload)
    source_start = clock.taipei_monday(p["from_date"]).astimezone(UTC)
    target_start = clock.taipei_monday(p["to_date"]).astimezone(UTC)
    ensure(source_start != target_start, 422, "office_week_invalid", "來源週與目標週不可相同")
    shift_by = target_start - source_start
    stmt = (
        select(AdmShift)
        .where(
            AdmShift.workspace_id == uuid.UUID(ctx.workspace_id),
            AdmShift.status != "cancelled",
            col(AdmShift.start_at) >= source_start,
            col(AdmShift.start_at) < source_start + timedelta(days=7),
        )
        .order_by(by_seq(AdmShift))
    )
    source = list(ctx.db.exec(stmt))
    ensure(len(source) > 0, 422, "office_week_empty", "來源週沒有可複製的班次")
    copies = []
    for row in source:
        copied = AdmShift(
            id=uuid.UUID(new_id()),
            workspace_id=row.workspace_id,
            staff_id=row.staff_id,
            unit_id=row.unit_id,
            start_at=row.start_at + shift_by,
            end_at=row.end_at + shift_by,
            break_minutes=row.break_minutes,
            note=row.note,
            status="scheduled",
            created_at=ctx.now,
            updated_at=ctx.now,
        )
        ctx.db.add(copied)
        # 逐筆 flush，讓 seq 依來源順序配發
        ctx.db.flush()
        copies.append(copied)
    return str(copies[0].id)
