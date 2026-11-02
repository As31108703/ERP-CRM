"""公告：建立、更新、封存與還原（A§2）。封存／還原的理由由伺服器寫入並建立 change 紀錄。"""

import uuid
from typing import Any

from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration import validators as v
from src.modules.administration.changes import append_change, ensure_capacity
from src.modules.administration.entity import AdmNotice
from src.modules.administration.lookup import active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import row_out
from src.platform.context import CommandContext

ARCHIVE_REASON = "封存公告"
RESTORE_REASON = "還原公告"


def _unit_id(ctx: CommandContext, value: Any) -> uuid.UUID | None:
    """null 表示全體；指定時須為啟用中的單位。"""
    return None if value is None else active_unit(ctx, value).id


def create_notice(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.notice.create", payload)
    unit_id = _unit_id(ctx, p.get("unit_id"))
    row = AdmNotice(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        title=v.text(p["title"]),
        body=v.text(p.get("body", ""), 2000, allow_empty=True),
        unit_id=unit_id,
        pinned=v.boolean(p.get("pinned", False), "公告置頂狀態不符"),
        due_at=v.optional_instant(p.get("due_at")),
        archived=False,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    return str(row.id)


def update_notice(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """一般更新：不建立 change 紀錄，封存中的公告也可以更新。"""
    p = parse("office.notice.update", payload)
    v.editable(p)
    row = row_by_id(ctx, AdmNotice, p["id"], lock=True)
    if "unit_id" in p:
        row.unit_id = _unit_id(ctx, p["unit_id"])
    if "title" in p:
        row.title = v.text(p["title"])
    if "body" in p:
        row.body = v.text(p["body"], 2000, allow_empty=True)
    if "pinned" in p:
        row.pinned = v.boolean(p["pinned"], "公告置頂狀態不符")
    if "due_at" in p:
        row.due_at = v.optional_instant(p["due_at"])
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)


def _set_archived(ctx: CommandContext, payload: dict[str, Any], archive: bool) -> str | None:
    action = "office.notice.archive" if archive else "office.notice.restore"
    p = parse(action, payload)
    row = row_by_id(ctx, AdmNotice, p["id"], lock=True)
    ensure(
        row.archived != archive,
        409,
        "office_transition_invalid",
        "公告已封存" if archive else "公告尚未封存",
    )
    ensure_capacity(ctx)
    before = row_out("notices", row)
    row.archived = archive
    row.updated_at = ctx.now
    ctx.db.add(row)
    append_change(
        ctx,
        "notice.archive" if archive else "notice.restore",
        row.id,
        ARCHIVE_REASON if archive else RESTORE_REASON,
        before,
        row_out("notices", row),
    )
    return str(row.id)


def archive_notice(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    return _set_archived(ctx, payload, True)


def restore_notice(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    return _set_archived(ctx, payload, False)
