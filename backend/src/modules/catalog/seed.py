"""建立工作區時的示範資料（B§3.0）。

各業務模組在自己的 Task 以 `register_seeder(name, fn, order=...)` 接上 seed 函式。
執行順序只看 `order`（由小到大），與模組匯入順序無關；後面的 seed 可以讀取前面已建立的資料。
B§3.0 的資料有先後相依（商品先於 BOM、客戶先於案件與商機、案件先於服務草稿），
各模組使用下列固定位置：

| order | 內容 |
|---|---|
| 10 | 系統錢包與示範買家錢包（wallets） |
| 20 | 商品 A／B（inventory） |
| 30 | 客戶、案件、商機（crm） |
| 40 | 服務草稿（services） |
| 50 | BOM（manufacturing） |
| 60 | 待辦與里程碑（projects） |
| 70 | 行政資料（administration） |

seed 函式簽名為 `(ctx, template) -> None`，依 `ctx.workspace.modules` 自行判斷要不要建立資料。
seed 函式在命令管線的交易內執行，不得 commit 或 rollback。
"""

from collections.abc import Callable
from dataclasses import dataclass

from src.modules.catalog.templates import Template
from src.platform.context import CommandContext

Seeder = Callable[[CommandContext, Template], None]

SEED_WALLETS = 10
SEED_PRODUCTS = 20
SEED_CRM = 30
SEED_SERVICES = 40
SEED_MANUFACTURING = 50
SEED_PROJECTS = 60
SEED_ADMINISTRATION = 70


@dataclass(frozen=True)
class _Entry:
    order: int
    fn: Seeder


# 名稱 → 設定；同名重複註冊時取代原本的設定（模組被重新匯入也不會重複執行）
_SEEDERS: dict[str, _Entry] = {}


def register_seeder(name: str, fn: Seeder, *, order: int) -> None:
    """註冊 seed 函式；不同名稱不可共用同一個 order，避免順序依賴匯入先後。"""
    for other, entry in _SEEDERS.items():
        if other != name and entry.order == order:
            raise ValueError(f"seed 順序 {order} 已由 {other} 使用")
    _SEEDERS[name] = _Entry(order, fn)


def seed_workspace(ctx: CommandContext, template: Template) -> None:
    """依 order 由小到大執行已註冊的 seed 函式。"""
    if ctx.workspace is None:
        raise RuntimeError("seed_workspace 需要已建立的工作區")
    for entry in sorted(_SEEDERS.values(), key=lambda e: e.order):
        entry.fn(ctx, template)
