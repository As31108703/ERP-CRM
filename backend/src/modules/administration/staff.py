"""假員工（虛構示範人物）：建立與更新（A§2）。代碼與所屬單位不可變更。"""

import uuid
from typing import Any

from src.core.ids import new_id
from src.modules.administration import validators as v
from src.modules.administration.entity import AdmStaff
from src.modules.administration.lookup import active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import STAFF_STATUSES
from src.platform.context import CommandContext


def create_staff(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.staff.create", payload)
    unit = active_unit(ctx, p["unit_id"])
    row = AdmStaff(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        code=v.text(p["code"], 32),
        alias=v.text(p["alias"], 80),
        unit_id=unit.id,
        role_label=v.text(p.get("role_label", ""), 100, allow_empty=True),
        status="active",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def update_staff(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.staff.update", payload)
    v.editable(p)
    row = row_by_id(ctx, AdmStaff, p["id"], lock=True)
    if "alias" in p:
        row.alias = v.text(p["alias"], 80)
    if "role_label" in p:
        row.role_label = v.text(p["role_label"], 100, allow_empty=True)
    if "status" in p:
        row.status = v.enum_value(p["status"], STAFF_STATUSES)
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)
