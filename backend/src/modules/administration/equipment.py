"""設備：建立與更新（A§2）。代碼與所屬單位不可變更。"""

import uuid
from typing import Any

from src.core.ids import new_id
from src.modules.administration import validators as v
from src.modules.administration.entity import AdmEquipment
from src.modules.administration.lookup import active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import EQUIPMENT_STATES
from src.platform.context import CommandContext


def create_equipment(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.equipment.create", payload)
    unit = active_unit(ctx, p["unit_id"])
    row = AdmEquipment(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        code=v.text(p["code"], 32),
        name=v.text(p["name"]),
        unit_id=unit.id,
        state="available",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def update_equipment(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.equipment.update", payload)
    v.editable(p)
    row = row_by_id(ctx, AdmEquipment, p["id"], lock=True)
    if "name" in p:
        row.name = v.text(p["name"])
    if "state" in p:
        row.state = v.enum_value(p["state"], EQUIPMENT_STATES)
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)
