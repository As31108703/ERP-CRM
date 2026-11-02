"""建立工作區時的示範資料（B§3.0）。

各業務模組在自己的 Task 以 `register_seeder` 接上 seed 函式，例如：

    register_seeder("inventory", seed_products)

seed 函式簽名為 `(ctx, template) -> None`，依 `ctx.workspace.modules` 自行判斷要不要建立資料；
執行順序即註冊順序，後面的 seed 可以讀取前面已建立的資料（例如 BOM 需要先有商品）。
seed 函式在命令管線的交易內執行，不得 commit 或 rollback。
"""

from collections.abc import Callable

from src.modules.catalog.templates import Template
from src.platform.context import CommandContext

Seeder = Callable[[CommandContext, Template], None]

# 依註冊順序保存；同名重複註冊時取代原本的函式（模組被重新匯入也不會重複執行）
_SEEDERS: dict[str, Seeder] = {}


def register_seeder(name: str, fn: Seeder) -> None:
    _SEEDERS[name] = fn


def seed_workspace(ctx: CommandContext, template: Template) -> None:
    """依序執行已註冊的 seed 函式。目前尚無業務模組，因此不建立任何資料。"""
    if ctx.workspace is None:
        raise RuntimeError("seed_workspace 需要已建立的工作區")
    for fn in list(_SEEDERS.values()):
        fn(ctx, template)
