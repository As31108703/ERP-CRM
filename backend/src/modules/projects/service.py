"""專案任務與里程碑（B§3.2 通用紀錄的 tasks、milestones）與示範資料（B§3.0）。

資料沿用 crm 的通用紀錄表（`crm_record`，collection 為 tasks／milestones），欄位、長度、
失單原因與參照規則都由 `platform/records.generic_create/update` 處理。
"""

import uuid
from typing import Any

from src.modules.catalog.templates import Template
from src.modules.crm.entity import CrmRecordRow
from src.platform import records
from src.platform.context import CommandContext

MODULE = "projects"
# 路徑上的集合 → action 前綴
COLLECTIONS: dict[str, str] = {"tasks": "task", "milestones": "milestone"}
DEFAULT_TASK = "確認需求"
DEFAULT_MILESTONE = "原型驗收"


def create_record(ctx: CommandContext, collection: str, p: dict[str, Any]) -> str:
    """`task.create`／`milestone.create`：回傳新紀錄 id。"""
    return records.generic_create(ctx, collection, p)


def update_record(ctx: CommandContext, collection: str, p: dict[str, Any]) -> str:
    """`task.update`／`milestone.update {id, ...}`：找不到 404 record_missing。"""
    return records.generic_update(ctx, collection, p)


# --- seed -----------------------------------------------------------------------


def _seed(ctx: CommandContext, collection: str, title: str, status: str) -> None:
    ctx.db.add(
        CrmRecordRow(
            workspace_id=uuid.UUID(ctx.workspace_id),
            collection=collection,
            title=title,
            status=status,
            created_at=ctx.now,
            updated_at=ctx.now,
        )
    )
    ctx.db.flush()


def seed_projects(ctx: CommandContext, template: Template) -> None:
    """B§3.0：啟用 projects 時建立任務（sample.task，沒有時「確認需求」，todo）與
    里程碑（sample.milestone，沒有時「原型驗收」，planned）。"""
    assert ctx.workspace is not None
    if MODULE not in ctx.workspace.modules:
        return
    sample = template.sample
    task = sample.task if sample.task is not None else DEFAULT_TASK
    milestone = sample.milestone if sample.milestone is not None else DEFAULT_MILESTONE
    _seed(ctx, "tasks", task, "todo")
    _seed(ctx, "milestones", milestone, "planned")
