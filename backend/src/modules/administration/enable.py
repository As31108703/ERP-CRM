"""`office.enable`：在既有工作區啟用行政模組，不動其他資料（A§2）。"""

from typing import Any

from src.core.problem import ensure
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import MODULE
from src.platform.context import CommandContext


def enable(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    parse("office.enable", payload)
    workspace = ctx.require_workspace()
    ensure(MODULE not in workspace.modules, 409, "office_already_enabled", "行政模組已啟用")
    # 重新指定整個串列，ARRAY 欄位才會被標記為已變更
    workspace.modules = [*workspace.modules, MODULE]
    ctx.db.add(workspace)
    return workspace.generation_id
