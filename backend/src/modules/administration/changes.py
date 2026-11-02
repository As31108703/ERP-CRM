"""更正與封存紀錄（A§1 Change）：寫入 before／after 整列快照。"""

import uuid
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration.entity import CHANGE_LIMIT, AdmChange
from src.platform.context import CommandContext


def ensure_capacity(ctx: CommandContext) -> None:
    """紀錄最多 200 筆，舊紀錄不會被淘汰；已滿時 422 office_change_limit。"""
    count = ctx.db.exec(
        select(func.count())
        .select_from(AdmChange)
        .where(AdmChange.workspace_id == uuid.UUID(ctx.workspace_id))
    ).one()
    ensure(count < CHANGE_LIMIT, 422, "office_change_limit", "更正與封存紀錄最多 200 筆")


def append_change(
    ctx: CommandContext,
    kind: str,
    record_id: uuid.UUID,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> AdmChange:
    """新增一筆 change；`at` 為命令時間，呼叫端須讓 after["updated_at"] 等於同一時間。"""
    change = AdmChange(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        kind=kind,
        record_id=record_id,
        at=ctx.now,
        reason=reason,
        before=before,
        after=after,
    )
    ctx.db.add(change)
    ctx.db.flush()
    return change
