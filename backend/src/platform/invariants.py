"""命令執行後的整體一致性檢查：依 SPEC_ORDER 執行各模組註冊的 invariants，
再依 FINAL_ORDER 執行最終檢查（跨模組預留量、工作區大小）。"""

from src.platform import registry
from src.platform.context import CommandContext


def check_all(ctx: CommandContext) -> None:
    """沒有工作區時不檢查；任一檢查拋出 Problem 時，由命令管線整筆回滾。"""
    if ctx.workspace is None:
        return
    # 讓檢查查詢看得到 handler 尚未寫出的變更
    ctx.db.flush()
    workspace_id = str(ctx.workspace.id)
    for spec in registry.all_specs():
        for check in spec.invariants:
            check(ctx.db, workspace_id)
    for check in registry.final_invariants():
        check(ctx.db, workspace_id)
