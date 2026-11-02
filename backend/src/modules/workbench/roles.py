"""角色視角（F§5 Role Center）：每個視角的可用性、最多 4 張重點卡片與建議流程。

卡片只在所屬模組啟用時加入；target 為該種類第一筆符合的紀錄。行政卡片的 target
使用 `{module: "administration", kind: <行政種類>, id}`，前端導到 `/administration?target=`。
"""

from collections.abc import Callable
from typing import Any

from src.modules.workbench.index import Row, World, num

VIEWS = ("owner", "sales", "operations", "administration")
CARD_LIMIT = 4


def available(w: World, view: str) -> bool:
    if view == "sales":
        return any(w.has(m) for m in ("crm", "sales", "services"))
    if view == "operations":
        return any(w.has(m) for m in ("inventory", "manufacturing"))
    if view == "administration":
        return w.has("administration")
    return view == "owner"


def roles(w: World) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for view in VIEWS:
        if available(w, view):
            out[view] = {"available": True, "cards": _cards(w, view), "flow": _flow(w, view)}
        else:
            out[view] = {"available": False, "cards": [], "flow": None}
    return out


def _cards(w: World, view: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    def add(
        card_id: str,
        label: str,
        module: str,
        rows: list[Row],
        description: str,
        kind: str | None = None,
        unit: str = "筆",
    ) -> None:
        if not w.has(module):
            return
        card: dict[str, Any] = {
            "id": card_id,
            "label": label,
            "module": module,
            "count": len(rows),
            "unit": unit,
            "description": description,
        }
        first = next((r for r in rows if isinstance(r.get("id"), str)), None)
        if kind is not None and first is not None:
            card["target"] = {"module": module, "kind": kind, "id": first["id"]}
        cards.append(card)

    def open_orders() -> None:
        rows = [
            r
            for r in w.rows("order")
            if r.get("status") not in ("cancelled", "returned")
            and (
                num(r, "paid_minor") < num(r, "total_minor")
                or any(
                    num(line, "shipped_quantity") < num(line, "quantity")
                    for line in r.get("lines") or []
                )
            )
        ]
        add("open-orders", "待處理訂單", "sales", rows, "尚有未付測試幣或未出貨品項。", "order")

    def open_services() -> None:
        rows = [
            r
            for r in w.rows("service")
            if r.get("status") in ("draft", "confirmed", "changes_requested", "submitted")
            or (r.get("status") == "accepted" and num(r, "paid_minor") < num(r, "amount_minor"))
        ]
        add(
            "open-services",
            "待處理服務",
            "services",
            rows,
            "查看草稿、交付、驗收與未收足測試幣的服務。",
            "service",
        )

    def empty_stock() -> None:
        rows = [
            r
            for r in w.rows("product")
            if r.get("active") is True and num(r, "on_hand") - num(r, "reserved") <= 0
        ]
        add(
            "empty-stock",
            "無可用庫存商品",
            "inventory",
            rows,
            "啟用商品的現有數量減預留數量為 0；目前未設定安全庫存門檻。",
            "product",
            "項",
        )

    def production() -> None:
        rows = [
            r for r in w.rows("workOrder") if r.get("status") in ("planned", "reserved", "started")
        ]
        add(
            "open-work-orders",
            "進行中工單",
            "manufacturing",
            rows,
            "計畫中、已備料或製作中，尚未完工。",
            "workOrder",
        )

    def requests() -> None:
        rows = [r for r in w.administration("requests") if r.get("status") == "submitted"]
        add(
            "admin-requests",
            "待處理模擬申請",
            "administration",
            rows,
            "只計算已送出的模擬申請，不代表正式核准。",
            "request",
        )

    def tasks() -> None:
        rows = [r for r in w.rows("task") if r.get("status") in ("todo", "in_progress")]
        add("open-tasks", "進行中任務", "projects", rows, "查看待辦與進行中的任務。", "task")

    def deals() -> None:
        rows = [r for r in w.rows("deal") if r.get("status") in ("new", "open")]
        add("open-deals", "待跟進商機", "crm", rows, "查看待聯繫與進行中的商機。", "deal")

    order: dict[str, tuple[Callable[[], None], ...]] = {
        "operations": (empty_stock, production, open_orders, tasks),
        "sales": (open_orders, open_services, deals, tasks),
        "owner": (open_orders, open_services, empty_stock, production, requests, tasks, deals),
    }
    if view == "administration":
        requests()
        add(
            "scheduled-shifts",
            "已排班次",
            "administration",
            [r for r in w.administration("shifts") if r.get("status") == "scheduled"],
            "狀態仍為已排班；排班不代表已完成出勤。",
            "shift",
            "班",
        )
        add(
            "active-staff",
            "模擬在職人員",
            "administration",
            [r for r in w.administration("staff") if r.get("status") == "active"],
            "使用假名與模擬資料，尚未提供正式薪資。",
            "staff",
            "人",
        )
        add(
            "active-reservations",
            "有效設備預約",
            "administration",
            [r for r in w.administration("reservations") if r.get("status") == "reserved"],
            "查看未取消或歸還的設備預約。",
            "reservation",
        )
    else:
        for build in order[view]:
            build()
    if not cards and w.has("wallets"):
        add(
            "ledger-records",
            "模擬流水紀錄",
            "wallets",
            w.collection("ledger"),
            "查看已發生的 SIM 測試幣紀錄，不是正式會計帳。",
        )
    return cards[:CARD_LIMIT]


def _flow(w: World, view: str) -> dict[str, Any] | None:
    """依序取第一個符合的流程；步驟只保留已啟用的模組，報表永遠保留。"""

    def make(flow_id: str, title: str, description: str, steps: list[tuple[str, str]]) -> Any:
        return {
            "id": flow_id,
            "title": title,
            "description": description,
            "steps": [
                {"module": module, "label": label}
                for module, label in steps
                if module == "reports" or w.has(module)
            ],
        }

    industry = w.data.get("industry")
    if view == "administration" and w.has("administration"):
        return make(
            "admin",
            "行政日常",
            "整理模擬人員、排班與申請，操作時再逐筆確認。",
            [("administration", "開啟行政工作台")],
        )
    production_view = view == "operations" or (industry == "manufacturing" and view == "owner")
    if production_view and w.has("manufacturing"):
        return make(
            "production",
            "從材料到完工",
            "依序核對材料、製作與成本報表。點擊只會開啟頁面。",
            [
                ("inventory", "核對材料庫存"),
                ("manufacturing", "查看配方與製作單"),
                ("reports", "核對模擬報表"),
            ],
        )
    if (
        view != "operations"
        and w.has("services")
        and (not w.has("sales") or industry in ("service", "projects"))
    ):
        return make(
            "service",
            "從客戶到服務收款",
            "整理客戶需求，再確認交付與 SIM 測試幣紀錄。",
            [
                ("crm", "整理客戶與案件"),
                ("services", "查看報價與交付"),
                ("wallets", "核對測試幣錢包"),
                ("reports", "核對模擬報表"),
            ],
        )
    if view != "operations" and w.has("sales"):
        return make(
            "sales",
            "從備貨到接單出貨",
            "先備妥商品與測試幣，再到訂單頁確認操作。",
            [
                ("inventory", "準備商品與庫存"),
                ("wallets", "準備測試幣"),
                ("sales", "查看訂單與出貨"),
                ("reports", "核對模擬報表"),
            ],
        )
    if w.has("inventory"):
        return make(
            "inventory",
            "商品與存貨整理",
            "先查看商品與可用數量，再核對模擬成本紀錄。",
            [("inventory", "整理商品與庫存"), ("reports", "核對模擬報表")],
        )
    if w.has("administration"):
        return make(
            "admin",
            "行政日常",
            "從模擬人員、班表與行政申請開始。",
            [("administration", "開啟行政工作台")],
        )
    if w.has("projects"):
        return make(
            "projects",
            "安排今天的工作",
            "整理待辦與交付進度，再逐筆更新紀錄。",
            [("projects", "查看任務與里程碑")],
        )
    if w.has("crm"):
        return make(
            "crm",
            "客戶與商機整理",
            "整理客戶與商機，再決定下一個跟進動作。",
            [("crm", "查看客戶與商機")],
        )
    if w.has("wallets"):
        return make(
            "wallets",
            "核對 SIM 測試幣",
            "查看錢包與已發生的模擬流水。",
            [("wallets", "查看測試幣錢包"), ("reports", "核對模擬報表")],
        )
    return None
