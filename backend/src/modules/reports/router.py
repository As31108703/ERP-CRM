"""報表 API：`GET /api/v1/reports`，與 `workspace/view` 的 `report` 為同一份計算結果。"""

from typing import Any

from fastapi import APIRouter, Depends

from src.core.problem import ensure
from src.modules.reports.service import build_report
from src.platform.context import CommandContext
from src.platform.pipeline import touch_session

router = APIRouter(prefix="/api/v1/reports")
Touch = Depends(touch_session)


@router.get("")
def report(ctx: CommandContext = Touch) -> dict[str, Any]:
    """經 touch_session 計入速率限制，不改版本與資料。"""
    ensure(ctx.workspace is not None, 409, "workspace_missing", "請先建立工作區")
    return build_report(ctx.db, ctx.workspace_id)
