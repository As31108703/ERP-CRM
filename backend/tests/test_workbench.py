"""工作台衍生資料：操作提示、待處理工作、角色視角、全站搜尋與上手引導（F§2、F§4、F§5）。"""

from datetime import UTC, datetime
from typing import Any

import pytest

from src.core import clock
from tests.helpers import ApiClient

WORKBENCH = "/api/v1/workbench"
SEARCH = f"{WORKBENCH}/search"
FIRST_RUN = f"{WORKBENCH}/first-run"
PRODUCTS = "/api/v1/inventory/products"
QUOTES = "/api/v1/crm/quotes"


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _bench(api: ApiClient) -> dict[str, Any]:
    r = api.get(WORKBENCH)
    assert r.status_code == 200, r.text
    return r.json()


def _search(api: ApiClient, q: str, **params: Any) -> dict[str, Any]:
    r = api.get(SEARCH, params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _stocked_product(api: ApiClient, quantity: int = 5) -> str:
    business = _wallet(api.snapshot(), "business")["id"]
    api.ok("POST", f"/api/v1/wallets/{business}/fund", {"amount_minor": 500 * quantity})
    pid = api.ok(
        "POST",
        PRODUCTS,
        {"name": "測試商品", "sku": "T-001", "price_minor": 900, "cost_minor": 500},
    )["result"]
    api.ok("POST", f"{PRODUCTS}/{pid}/receive", {"quantity": quantity})
    return pid


def _unpaid_order(api: ApiClient) -> tuple[str, str]:
    """建立買家沒有測試幣的訂單，回傳 (訂單 id, 買家錢包 id)。"""
    pid = _stocked_product(api)
    buyer = _wallet(api.snapshot(), "buyer")["id"]
    body = {"buyer_wallet_id": buyer, "lines": [{"product_id": pid, "quantity": 1}]}
    return api.ok("POST", "/api/v1/sales/orders", body)["result"], buyer


# --- 操作提示 -------------------------------------------------------------------------


def test_order_readiness_buyer_no_funds(api: ApiClient) -> None:
    api.setup()
    order, buyer = _unpaid_order(api)
    ready = _bench(api)["readiness"][f"order:{order}"]
    assert ready["summary"] == "尚欠 9.00 SIM，請先準備買家測試幣。"
    assert ready["blockers"] == [
        {
            "message": "買家沒有可用測試幣，尚欠 9.00 SIM。",
            "target": {"module": "wallets", "kind": "wallet", "id": buyer},
        }
    ]
    # 買家有餘額後不再阻擋，並提示最多可先支付的金額
    api.ok("POST", f"/api/v1/wallets/{buyer}/fund", {"amount_minor": 400})
    ready = _bench(api)["readiness"][f"order:{order}"]
    assert ready["blockers"] == []
    assert ready["summary"] == "尚欠 9.00 SIM，目前可先支付最多 4.00 SIM；允許部分付款。"


def test_readiness_keys_cover_enabled_records_only(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "wallets"])
    ws = api.snapshot()
    readiness = _bench(api)["readiness"]
    product = ws["products"][0]
    assert readiness[f"product:{product['id']}"] == {
        "summary": "共用庫存：現有 0 件、預留 0 件、可用 0 件。",
        "blockers": [],
    }
    assert ws["customers"], "示範客戶應存在於未啟用 crm 的工作區"
    assert not any(key.startswith(("customer:", "deal:", "case:")) for key in readiness)


# --- 待處理工作 -----------------------------------------------------------------------


def test_queue_attention_first(api: ApiClient) -> None:
    api.setup()
    order, buyer = _unpaid_order(api)
    queue = _bench(api)["queue"]
    priorities = [item["priority"] for item in queue]
    assert "attention" in priorities and "next" in priorities
    first_next = priorities.index("next")
    assert all(p == "next" for p in priorities[first_next:])
    pay = next(item for item in queue if item["id"] == f"order:{order}:pay")
    assert pay == {
        "id": f"order:{order}:pay",
        "target": {"module": "wallets", "kind": "wallet", "id": buyer},
        "title": f"訂單 {order[:8]}",
        "description": "買家沒有可用測試幣，尚欠 9.00 SIM。",
        "priority": "attention",
        "label": "準備買家測試幣",
    }
    task = api.snapshot()["tasks"][0]
    progress = next(item for item in queue if item["id"] == f"task:{task['id']}:progress")
    assert progress["priority"] == "next"
    assert progress["label"] == "更新進度"
    assert progress["target"] == {"module": "projects", "kind": "task", "id": task["id"]}


def test_expired_quote_in_queue(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    body = {"case_id": case, "amount_minor": 1000, "expires_at": "2030-01-01T00:00:00Z"}
    quote = api.ok("POST", QUOTES, body)["result"]
    api.ok("POST", f"{QUOTES}/{quote}/issue", {})
    item_id = f"quote:{quote}:expired"
    assert all(item["id"] != item_id for item in _bench(api)["queue"])

    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2030, 1, 1, tzinfo=UTC))
    queue = _bench(api)["queue"]
    item = next(item for item in queue if item["id"] == item_id)
    assert item["priority"] == "attention"
    assert item["label"] == "重新起草報價"
    assert item["description"] == "報價已過期，請回到原案件重新起草模擬報價。"
    assert item["target"] == {"module": "crm", "kind": "case", "id": case}
    assert queue[0]["priority"] == "attention"
    # 報價在啟用服務模組時歸到服務頁
    ready = _bench(api)["readiness"][f"quote:{quote}"]
    assert ready["summary"].startswith("報價已凍結，確認時需使用正確摘要；有效期限 ")


# --- 角色視角 -------------------------------------------------------------------------


def test_role_owner_max_4_cards(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    roles = _bench(api)["roles"]
    assert set(roles) == {"owner", "sales", "operations", "administration"}
    assert all(roles[v]["available"] for v in roles)
    owner = roles["owner"]
    assert [c["id"] for c in owner["cards"]] == [
        "open-orders",
        "open-services",
        "empty-stock",
        "open-work-orders",
    ]
    stock = owner["cards"][2]
    assert stock == {
        "id": "empty-stock",
        "label": "無可用庫存商品",
        "module": "inventory",
        "count": 2,
        "unit": "項",
        "description": "啟用商品的現有數量減預留數量為 0；目前未設定安全庫存門檻。",
        "target": {"module": "inventory", "kind": "product", "id": ws["products"][0]["id"]},
    }
    assert "target" not in owner["cards"][0]  # 沒有符合的訂單時不給 target
    admin = roles["administration"]
    assert [c["id"] for c in admin["cards"]] == [
        "admin-requests",
        "scheduled-shifts",
        "active-staff",
        "active-reservations",
    ]
    assert admin["flow"] == {
        "id": "admin",
        "title": "行政日常",
        "description": "整理模擬人員、排班與申請，操作時再逐筆確認。",
        "steps": [{"module": "administration", "label": "開啟行政工作台"}],
    }


def test_role_views_unavailable_without_modules(api: ApiClient) -> None:
    api.setup("general", modules=["wallets"])
    roles = _bench(api)["roles"]
    assert roles["owner"]["available"] is True
    for view in ("sales", "operations", "administration"):
        assert roles[view] == {"available": False, "cards": [], "flow": None}
    # 沒有其他卡片且啟用錢包時，改顯示模擬流水紀錄
    assert [c["id"] for c in roles["owner"]["cards"]] == ["ledger-records"]
    assert roles["owner"]["flow"]["title"] == "核對 SIM 測試幣"


def test_role_admin_cards_target_admin_records(api: ApiClient) -> None:
    api.setup()
    api.ok("POST", "/api/v1/administration/demo", {"preset": "store", "week_start": "2026-11-02"})
    office = api.snapshot()["administration"]
    cards = {c["id"]: c for c in _bench(api)["roles"]["administration"]["cards"]}
    staff = [s for s in office["staff"] if s["status"] == "active"]
    assert cards["active-staff"]["count"] == len(staff)
    assert cards["active-staff"]["unit"] == "人"
    assert cards["active-staff"]["target"] == {
        "module": "administration",
        "kind": "staff",
        "id": staff[0]["id"],
    }
    submitted = [r for r in office["requests"] if r["status"] == "submitted"]
    assert cards["admin-requests"]["count"] == len(submitted)
    # 行政資料不在全站搜尋索引內
    notice = office["notices"][0]["title"]
    assert _search(api, notice) == {"total": 0, "items": []}


def test_flow_manufacturing_template_owner(api: ApiClient) -> None:
    api.setup("manufacturing")
    roles = _bench(api)["roles"]
    flow = roles["owner"]["flow"]
    assert flow["title"] == "從材料到完工"
    assert flow["steps"] == [
        {"module": "inventory", "label": "核對材料庫存"},
        {"module": "manufacturing", "label": "查看配方與製作單"},
        {"module": "reports", "label": "核對模擬報表"},
    ]
    assert roles["sales"]["flow"]["title"] == "從備貨到接單出貨"
    assert roles["administration"]["available"] is False


def test_flow_service_template_owner(api: ApiClient) -> None:
    api.setup("service")
    flow = _bench(api)["roles"]["owner"]["flow"]
    assert flow["title"] == "從客戶到服務收款"
    # 未啟用的模組步驟被濾掉，報表永遠保留
    assert [s["module"] for s in flow["steps"]] == ["crm", "services", "wallets", "reports"]


# --- 全站搜尋 -------------------------------------------------------------------------


def test_search_tokens_all_must_match(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    product = next(p for p in ws["products"] if p["sku"] == "DEMO-001")
    found = _search(api, "示範  成品")
    # 商品本身與引用它的 BOM 都會命中（BOM 以關聯商品名稱建立索引）
    assert [(i["kind"], i["module"]) for i in found["items"]] == [
        ("product", "inventory"),
        ("bom", "manufacturing"),
    ]
    assert found["items"][0] == {
        "module": "inventory",
        "kind": "product",
        "id": product["id"],
        "title": product["name"],
        "description": "商品 · 啟用中",
        "status_label": "啟用中",
    }
    assert _search(api, "示範 不存在的詞") == {"total": 0, "items": []}
    assert _search(api, "   ") == {"total": 0, "items": []}


def test_search_relations_and_paging(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    customer = ws["customers"][0]
    # 商機、案件以客戶名稱關聯，也能用客戶名稱找到
    hits = _search(api, customer["name"])
    kinds = {item["kind"] for item in hits["items"]}
    assert {"customer", "deal", "case"} <= kinds
    page = _search(api, customer["name"], offset=1, limit=1)
    assert page["total"] == hits["total"]
    assert page["items"] == hits["items"][1:2]


def test_search_disabled_module_excluded(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "wallets"])
    ws = api.snapshot()
    assert any("示範" in (c["name"] or "") for c in ws["customers"])
    found = _search(api, "示範")
    assert found["total"] >= 1
    assert {item["module"] for item in found["items"]} <= {"inventory", "wallets"}


def test_search_nfkc_fullwidth(api: ApiClient) -> None:
    api.setup()
    found = _search(api, "ＤＥＭＯ　００１")
    assert any(
        item["kind"] == "product" and item["description"].startswith("商品")
        for item in found["items"]
    )
    product = next(p for p in api.snapshot()["products"] if p["sku"] == "DEMO-001")
    assert product["id"] in {item["id"] for item in found["items"]}


def test_search_query_too_long_422(api: ApiClient) -> None:
    api.setup()
    r = api.get(SEARCH, params={"q": "a" * 121})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "payload_invalid"
    assert api.get(SEARCH, params={"q": "a" * 120}).status_code == 200


def test_workbench_without_workspace_409(api: ApiClient) -> None:
    for path in (WORKBENCH, SEARCH + "?q=x", FIRST_RUN):
        r = api.get(path)
        assert r.status_code == 409, path
        assert r.json()["error"]["code"] == "workspace_missing"


# --- 上手引導 -------------------------------------------------------------------------


def _first_run(api: ApiClient) -> dict[str, Any]:
    r = api.get(FIRST_RUN)
    assert r.status_code == 200, r.text
    return r.json()


def test_first_run_progress(api: ApiClient) -> None:
    api.setup()
    data = _first_run(api)
    assert data == {
        "progress": [
            {"id": "workspace", "label": "工作區已建立", "done": True},
            {"id": "records", "label": "新增或調整資料", "done": False},
            {"id": "operation", "label": "完成模擬操作", "done": False},
        ],
        "route": {
            "module": "inventory",
            "title": "把商品換成你的店務範例",
            "description": "查看示範商品，編輯名稱與模擬售價；要接單時，再準備庫存與測試幣。",
            "action": "查看我的商品",
        },
    }
    product = api.snapshot()["products"][0]["id"]
    api.ok("PATCH", f"{PRODUCTS}/{product}", {"name": "我的商品"})
    assert [p["done"] for p in _first_run(api)["progress"]] == [True, True, False]
    # 錢包啟用時，補充測試幣算完成一次模擬操作
    business = _wallet(api.snapshot(), "business")["id"]
    api.ok("POST", f"/api/v1/wallets/{business}/fund", {"amount_minor": 100})
    assert [p["done"] for p in _first_run(api)["progress"]] == [True, True, True]


def test_first_run_route_follows_modules(api: ApiClient) -> None:
    api.setup("service")
    route = _first_run(api)["route"]
    assert (route["module"], route["action"]) == ("services", "查看我的服務")


def test_work_order_short_material_in_queue(api: ApiClient) -> None:
    api.setup("manufacturing")
    ws = api.snapshot()
    bom = ws["boms"][0]
    material = bom["components"][0]["product_id"]
    name = next(p["name"] for p in ws["products"] if p["id"] == material)
    body = {"bom_id": bom["id"], "quantity": 2}
    wo = api.ok("POST", "/api/v1/manufacturing/work-orders", body)["result"]
    need = bom["components"][0]["quantity"] * 2
    bench = _bench(api)
    message = f"「{name}」需要 {need} 件，目前可用 0 件；依本工單凍結的 BOM。"
    assert bench["readiness"][f"workOrder:{wo}"] == {
        "summary": "依凍結 BOM 核對共享庫存；材料足夠後可備料。",
        "blockers": [
            {
                "message": message,
                "target": {"module": "inventory", "kind": "product", "id": material},
            }
        ],
    }
    item = next(i for i in bench["queue"] if i["id"] == f"workOrder:{wo}:planned")
    assert (item["label"], item["priority"], item["description"]) == (
        "補足工單材料",
        "attention",
        message,
    )
    card = next(c for c in bench["roles"]["operations"]["cards"] if c["id"] == "open-work-orders")
    assert card["count"] == 1
    assert card["target"] == {"module": "manufacturing", "kind": "workOrder", "id": wo}
