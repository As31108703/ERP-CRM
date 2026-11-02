"""組織單位：建立與更新（A§2）。上層不可變更；停用受下層資料阻擋的規則在 invariants。"""

import uuid
from typing import Any

from src.core.ids import new_id
from src.modules.administration import validators as v
from src.modules.administration.entity import AdmUnit
from src.modules.administration.lookup import active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import UNIT_KINDS
from src.platform.context import CommandContext


def create_unit(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.unit.create", payload)
    parent_id = p.get("parent_id")
    parent = active_unit(ctx, parent_id) if parent_id is not None else None
    row = AdmUnit(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        name=v.text(p["name"]),
        kind=v.enum_value(p["kind"], UNIT_KINDS),
        parent_id=parent.id if parent is not None else None,
        active=True,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def update_unit(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.unit.update", payload)
    v.editable(p)
    row = row_by_id(ctx, AdmUnit, p["id"], lock=True)
    if "name" in p:
        row.name = v.text(p["name"])
    if "active" in p:
        row.active = v.boolean(p["active"], "單位啟用狀態不符")
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)
