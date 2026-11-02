"""工作台 API：操作提示、待處理工作、角色視角、全站搜尋與上手引導。

全部是唯讀 GET，經 `touch_session` 計入速率限制；資料取自工作區快照（各模組的
`ModuleSpec.snapshot`），不改版本也不寫入任何資料。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from src.modules.learning.service import available_paths
from src.modules.workbench import index, queue, readiness, roles
from src.modules.workbench.first_run import first_run
from src.modules.workspace import service as workspace_service
from src.platform.context import CommandContext
from src.platform.pipeline import touch_session

router = APIRouter(prefix="/api/v1/workbench")
Touch = Depends(touch_session)
SEARCH_PAGE_MAX = 50


def _world(ctx: CommandContext) -> index.World:
    data = workspace_service.snapshot(ctx.db, ctx.require_workspace(), ctx.session_row.version)
    return index.World(data)


@router.get("")
def workbench(ctx: CommandContext = Touch) -> dict[str, Any]:
    w = _world(ctx)
    return {
        "readiness": {
            f"{r.kind}:{r.id}": readiness.readiness(w, r.kind, r.id) for r in index.index(w)
        },
        "queue": queue.work_queue(w, ctx.now),
        "roles": roles.roles(w),
    }


@router.get("/search")
def search(
    ctx: CommandContext = Touch,
    q: str = Query("", max_length=index.QUERY_MAX),
    offset: int = Query(0, ge=0),
    limit: int = Query(SEARCH_PAGE_MAX, ge=1, le=SEARCH_PAGE_MAX),
) -> dict[str, Any]:
    return index.search(_world(ctx), q, offset, limit)


@router.get("/first-run")
def first_run_guide(ctx: CommandContext = Touch) -> dict[str, Any]:
    data = first_run(_world(ctx))
    data["learning_available"] = len(available_paths(ctx.db, ctx.workspace_id))
    return data
