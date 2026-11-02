"""上手引導（F§4 FirstRunGuide）：三項進度依實際紀錄判斷，開啟頁面不算完成。"""

import re
from typing import Any

from src.modules.workbench.index import World

_RECORDS = re.compile(
    r"^(product|wallet|customer|contact|case|deal|task|milestone|bom"
    r"|office\.(unit|staff|shift|attendance|request|equipment|reservation|notice))"
    r"\.(create|update)$"
)
_OPERATIONS = frozenset(
    {
        "order.ship",
        "service.pay",
        "workOrder.complete",
        "followup.create",
        "office.attendance.create",
        "office.request.prepare",
        "inventory.receive",
    }
)

# 起點路線：依序取第一個已啟用的模組，都沒有時指向錢包
_ROUTES: tuple[dict[str, str], ...] = (
    {
        "module": "inventory",
        "title": "把商品換成你的店務範例",
        "description": "查看示範商品，編輯名稱與模擬售價；要接單時，再準備庫存與測試幣。",
        "action": "查看我的商品",
    },
    {
        "module": "services",
        "title": "從第一項服務開始",
        "description": "查看示範服務，確認報價、交付與驗收的操作條件。",
        "action": "查看我的服務",
    },
    {
        "module": "crm",
        "title": "建立第一位模擬客戶",
        "description": "新增虛構客戶，記下需求，再安排下一次跟進。",
        "action": "前往客戶管理",
    },
    {
        "module": "administration",
        "title": "安排第一個班次",
        "description": "從組織與假員工開始，依畫面引導排班；也可明確加入合成示範。",
        "action": "前往行政工作台",
    },
    {
        "module": "projects",
        "title": "安排第一件待辦",
        "description": "新增工作名稱、到期時間與說明，完成後更新狀態。",
        "action": "前往任務管理",
    },
)
_WALLET_ROUTE = {
    "module": "wallets",
    "title": "認識測試幣錢包",
    "description": "查看商家與買家錢包。補充 SIM 測試幣會在你確認後才執行。",
    "action": "查看測試幣錢包",
}


def first_run(w: World) -> dict[str, Any]:
    actions = {h.get("action") for h in w.collection("history")}
    actions.discard(None)
    records = any(_RECORDS.match(a) for a in actions if isinstance(a, str))
    inventory_only = w.has("inventory") and not any(
        w.has(m) for m in ("sales", "manufacturing", "services")
    )
    operation = (
        bool(actions & _OPERATIONS)
        or any(r.get("status") == "done" for r in w.rows("task"))
        or any(r.get("status") == "done" for r in w.rows("milestone"))
        or (w.has("wallets") and "wallet.fund" in actions)
        or (inventory_only and "product.update" in actions)
    )
    route = next((r for r in _ROUTES if w.has(r["module"])), _WALLET_ROUTE)
    return {
        "progress": [
            {"id": "workspace", "label": "工作區已建立", "done": True},
            {"id": "records", "label": "新增或調整資料", "done": records},
            {"id": "operation", "label": "完成模擬操作", "done": operation},
        ],
        "route": dict(route),
    }
