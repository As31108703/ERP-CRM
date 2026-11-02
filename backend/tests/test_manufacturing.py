"""製造：版本化且不可變的 BOM（循環偵測）、工單 planned → reserved → started → completed
（材料 FIFO 耗用與完工成本分攤）、取消釋放預留，以及一致性檢查、seed 與快照還原。"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.modules.catalog.templates import TEMPLATES
from src.modules.manufacturing.router import SPEC as MANUFACTURING_SPEC
from tests.helpers import ApiClient, workspace_ctx

BOMS = "/api/v1/manufacturing/boms"
WORK_ORDERS = "/api/v1/manufacturing/work-orders"
PRODUCTS = "/api/v1/inventory/products"
MISSING = "00000000-0000-4000-8000-000000000000"
BOM_KEYS = {"id", "product_id", "components", "revision", "created_at"}
WORK_ORDER_KEYS = {
    "id",
    "learning_run_id",
    "bom_id",
    "bom_snapshot",
    "quantity",
    "status",
    "actual_cost_minor",
    "consumed_material_lots",
    "created_at",
    "updated_at",
}


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _product(ws: dict[str, Any], product_id: str) -> dict[str, Any]:
    return next(p for p in ws["products"] if p["id"] == product_id)


def _bom(ws: dict[str, Any], bom_id: str) -> dict[str, Any]:
    return next(b for b in ws["boms"] if b["id"] == bom_id)


def _wo(ws: dict[str, Any], wo_id: str) -> dict[str, Any]:
    return next(o for o in ws["work_orders"] if o["id"] == wo_id)


def _fund_business(api: ApiClient, amount: int = 10_000_000) -> None:
    business = _wallet(api.snapshot(), "business")["id"]
    api.ok("POST", f"/api/v1/wallets/{business}/fund", {"amount_minor": amount})


def _receive(api: ApiClient, product_id: str, quantity: int) -> None:
    api.ok("POST", f"{PRODUCTS}/{product_id}/receive", {"quantity": quantity})


def _new_product(api: ApiClient, name: str, cost: int = 0) -> str:
    body = {"name": name, "sku": name, "price_minor": 0, "cost_minor": cost}
    return api.ok("POST", PRODUCTS, body)["result"]


def _set_cost(api: ApiClient, product_id: str, cost: int) -> None:
    api.ok("PATCH", f"{PRODUCTS}/{product_id}", {"cost_minor": cost})


def _create_bom(api: ApiClient, product_id: str, components: list[tuple[str, int]]) -> str:
    body = {
        "product_id": product_id,
        "components": [{"product_id": p, "quantity": q} for p, q in components],
    }
    return api.ok("POST", BOMS, body)["result"]


def _create_wo(api: ApiClient, bom_id: str, quantity: int, **extra: Any) -> str:
    return api.ok("POST", WORK_ORDERS, {"bom_id": bom_id, "quantity": quantity, **extra})["result"]


def _act(api: ApiClient, wo_id: str, verb: str) -> None:
    api.ok("POST", f"{WORK_ORDERS}/{wo_id}/{verb}", {})


def _run(api: ApiClient, wo_id: str, *verbs: str) -> None:
    for verb in verbs:
        _act(api, wo_id, verb)


def _products_ab(ws: dict[str, Any]) -> tuple[str, str]:
    a, b = ws["products"][:2]
    return a["id"], b["id"]


def _stock_value_balanced(ws: dict[str, Any]) -> bool:
    purchased = sum(x["total_minor"] for x in ws["purchases"])
    held = sum(p["stock_value_minor"] for p in ws["products"])
    return purchased == held


# --- seed -----------------------------------------------------------------------


@pytest.mark.parametrize("industry", ["manufacturing", "restaurant", "general"])
def test_seed_bom(api: ApiClient, industry: str) -> None:
    api.setup(industry)
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [bom] = ws["boms"]
    assert set(bom) == BOM_KEYS
    quantity = TEMPLATES[industry].sample.bom_quantity or 1
    assert bom["product_id"] == a
    assert bom["components"] == [{"product_id": b, "quantity": quantity}]
    assert bom["revision"] == 1
    assert ws["work_orders"] == []
    assert ws["history"] == []


@pytest.mark.parametrize(
    ("industry", "modules"),
    [("retail", None), ("general", ["inventory", "wallets", "sales"])],
)
def test_seed_no_bom_without_module(
    api: ApiClient, industry: str, modules: list[str] | None
) -> None:
    api.setup(industry, modules=modules)
    assert api.snapshot()["boms"] == []


# --- BOM ------------------------------------------------------------------------


def test_bom_cycle_rejected(api: ApiClient) -> None:
    """先建 A←B，再建 B←A：422 bom_cycle，資料不變。"""
    api.setup("general")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate(
        "POST", BOMS, {"product_id": b, "components": [{"product_id": a, "quantity": 1}]}
    )
    assert _error(r) == (422, "bom_cycle")
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_bom_cycle_indirect(api: ApiClient) -> None:
    """A←B（seed）、B←C，再建 C←A 形成三角循環。"""
    api.setup("general")
    a, b = _products_ab(api.snapshot())
    c = _new_product(api, "C")
    _create_bom(api, b, [(c, 1)])
    r = api.mutate(
        "POST", BOMS, {"product_id": c, "components": [{"product_id": a, "quantity": 1}]}
    )
    assert _error(r) == (422, "bom_cycle")


def test_bom_cycle_across_revisions(api: ApiClient) -> None:
    """命令檢查只看各成品最新版本的邊（A←C 取代 A←B），但所有版本合併後 A→B→A 仍是循環，
    由一致性檢查擋下。"""
    api.setup("general")
    a, b = _products_ab(api.snapshot())
    c = _new_product(api, "C")
    _create_bom(api, a, [(c, 1)])
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate(
        "POST", BOMS, {"product_id": b, "components": [{"product_id": a, "quantity": 1}]}
    )
    assert _error(r) == (422, "bom_cycle")
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_revision_increments(api: ApiClient) -> None:
    api.setup("general")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [seeded] = ws["boms"]
    c = _new_product(api, "C")
    wo = _create_wo(api, seeded["id"], 1)
    rev2 = _create_bom(api, a, [(b, 3), (c, 1)])
    rev3 = _create_bom(api, a, [(c, 2)])
    other = _create_bom(api, c, [(b, 1)])
    ws = api.snapshot()
    assert [x["id"] for x in ws["boms"]] == [seeded["id"], rev2, rev3, other]
    assert [x["revision"] for x in ws["boms"]] == [1, 2, 3, 1]
    assert _bom(ws, rev2)["components"] == [
        {"product_id": b, "quantity": 3},
        {"product_id": c, "quantity": 1},
    ]
    # 舊版本不可變；既有工單的快照仍是第 1 版
    assert _bom(ws, seeded["id"]) == seeded
    assert _wo(ws, wo)["bom_snapshot"] == seeded
    assert ws["history"][-1]["action"] == "bom.create"
    assert ws["history"][-1]["result"] == other


# --- 工單流程 ---------------------------------------------------------------------


def test_work_order_happy_path(api: ApiClient) -> None:
    api.setup("manufacturing")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [bom] = ws["boms"]
    _fund_business(api)
    _receive(api, b, 10)
    wo = _create_wo(api, bom["id"], 3, learning_run_id="run-abcdef01")
    ws = api.snapshot()
    order = _wo(ws, wo)
    assert set(order) == WORK_ORDER_KEYS
    assert order["status"] == "planned"
    assert order["bom_snapshot"] == bom
    assert order["quantity"] == 3
    assert order["learning_run_id"] == "run-abcdef01"
    assert order["actual_cost_minor"] is None
    assert order["consumed_material_lots"] == []

    _act(api, wo, "reserve")
    ws = api.snapshot()
    assert _wo(ws, wo)["status"] == "reserved"
    assert _product(ws, b)["reserved"] == 6
    created_at = _wo(ws, wo)["created_at"]

    _act(api, wo, "start")
    assert _wo(api.snapshot(), wo)["status"] == "started"

    _act(api, wo, "complete")
    ws = api.snapshot()
    order = _wo(ws, wo)
    assert order["status"] == "completed"
    assert order["created_at"] == created_at
    assert order["actual_cost_minor"] == 3000
    assert order["consumed_material_lots"] == [{"product_id": b, "quantity": 6, "cost_minor": 500}]
    material = _product(ws, b)
    assert (material["on_hand"], material["reserved"], material["stock_value_minor"]) == (
        4,
        0,
        2000,
    )
    finished = _product(ws, a)
    assert finished["on_hand"] == 3
    assert finished["stock_value_minor"] == 3000
    assert finished["lots"] == [{"quantity": 3, "cost_minor": 1000}]
    assert _stock_value_balanced(ws)
    assert [h["action"] for h in ws["history"][-4:]] == [
        "workOrder.create",
        "workOrder.reserve",
        "workOrder.start",
        "workOrder.complete",
    ]
    assert ws["history"][-1]["result"] == wo


def test_complete_cost_rounding(api: ApiClient) -> None:
    """材料成本合計 1001、做 3 件：成品批次 [(2,334),(1,333)]，actual_cost_minor 1001。"""
    api.setup("general")
    _fund_business(api)
    material = _new_product(api, "原料", cost=1)
    _receive(api, material, 1)
    _set_cost(api, material, 500)
    _receive(api, material, 2)
    finished = _new_product(api, "成品")
    bom = _create_bom(api, finished, [(material, 1)])
    wo = _create_wo(api, bom, 3)
    _run(api, wo, "reserve", "start", "complete")
    ws = api.snapshot()
    order = _wo(ws, wo)
    assert order["actual_cost_minor"] == 1001
    assert order["consumed_material_lots"] == [
        {"product_id": material, "quantity": 1, "cost_minor": 1},
        {"product_id": material, "quantity": 2, "cost_minor": 500},
    ]
    product = _product(ws, finished)
    assert [(lot["quantity"], lot["cost_minor"]) for lot in product["lots"]] == [(2, 334), (1, 333)]
    assert product["stock_value_minor"] == 1001
    assert product["on_hand"] == 3
    assert _product(ws, material)["lots"] == []
    assert _stock_value_balanced(ws)


def test_complete_even_cost_single_lot(api: ApiClient) -> None:
    """可整除時只推入一個成本層。"""
    api.setup("general")
    _fund_business(api)
    material = _new_product(api, "原料", cost=250)
    _receive(api, material, 4)
    finished = _new_product(api, "成品")
    wo = _create_wo(api, _create_bom(api, finished, [(material, 2)]), 2)
    _run(api, wo, "reserve", "start", "complete")
    ws = api.snapshot()
    assert _product(ws, finished)["lots"] == [{"quantity": 2, "cost_minor": 500}]
    assert _wo(ws, wo)["actual_cost_minor"] == 1000


def test_complete_multiple_components_fifo(api: ApiClient) -> None:
    """多個材料依 BOM 順序、各自 FIFO 耗用；耗料紀錄依耗用順序。"""
    api.setup("general")
    _fund_business(api)
    x = _new_product(api, "X", cost=10)
    y = _new_product(api, "Y", cost=7)
    _receive(api, x, 2)
    _set_cost(api, x, 20)
    _receive(api, x, 5)
    _receive(api, y, 3)
    finished = _new_product(api, "成品")
    wo = _create_wo(api, _create_bom(api, finished, [(x, 2), (y, 1)]), 2)
    _run(api, wo, "reserve", "start", "complete")
    ws = api.snapshot()
    order = _wo(ws, wo)
    assert order["consumed_material_lots"] == [
        {"product_id": x, "quantity": 2, "cost_minor": 10},
        {"product_id": x, "quantity": 2, "cost_minor": 20},
        {"product_id": y, "quantity": 2, "cost_minor": 7},
    ]
    assert order["actual_cost_minor"] == 20 + 40 + 14
    assert _product(ws, x)["lots"] == [{"quantity": 3, "cost_minor": 20}]
    assert _product(ws, y)["lots"] == [{"quantity": 1, "cost_minor": 7}]
    assert _product(ws, finished)["lots"] == [{"quantity": 2, "cost_minor": 37}]
    assert _stock_value_balanced(ws)


def test_reserve_insufficient_409_materials_insufficient(api: ApiClient) -> None:
    """可用量（on_hand - reserved）不足：409 materials_insufficient，前面已預留的材料也一併回滾。"""
    api.setup("general")
    _fund_business(api)
    x = _new_product(api, "X", cost=1)
    y = _new_product(api, "Y", cost=1)
    _receive(api, x, 10)
    _receive(api, y, 3)
    finished = _new_product(api, "成品")
    bom = _create_bom(api, finished, [(x, 1), (y, 1)])
    first = _create_wo(api, bom, 2)
    _act(api, first, "reserve")
    second = _create_wo(api, bom, 2)
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{WORK_ORDERS}/{second}/reserve", {})
    assert _error(r) == (409, "materials_insufficient")
    ws = api.snapshot()
    assert ws == before
    assert api.state()["version"] == version
    assert _product(ws, x)["reserved"] == 2
    assert _wo(ws, second)["status"] == "planned"
    # 剛好足夠時可以預留
    third = _create_wo(api, bom, 1)
    _act(api, third, "reserve")
    assert _product(api.snapshot(), y)["reserved"] == 3


def test_sales_and_work_orders_share_reservations(api: ApiClient) -> None:
    """訂單與工單的預留合併計算：訂單已佔用的材料，工單不能再預留。"""
    api.setup("general")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [bom] = ws["boms"]
    buyer = _wallet(ws, "buyer")["id"]
    _fund_business(api)
    _receive(api, b, 3)
    api.ok(
        "POST",
        "/api/v1/sales/orders",
        {"buyer_wallet_id": buyer, "lines": [{"product_id": b, "quantity": 2}]},
    )
    wo = _create_wo(api, bom["id"], 2)
    r = api.mutate("POST", f"{WORK_ORDERS}/{wo}/reserve", {})
    assert _error(r) == (409, "materials_insufficient")
    ok = _create_wo(api, bom["id"], 1)
    _act(api, ok, "reserve")
    assert _product(api.snapshot(), b)["reserved"] == 3


@pytest.mark.parametrize("steps", [(), ("reserve",), ("reserve", "start")])
def test_cancel_releases_reserved(api: ApiClient, steps: tuple[str, ...]) -> None:
    api.setup("manufacturing")
    ws = api.snapshot()
    _, b = _products_ab(ws)
    [bom] = ws["boms"]
    _fund_business(api)
    _receive(api, b, 10)
    other = _create_wo(api, bom["id"], 1)
    _act(api, other, "reserve")
    wo = _create_wo(api, bom["id"], 3)
    _run(api, wo, *steps)
    _act(api, wo, "cancel")
    ws = api.snapshot()
    order = _wo(ws, wo)
    assert order["status"] == "cancelled"
    assert order["actual_cost_minor"] is None
    material = _product(ws, b)
    # 只剩另一張工單的 2 件預留；on_hand 與成本層不變
    assert (material["reserved"], material["on_hand"]) == (2, 10)
    assert material["lots"] == [{"quantity": 10, "cost_minor": 500}]
    assert ws["history"][-1]["action"] == "workOrder.cancel"
    # 取消後的工單不能再預留
    r = api.mutate("POST", f"{WORK_ORDERS}/{wo}/reserve", {})
    assert _error(r) == (409, "production_state")


def test_no_money_moves_on_complete(api: ApiClient) -> None:
    """預留、開工、完工、取消都不動錢包與流水；庫存價值仍守恆（價值在商品間移轉）。"""
    api.setup("manufacturing")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [bom] = ws["boms"]
    _fund_business(api)
    _receive(api, b, 10)
    before = api.snapshot()
    done = _create_wo(api, bom["id"], 2)
    _run(api, done, "reserve", "start", "complete")
    dropped = _create_wo(api, bom["id"], 1)
    _run(api, dropped, "reserve", "start", "cancel")
    ws = api.snapshot()
    assert ws["wallets"] == before["wallets"]
    assert ws["ledger"] == before["ledger"]
    assert ws["purchases"] == before["purchases"]
    assert _stock_value_balanced(ws)
    total_value = sum(p["stock_value_minor"] for p in ws["products"])
    assert total_value == sum(p["stock_value_minor"] for p in before["products"]) == 5000
    assert _product(ws, a)["stock_value_minor"] == 2000
    assert _product(ws, b)["stock_value_minor"] == 3000


def test_finished_goods_can_be_sold(api: ApiClient) -> None:
    """完工成品進入 FIFO，可以照常出貨；出貨成本沿用完工成本層。"""
    api.setup("general")
    ws = api.snapshot()
    a, b = _products_ab(ws)
    [bom] = ws["boms"]
    buyer = _wallet(ws, "buyer")["id"]
    _fund_business(api)
    _receive(api, b, 2)
    wo = _create_wo(api, bom["id"], 2)
    _run(api, wo, "reserve", "start", "complete")
    price = _product(api.snapshot(), a)["price_minor"]
    api.ok("POST", f"/api/v1/wallets/{buyer}/fund", {"amount_minor": price})
    order = api.ok(
        "POST",
        "/api/v1/sales/orders",
        {"buyer_wallet_id": buyer, "lines": [{"product_id": a, "quantity": 1}]},
    )["result"]
    api.ok("POST", f"/api/v1/sales/orders/{order}/pay", {"amount_minor": price})
    line = api.snapshot()["orders"][-1]["lines"][0]["id"]
    api.ok(
        "POST", f"/api/v1/sales/orders/{order}/ship", {"lines": [{"line_id": line, "quantity": 1}]}
    )
    ws = api.snapshot()
    assert ws["orders"][-1]["lines"][0]["shipped_cost_lots"] == [
        {"quantity": 1, "cost_minor": 500, "returned": 0}
    ]
    assert _product(ws, a)["lots"] == [{"quantity": 1, "cost_minor": 500}]


def test_manufacturing_disabled_403_module_disabled(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "wallets", "sales"])
    ws = api.snapshot()
    a, b = _products_ab(ws)
    version = api.state()["version"]
    for path, body in (
        (BOMS, {"product_id": a, "components": [{"product_id": b, "quantity": 1}]}),
        (WORK_ORDERS, {"bom_id": MISSING, "quantity": 1}),
        (f"{WORK_ORDERS}/{MISSING}/reserve", {}),
        (f"{WORK_ORDERS}/{MISSING}/start", {}),
        (f"{WORK_ORDERS}/{MISSING}/complete", {}),
        (f"{WORK_ORDERS}/{MISSING}/cancel", {}),
        # 禁用鍵名與模組未啟用同時成立時，模組閘優先
        (BOMS, {"bank": "x"}),
    ):
        r = api.mutate("POST", path, body)
        assert _error(r) == (403, "module_disabled"), path
    assert api.snapshot() == ws
    assert api.state()["version"] == version


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


class Scenario:
    """manufacturing 範本（BOM A ← B × 2）。商家補款後進貨 B 10 件（成本 500）：

    - planned：數量 3（需要 6 件，可用只剩 4 件）
    - reserved：數量 1，已預留 2 件
    - started：數量 1，已預留 2 件並開工
    - completed：數量 1，耗用 2 件
    - cancelled：數量 1，已預留後取消

    B 最後 on_hand 8、reserved 4。
    """

    def __init__(self, api: ApiClient) -> None:
        api.setup("manufacturing")
        ws = api.snapshot()
        self.a, self.b = _products_ab(ws)
        self.bom = ws["boms"][0]["id"]
        _fund_business(api)
        _receive(api, self.b, 10)
        self.planned = _create_wo(api, self.bom, 3)
        self.reserved = _create_wo(api, self.bom, 1)
        _act(api, self.reserved, "reserve")
        self.started = _create_wo(api, self.bom, 1)
        _run(api, self.started, "reserve", "start")
        self.completed = _create_wo(api, self.bom, 1)
        _run(api, self.completed, "reserve", "start", "complete")
        self.cancelled = _create_wo(api, self.bom, 1)
        _run(api, self.cancelled, "reserve", "cancel")


Make = Callable[[Scenario], tuple[str, Any]]


def _bom_body(s: Scenario, components: Any, product: str | None = None) -> tuple[str, Any]:
    return BOMS, {"product_id": product or s.a, "components": components}


def _wo_path(wo_id: str, verb: str) -> tuple[str, Any]:
    return f"{WORK_ORDERS}/{wo_id}/{verb}", {}


# (名稱, 產生請求, 狀態, 錯誤碼, 送出前竄改資料的 SQL)
_CASES: list[tuple[str, Make, int, str, str | None]] = [
    # B§3.1 通用前置檢查
    ("payload_list", lambda s: (BOMS, [1]), 422, "payload_invalid", None),
    (
        "forbidden_finance",
        lambda s: (WORK_ORDERS, {"bom_id": s.bom, "quantity": 1, "finance_ref": "x"}),
        422,
        "simulation_required",
        None,
    ),
    (
        "forbidden_on_action",
        lambda s: (f"{WORK_ORDERS}/{s.planned}/reserve", {"payment_url": "x"}),
        422,
        "simulation_required",
        None,
    ),
    (
        "protected_reserved",
        lambda s: (f"{WORK_ORDERS}/{s.reserved}/start", {"reserved": 0}),
        422,
        "protected_field",
        None,
    ),
    (
        "protected_lots",
        lambda s: (BOMS, {**_bom_body(s, [{"product_id": s.b, "quantity": 1}])[1], "lots": []}),
        422,
        "protected_field",
        None,
    ),
    (
        "learning_id_on_bom",
        lambda s: (
            BOMS,
            {
                **_bom_body(s, [{"product_id": s.b, "quantity": 1}])[1],
                "learning_run_id": "run-abcdef01",
            },
        ),
        422,
        "learning_id_invalid",
        None,
    ),
    (
        "learning_id_on_reserve",
        lambda s: (f"{WORK_ORDERS}/{s.planned}/reserve", {"learning_run_id": "run-abcdef01"}),
        422,
        "learning_id_invalid",
        None,
    ),
    (
        "learning_id_format",
        lambda s: (WORK_ORDERS, {"bom_id": s.bom, "quantity": 1, "learning_run_id": "short"}),
        422,
        "learning_id_invalid",
        None,
    ),
    # bom.create
    (
        "bom_product_missing",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1}], MISSING),
        404,
        "record_missing",
        None,
    ),
    (
        "bom_product_bad_id",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1}], "not-a-uuid"),
        404,
        "record_missing",
        None,
    ),
    (
        "bom_product_is_bom",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1}], s.bom),
        404,
        "record_missing",
        None,
    ),
    ("bom_components_missing", lambda s: (BOMS, {"product_id": s.a}), 422, "bom_invalid", None),
    ("bom_components_empty", lambda s: _bom_body(s, []), 422, "bom_invalid", None),
    (
        "bom_components_not_list",
        lambda s: _bom_body(s, {"product_id": s.b, "quantity": 1}),
        422,
        "bom_invalid",
        None,
    ),
    (
        "bom_components_31",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1}] * 31),
        422,
        "bom_invalid",
        None,
    ),
    (
        "bom_component_missing",
        lambda s: _bom_body(s, [{"product_id": MISSING, "quantity": 1}]),
        404,
        "record_missing",
        None,
    ),
    (
        "bom_component_not_object",
        lambda s: _bom_body(s, [s.b]),
        404,
        "record_missing",
        None,
    ),
    (
        "bom_component_quantity_zero",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 0}]),
        422,
        "number_invalid",
        None,
    ),
    (
        "bom_component_quantity_missing",
        lambda s: _bom_body(s, [{"product_id": s.b}]),
        422,
        "number_invalid",
        None,
    ),
    (
        "bom_component_quantity_fraction",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1.5}]),
        422,
        "number_invalid",
        None,
    ),
    (
        "bom_component_quantity_over_limit",
        lambda s: _bom_body(s, [{"product_id": s.b, "quantity": 1_000_000_001}]),
        422,
        "number_invalid",
        None,
    ),
    (
        "bom_self_component",
        lambda s: _bom_body(s, [{"product_id": s.a, "quantity": 1}]),
        422,
        "bom_cycle",
        None,
    ),
    (
        "bom_duplicate_component",
        lambda s: _bom_body(
            s, [{"product_id": s.b, "quantity": 1}, {"product_id": s.b, "quantity": 2}]
        ),
        422,
        "bom_cycle",
        None,
    ),
    (
        "bom_cycle",
        lambda s: _bom_body(s, [{"product_id": s.a, "quantity": 1}], s.b),
        422,
        "bom_cycle",
        None,
    ),
    # workOrder.create
    (
        "wo_bom_missing",
        lambda s: (WORK_ORDERS, {"bom_id": MISSING, "quantity": 1}),
        404,
        "record_missing",
        None,
    ),
    (
        "wo_bom_is_product",
        lambda s: (WORK_ORDERS, {"bom_id": s.a, "quantity": 1}),
        404,
        "record_missing",
        None,
    ),
    (
        "wo_bom_bad_id",
        lambda s: (WORK_ORDERS, {"bom_id": 1, "quantity": 1}),
        404,
        "record_missing",
        None,
    ),
    (
        "wo_quantity_missing",
        lambda s: (WORK_ORDERS, {"bom_id": s.bom}),
        422,
        "number_invalid",
        None,
    ),
    (
        "wo_quantity_zero",
        lambda s: (WORK_ORDERS, {"bom_id": s.bom, "quantity": 0}),
        422,
        "number_invalid",
        None,
    ),
    (
        "wo_quantity_over_limit",
        lambda s: (WORK_ORDERS, {"bom_id": s.bom, "quantity": 1_000_000_001}),
        422,
        "number_invalid",
        None,
    ),
    # 工單操作：找不到
    *[
        (f"{verb}_missing", lambda s, v=verb: _wo_path(MISSING, v), 404, "record_missing", None)
        for verb in ("reserve", "start", "complete", "cancel")
    ],
    ("reserve_bad_id", lambda s: _wo_path("not-a-uuid", "reserve"), 404, "record_missing", None),
    # workOrder.reserve
    *[
        (
            f"reserve_{state}",
            lambda s, x=state: _wo_path(getattr(s, x), "reserve"),
            409,
            "production_state",
            None,
        )
        for state in ("reserved", "started", "completed", "cancelled")
    ],
    (
        "reserve_insufficient",
        lambda s: _wo_path(s.planned, "reserve"),
        409,
        "materials_insufficient",
        None,
    ),
    (
        # 數量相乘超過 1e9 的預留量
        "reserve_quantity_overflow",
        lambda s: _wo_path(s.planned, "reserve"),
        422,
        "number_invalid",
        "UPDATE work_order SET quantity = 600000000 WHERE status = 'planned'",
    ),
    # workOrder.start
    *[
        (
            f"start_{state}",
            lambda s, x=state: _wo_path(getattr(s, x), "start"),
            409,
            "production_state",
            None,
        )
        for state in ("planned", "started", "completed", "cancelled")
    ],
    # workOrder.complete
    *[
        (
            f"complete_{state}",
            lambda s, x=state: _wo_path(getattr(s, x), "complete"),
            409,
            "production_state",
            None,
        )
        for state in ("planned", "reserved", "completed", "cancelled")
    ],
    (
        # 材料成本層被清空（on_hand 未變）：完工時耗用不到成本層
        "complete_lots_exhausted",
        lambda s: _wo_path(s.started, "complete"),
        409,
        "stock_invalid",
        "DELETE FROM product_lot"
        " WHERE product_id IN (SELECT id FROM product WHERE sku = 'MAT-001')",
    ),
    # workOrder.cancel
    *[
        (
            f"cancel_{state}",
            lambda s, x=state: _wo_path(getattr(s, x), "cancel"),
            409,
            "production_state",
            None,
        )
        for state in ("completed", "cancelled")
    ],
]


@pytest.mark.parametrize(
    ("name", "make", "status", "code", "sql"), _CASES, ids=[c[0] for c in _CASES]
)
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient,
    db_engine: Engine,
    name: str,
    make: Make,
    status: int,
    code: str,
    sql: str | None,
) -> None:
    scenario = Scenario(api)
    if sql is not None:
        with db_engine.begin() as conn:
            conn.execute(text(sql))
    before = api.snapshot()
    version = api.state()["version"]
    path, body = make(scenario)
    r = api.mutate("POST", path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_rejection_table_covers_every_error_code() -> None:
    """B§3.8 與 B§3.1 會出現在製造命令的每一種錯誤碼，參數化表都至少有一案。"""
    codes = {c[3] for c in _CASES}
    assert codes >= {
        "payload_invalid",
        "simulation_required",
        "protected_field",
        "learning_id_invalid",
        "number_invalid",
        "record_missing",
        "bom_invalid",
        "bom_cycle",
        "production_state",
        "materials_insufficient",
        "stock_invalid",
    }


# --- 一致性檢查：竄改後下一個命令整筆拒絕 ---------------------------------------------


_COMPLETED = "(SELECT id FROM work_order WHERE status = 'completed')"
_PLANNED = "(SELECT id FROM work_order WHERE status = 'planned')"


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("UPDATE bom SET revision = 0", "number_invalid"),
        ("UPDATE bom SET product_id = gen_random_uuid()", "record_missing"),
        ("UPDATE bom_component SET product_id = gen_random_uuid()", "record_missing"),
        ("UPDATE bom_component SET quantity = 0", "number_invalid"),
        ("DELETE FROM bom_component", "bom_invalid"),
        ("UPDATE bom_component SET product_id = (SELECT product_id FROM bom)", "bom_invalid"),
        (
            "INSERT INTO bom_component (workspace_id, bom_id, idx, product_id, quantity)"
            " SELECT workspace_id, bom_id, 1, product_id, 1 FROM bom_component",
            "bom_invalid",
        ),
        (
            # B 的 BOM 以 A 為材料：A→B→A
            "INSERT INTO bom (id, workspace_id, product_id, revision, created_at)"
            " SELECT gen_random_uuid(), workspace_id, (SELECT product_id FROM bom_component),"
            " 1, now() FROM bom;"
            " INSERT INTO bom_component (workspace_id, bom_id, idx, product_id, quantity)"
            " SELECT b.workspace_id, b.id, 0,"
            " (SELECT product_id FROM bom WHERE revision = 1 ORDER BY seq LIMIT 1),"
            " 1 FROM bom b WHERE b.seq = (SELECT max(seq) FROM bom)",
            "bom_cycle",
        ),
        ("UPDATE work_order SET bom_id = gen_random_uuid()", "record_missing"),
        (
            f"UPDATE work_order SET bom_snapshot = jsonb_set(bom_snapshot, '{{revision}}', '2')"
            f" WHERE id = {_PLANNED}",
            "production_invalid",
        ),
        ("UPDATE bom_component SET quantity = 5", "production_invalid"),
        (f"UPDATE work_order SET status = 'bogus' WHERE id = {_PLANNED}", "production_invalid"),
        (
            f"UPDATE work_order SET actual_cost_minor = 1 WHERE id = {_COMPLETED}",
            "production_invalid",
        ),
        (
            f"UPDATE work_order SET actual_cost_minor = NULL WHERE id = {_COMPLETED}",
            "number_invalid",
        ),
        (
            "UPDATE consumed_material_lot SET quantity = 1, cost_minor = 1000",
            "production_invalid",
        ),
        ("UPDATE consumed_material_lot SET product_id = gen_random_uuid()", "record_missing"),
        ("UPDATE consumed_material_lot SET quantity = 0", "number_invalid"),
        (f"UPDATE work_order SET quantity = 0 WHERE id = {_PLANNED}", "number_invalid"),
        (
            f"UPDATE work_order SET learning_run_id = 'bad id!' WHERE id = {_PLANNED}",
            "learning_id_invalid",
        ),
        # 已預留的工單改回 planned：預留量對不上
        (
            "UPDATE work_order SET status = 'planned' WHERE status = 'reserved'",
            "reservation_invalid",
        ),
    ],
)
def test_tampered_manufacturing_rejected(
    api: ApiClient, db_engine: Engine, sql: str, code: str
) -> None:
    Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(text(sql))
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", "/api/v1/crm/customers", {"name": "x"})
    assert r.json()["error"]["code"] == code, r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


@pytest.mark.parametrize("table", ["bom", "work_order"])
def test_manufacturing_record_limit(api: ApiClient, db_engine: Engine, table: str) -> None:
    api.setup("manufacturing")
    ws = api.snapshot()
    bom = ws["boms"][0]
    with db_engine.begin() as conn:
        if table == "bom":
            conn.execute(
                text(
                    "INSERT INTO bom (id, workspace_id, product_id, revision, created_at)"
                    " SELECT gen_random_uuid(), w.id, :product, 1, now()"
                    " FROM workspace w, generate_series(1, 500)"
                ),
                {"product": bom["product_id"]},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO work_order (id, workspace_id, bom_id, bom_snapshot, quantity,"
                    " status, created_at, updated_at)"
                    " SELECT gen_random_uuid(), w.id, b.id, '{}'::jsonb, 1, 'planned', now(), now()"
                    " FROM workspace w, bom b, generate_series(1, 501)"
                )
            )
    r = api.mutate("POST", "/api/v1/crm/customers", {"name": "x"})
    assert _error(r) == (422, "record_limit")


# --- 快照還原與清除 ---------------------------------------------------------------


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    s = Scenario(api)
    api.ok("POST", WORK_ORDERS, {"bom_id": s.bom, "quantity": 1, "learning_run_id": "run-abcdef01"})
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = MANUFACTURING_SPEC.snapshot(db, ctx.workspace_id)
        assert len(before["boms"]) == 1
        assert len(before["work_orders"]) == 6
        assert any(o["consumed_material_lots"] for o in before["work_orders"])
        assert any(o["learning_run_id"] for o in before["work_orders"])
        db.execute(text("DELETE FROM work_order"))
        db.execute(text("DELETE FROM bom"))
        empty = MANUFACTURING_SPEC.snapshot(db, ctx.workspace_id)
        assert empty == {"boms": [], "work_orders": []}
        MANUFACTURING_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert MANUFACTURING_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()


def test_clear_cascades_manufacturing(api: ApiClient, db_engine: Engine) -> None:
    Scenario(api)
    api.ok("POST", "/api/v1/workspace/clear", {})
    with db_engine.connect() as conn:
        for table in ("bom", "bom_component", "work_order", "consumed_material_lot"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
