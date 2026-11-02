"""手動出勤（非打卡）：建立、附理由更正與作廢（A§2）。

作廢只把 voided 設為 true 並留下 change 紀錄；紀錄仍保留，但不再計入工時、不再佔用時段。
完成班次不會自動產生出勤，兩者彼此獨立。
"""

import uuid
from typing import Any

from sqlmodel import Session, select

from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration.corrections import correct_record
from src.modules.administration.entity import AdmAttendance
from src.modules.administration.lookup import row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.shifts import segment_edits, segment_values
from src.platform.context import CommandContext


def create_attendance(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.attendance.create", payload)
    row = AdmAttendance(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        **segment_values(ctx, p),
        voided=False,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def _not_voided(ctx: CommandContext, row_id: Any, message: str) -> AdmAttendance:
    row = row_by_id(ctx, AdmAttendance, row_id, lock=True)
    ensure(not row.voided, 409, "office_transition_invalid", message)
    return row


def update_attendance(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.attendance.update", payload)
    row = _not_voided(ctx, p["id"], "已作廢的出勤不可再更正")
    edits = segment_edits(row, p)
    return correct_record(ctx, "attendance", row.id, "attendance.update", edits, p["reason"])


def void_attendance(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.attendance.void", payload)
    row = _not_voided(ctx, p["id"], "出勤已作廢")
    edits = {"voided": True}
    return correct_record(ctx, "attendance", row.id, "attendance.void", edits, p["reason"])


def actual_work_minutes(db: Session, workspace_id: str) -> int:
    """實際工時（A§4 actual_work_minutes）：未作廢出勤的（結束 − 開始）分鐘減休息，不截斷。"""
    stmt = select(AdmAttendance).where(
        AdmAttendance.workspace_id == uuid.UUID(workspace_id),
        AdmAttendance.voided == False,  # noqa: E712
    )
    return sum(
        round((row.end_at - row.start_at).total_seconds() / 60) - row.break_minutes
        for row in db.exec(stmt)
    )
