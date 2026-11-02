"""銷售訂單：建立即預留、分次付款、分批出貨（FIFO 成本批次）、部分退貨回補到佇列尾端、
取消退款，以及訂單、預留與庫存價值守恆的一致性檢查。"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.modules.inventory import service as inventory
from src.modules.sales import service as sales
from src.modules.sales.router import SPEC as SALES_SPEC
from tests.helpers import (
    ORDERS,
    PRICE,
    ApiClient,
    buyer_wallet,
    create_order,
    fund,
    line_ids,
    ship_body,
    stocked_product,
    workspace_ctx,
)

PRODUCTS = "/api/v1/inventory/products"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _wallet_by_id(ws: dict[str, Any], wallet_id: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["id"] == wallet_id)


def _product(ws: dict[str, Any], product_id: str) -> dict[str, Any]:
    return next(p for p in ws["products"] if p["id"] == product_id)


def _order(ws: dict[str, Any], order_id: str) -> dict[str, Any]:
    return next(o for o in ws["orders"] if o["id"] == order_id)


def _lots(p: dict[str, Any]) -> list[tuple[int, int]]:
    return [(lot["quantity"], lot["cost_minor"]) for lot in p["lots"]]


# --- 主流程 -----------------------------------------------------------------------


def test_create_reserves_and_snapshots_line(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    buyer = buyer_wallet(api)
    oid = create_order(api, buyer, [(pid, 3)], learning_run_id="run-abcdef01")
    ws = api.snapshot()
    assert _product(ws, pid)["reserved"] == 3
    order = _order(ws, oid)
    assert {
        k: order[k]
        for k in (
            "buyer_wallet_id",
            "status",
            "total_minor",
            "paid_minor",
            "refunded_minor",
            "learning_run_id",
        )
    } == {
        "buyer_wallet_id": buyer,
        "status": "pending",
        "total_minor": 3 * PRICE,
        "paid_minor": 0,
        "refunded_minor": 0,
        "learning_run_id": "run-abcdef01",
    }
    [line] = order["lines"]
    assert {k: v for k, v in line.items() if k != "id"} == {
        "product_id": pid,
        "name": "測試商品",
        "price_minor": PRICE,
        "cost_minor": 100,
        "quantity": 3,
        "shipped_quantity": 0,
        "returned_quantity": 0,
        "shipped_cost_lots": [],
    }
    # 下單後改價不影響訂單快照
    api.ok("PATCH", f"{PRODUCTS}/{pid}", {"price_minor": 1})
    assert _order(api.snapshot(), oid)["lines"][0]["price_minor"] == PRICE
    assert api.snapshot()["history"][-2]["action"] == "order.create"


def test_full_flow_fifo_cost(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(2, 100), (2, 200)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 3 * PRICE)
    oid = create_order(api, buyer, [(pid, 3)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 3 * PRICE})
    [lid] = line_ids(api, oid)
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 3)]))
    ws = api.snapshot()
    order = _order(ws, oid)
    assert order["status"] == "shipped"
    [line] = order["lines"]
    assert [(x["quantity"], x["cost_minor"]) for x in line["shipped_cost_lots"]] == [
        (2, 100),
        (1, 200),
    ]
    assert all(x["returned"] == 0 for x in line["shipped_cost_lots"])
    assert line["shipped_quantity"] == 3
    p = _product(ws, pid)
    assert (p["on_hand"], p["reserved"], p["stock_value_minor"], _lots(p)) == (
        1,
        0,
        200,
        [(1, 200)],
    )
    # COGS（Task 15 報表）= 2*100 + 1*200 = 400
    assert sum(x["quantity"] * x["cost_minor"] for x in line["shipped_cost_lots"]) == 400
    assert _wallet_by_id(ws, buyer)["balance_minor"] == 0
    pay = [entry for entry in ws["ledger"] if entry["kind"] == "order.pay"]
    assert [entry["reference_id"] for entry in pay] == [oid]
    assert pay[0]["entries"] == [
        {"wallet_id": buyer, "amount_minor": -3 * PRICE},
        {"wallet_id": _wallet(ws, "business")["id"], "amount_minor": 3 * PRICE},
    ]


def test_partial_pay_status(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 10_000)
    oid = create_order(api, buyer, [(pid, 2)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 500})
    order = _order(api.snapshot(), oid)
    assert (order["status"], order["paid_minor"]) == ("partially_paid", 500)
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 2 * PRICE - 500})
    order = _order(api.snapshot(), oid)
    assert (order["status"], order["paid_minor"]) == ("paid", 2 * PRICE)


def test_ship_requires_full_payment_409_simulation_payment_required(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 10_000)
    oid = create_order(api, buyer, [(pid, 2)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 1})
    [lid] = line_ids(api, oid)
    before = api.snapshot()
    r = api.mutate("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 1)]))
    assert _error(r) == (409, "simulation_payment_required")
    assert api.snapshot() == before


def test_partial_ship_then_rest(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 3 * PRICE)
    oid = create_order(api, buyer, [(pid, 3)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 3 * PRICE})
    [lid] = line_ids(api, oid)
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 1)]))
    ws = api.snapshot()
    assert _order(ws, oid)["status"] == "partially_shipped"
    assert _product(ws, pid)["reserved"] == 2
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 2)]))
    ws = api.snapshot()
    assert _order(ws, oid)["status"] == "shipped"
    assert [
        (x["quantity"], x["cost_minor"]) for x in _order(ws, oid)["lines"][0]["shipped_cost_lots"]
    ] == [(1, 100), (2, 100)]


def test_return_restocks_to_queue_tail(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(2, 100), (2, 200)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 3 * PRICE)
    oid = create_order(api, buyer, [(pid, 3)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 3 * PRICE})
    [lid] = line_ids(api, oid)
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 3)]))
    api.ok("POST", f"{ORDERS}/{oid}/return", ship_body([(lid, 1)]))
    ws = api.snapshot()
    p = _product(ws, pid)
    assert _lots(p) == [(1, 200), (1, 100)]
    assert (p["on_hand"], p["stock_value_minor"], p["reserved"]) == (2, 300, 0)
    order = _order(ws, oid)
    assert (order["status"], order["refunded_minor"]) == ("partially_returned", PRICE)
    [line] = order["lines"]
    assert line["returned_quantity"] == 1
    assert [(x["quantity"], x["cost_minor"], x["returned"]) for x in line["shipped_cost_lots"]] == [
        (2, 100, 1),
        (1, 200, 0),
    ]
    assert _wallet_by_id(ws, buyer)["balance_minor"] == PRICE
    refund = ws["ledger"][-1]
    assert (refund["kind"], refund["reference_id"]) == ("order.return", oid)
    # 全部退完：status returned，退回的成本層依序接在尾端
    api.ok("POST", f"{ORDERS}/{oid}/return", ship_body([(lid, 2)]))
    ws = api.snapshot()
    assert _order(ws, oid)["status"] == "returned"
    assert _order(ws, oid)["refunded_minor"] == 3 * PRICE
    assert _lots(_product(ws, pid)) == [(1, 200), (1, 100), (1, 100), (1, 200)]


def test_ship_after_partial_return_allowed(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(4, 100)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 3 * PRICE)
    oid = create_order(api, buyer, [(pid, 3)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 3 * PRICE})
    [lid] = line_ids(api, oid)
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 2)]))
    api.ok("POST", f"{ORDERS}/{oid}/return", ship_body([(lid, 1)]))
    api.ok("POST", f"{ORDERS}/{oid}/ship", ship_body([(lid, 1)]))
    order = _order(api.snapshot(), oid)
    assert order["status"] == "shipped"
    assert (order["lines"][0]["shipped_quantity"], order["lines"][0]["returned_quantity"]) == (3, 1)


def test_cancel_refunds_and_releases(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    buyer = buyer_wallet(api)
    fund(api, buyer, 10_000)
    oid = create_order(api, buyer, [(pid, 2)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 700})
    api.ok("POST", f"{ORDERS}/{oid}/cancel", {})
    ws = api.snapshot()
    order = _order(ws, oid)
    assert (order["status"], order["paid_minor"], order["refunded_minor"]) == (
        "cancelled",
        700,
        700,
    )
    assert _product(ws, pid)["reserved"] == 0
    assert _wallet_by_id(ws, buyer)["balance_minor"] == 10_000
    cancel = ws["ledger"][-1]
    assert (cancel["kind"], cancel["reference_id"]) == ("order.cancel", oid)


def test_cancel_unpaid_writes_zero_ledger(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(5, 100)])
    oid = create_order(api, buyer_wallet(api), [(pid, 2)])
    api.ok("POST", f"{ORDERS}/{oid}/cancel", {})
    ws = api.snapshot()
    cancel = ws["ledger"][-1]
    assert (cancel["kind"], [e["amount_minor"] for e in cancel["entries"]]) == (
        "order.cancel",
        [0, 0],
    )
    assert _product(ws, pid)["reserved"] == 0


def test_out_of_stock_409(api: ApiClient) -> None:
    api.setup()
    pid = stocked_product(api, [(3, 100)])
    buyer = buyer_wallet(api)
    create_order(api, buyer, [(pid, 2)])
    before = api.snapshot()
    r = api.mutate(
        "POST", ORDERS, {"buyer_wallet_id": buyer, "lines": [{"product_id": pid, "quantity": 2}]}
    )
    assert _error(r) == (409, "simulation_out_of_stock")
    assert api.snapshot() == before


def test_sales_module_disabled(api: ApiClient) -> None:
    api.setup("retail", modules=["inventory", "wallets"])
    before = api.snapshot()
    r = api.mutate("POST", ORDERS, {"buyer_wallet_id": buyer_wallet(api), "lines": []})
    assert _error(r) == (403, "module_disabled")
    assert api.snapshot() == before


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


class Scenario:
    """每個錯誤案例的共用世界：商品 P（庫存 5、成本 100），A 未付款、B 已付清並出貨 2 件、
    C 已取消；另有停用商品 Q（庫存 1）。"""

    def __init__(self, api: ApiClient) -> None:
        api.setup()
        self.pid = stocked_product(api, [(5, 100)])
        ws = api.snapshot()
        business = _wallet(ws, "business")["id"]
        self.business = business
        self.buyer = _wallet(ws, "buyer")["id"]
        fund(api, self.buyer, 4 * PRICE)
        self.qid = api.ok(
            "POST",
            PRODUCTS,
            {"name": "停用商品", "sku": "Q-1", "price_minor": 10, "cost_minor": 0},
        )["result"]
        api.ok("POST", f"{PRODUCTS}/{self.qid}/receive", {"quantity": 1})
        api.ok("PATCH", f"{PRODUCTS}/{self.qid}", {"active": False})
        self.a = create_order(api, self.buyer, [(self.pid, 1)])
        self.b = create_order(api, self.buyer, [(self.pid, 2)])
        api.ok("POST", f"{ORDERS}/{self.b}/pay", {"amount_minor": 2 * PRICE})
        [self.b_line] = line_ids(api, self.b)
        api.ok("POST", f"{ORDERS}/{self.b}/ship", ship_body([(self.b_line, 1)]))
        self.c = create_order(api, self.buyer, [(self.pid, 1)])
        api.ok("POST", f"{ORDERS}/{self.c}/cancel", {})
        [self.a_line] = line_ids(api, self.a)
        [self.c_line] = line_ids(api, self.c)


def _create(s: Scenario, **overrides: Any) -> tuple[str, dict[str, Any]]:
    body = {"buyer_wallet_id": s.buyer, "lines": [{"product_id": s.pid, "quantity": 1}]}
    return ORDERS, {**body, **overrides}


def _act(order: str, action: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return f"{ORDERS}/{order}/{action}", body


Make = Callable[[Scenario], tuple[str, dict[str, Any]]]
# (名稱, 竄改 SQL 或 None, 產生請求, status, code)
Case = tuple[str, str | None, Make, int, str]

_CASES: list[Case] = [
    # order.create
    (
        "create_buyer_business",
        None,
        lambda s: _create(s, buyer_wallet_id=s.business),
        422,
        "simulation_buyer_required",
    ),
    (
        "create_buyer_missing",
        None,
        lambda s: _create(s, buyer_wallet_id=str(uuid.uuid4())),
        404,
        "simulation_record_missing",
    ),
    (
        "create_duplicate",
        None,
        lambda s: _create(s, lines=[{"product_id": s.pid, "quantity": 1}] * 2),
        422,
        "simulation_duplicate_line",
    ),
    (
        "create_product_missing",
        None,
        lambda s: _create(s, lines=[{"product_id": str(uuid.uuid4()), "quantity": 1}]),
        404,
        "simulation_record_missing",
    ),
    (
        "create_inactive",
        None,
        lambda s: _create(s, lines=[{"product_id": s.qid, "quantity": 1}]),
        409,
        "simulation_product_inactive",
    ),
    (
        "create_out_of_stock",
        None,
        lambda s: _create(s, lines=[{"product_id": s.pid, "quantity": 3}]),
        409,
        "simulation_out_of_stock",
    ),
    ("create_lines_empty", None, lambda s: _create(s, lines=[]), 422, "lines_invalid"),
    (
        "create_lines_missing",
        None,
        lambda s: (ORDERS, {"buyer_wallet_id": s.buyer}),
        422,
        "lines_invalid",
    ),
    (
        "create_lines_many",
        None,
        lambda s: _create(s, lines=[{"product_id": s.pid, "quantity": 1}] * 51),
        422,
        "lines_invalid",
    ),
    (
        "create_quantity_zero",
        None,
        lambda s: _create(s, lines=[{"product_id": s.pid, "quantity": 0}]),
        422,
        "number_invalid",
    ),
    (
        "create_learning_bad",
        None,
        lambda s: _create(s, learning_run_id="短"),
        422,
        "learning_id_invalid",
    ),
    ("create_bank", None, lambda s: _create(s, bank="x"), 422, "simulation_required"),
    ("create_reserved", None, lambda s: _create(s, reserved=1), 422, "protected_field"),
    # 其他 order.*：訂單不存在、已取消
    (
        "pay_missing",
        None,
        lambda s: _act(str(uuid.uuid4()), "pay", {"amount_minor": 1}),
        404,
        "simulation_record_missing",
    ),
    (
        "pay_not_uuid",
        None,
        lambda s: _act("nope", "pay", {"amount_minor": 1}),
        404,
        "simulation_record_missing",
    ),
    (
        "pay_cancelled",
        None,
        lambda s: _act(s.c, "pay", {"amount_minor": 1}),
        409,
        "simulation_order_cancelled",
    ),
    (
        "ship_cancelled",
        None,
        lambda s: _act(s.c, "ship", ship_body([(s.c_line, 1)])),
        409,
        "simulation_order_cancelled",
    ),
    (
        "return_cancelled",
        None,
        lambda s: _act(s.c, "return", ship_body([(s.c_line, 1)])),
        409,
        "simulation_order_cancelled",
    ),
    (
        "cancel_cancelled",
        None,
        lambda s: _act(s.c, "cancel", {}),
        409,
        "simulation_order_cancelled",
    ),
    # order.pay
    (
        "pay_shipped",
        None,
        lambda s: _act(s.b, "pay", {"amount_minor": 1}),
        409,
        "simulation_order_shipped",
    ),
    (
        "pay_overpayment",
        None,
        lambda s: _act(s.a, "pay", {"amount_minor": PRICE + 1}),
        409,
        "simulation_overpayment",
    ),
    (
        "pay_insufficient",
        "UPDATE wallet SET balance_minor = 0 WHERE kind = 'buyer'",
        lambda s: _act(s.a, "pay", {"amount_minor": 1}),
        409,
        "simulation_insufficient_funds",
    ),
    ("pay_zero", None, lambda s: _act(s.a, "pay", {"amount_minor": 0}), 422, "number_invalid"),
    ("pay_no_amount", None, lambda s: _act(s.a, "pay", {}), 422, "number_invalid"),
    # order.cancel
    ("cancel_shipped", None, lambda s: _act(s.b, "cancel", {}), 409, "simulation_order_shipped"),
    # order.ship
    (
        "ship_unpaid",
        None,
        lambda s: _act(s.a, "ship", ship_body([(s.a_line, 1)])),
        409,
        "simulation_payment_required",
    ),
    (
        "ship_duplicate",
        None,
        lambda s: _act(s.b, "ship", ship_body([(s.b_line, 1), (s.b_line, 1)])),
        422,
        "simulation_duplicate_line",
    ),
    (
        "ship_line_missing",
        None,
        lambda s: _act(s.b, "ship", ship_body([(str(uuid.uuid4()), 1)])),
        404,
        "simulation_record_missing",
    ),
    (
        "ship_other_order_line",
        None,
        lambda s: _act(s.b, "ship", ship_body([(s.a_line, 1)])),
        404,
        "simulation_record_missing",
    ),
    (
        "ship_overship",
        None,
        lambda s: _act(s.b, "ship", ship_body([(s.b_line, 2)])),
        409,
        "simulation_overship",
    ),
    ("ship_lines_missing", None, lambda s: _act(s.b, "ship", {}), 422, "lines_invalid"),
    (
        "ship_quantity_zero",
        None,
        lambda s: _act(s.b, "ship", ship_body([(s.b_line, 0)])),
        422,
        "number_invalid",
    ),
    (
        "ship_out_of_stock",
        "UPDATE product SET reserved = 0 WHERE sku = 'T-001'",
        lambda s: _act(s.b, "ship", ship_body([(s.b_line, 1)])),
        409,
        "simulation_out_of_stock",
    ),
    (
        "ship_lots_corrupt",
        "DELETE FROM product_lot",
        lambda s: _act(s.b, "ship", ship_body([(s.b_line, 1)])),
        409,
        "simulation_inventory_corrupt",
    ),
    # order.return
    (
        "return_overreturn",
        None,
        lambda s: _act(s.b, "return", ship_body([(s.b_line, 2)])),
        409,
        "simulation_overreturn",
    ),
    (
        "return_unshipped",
        None,
        lambda s: _act(s.a, "return", ship_body([(s.a_line, 1)])),
        409,
        "simulation_overreturn",
    ),
    (
        "return_duplicate",
        None,
        lambda s: _act(s.b, "return", ship_body([(s.b_line, 1), (s.b_line, 1)])),
        422,
        "simulation_duplicate_line",
    ),
    (
        "return_line_missing",
        None,
        lambda s: _act(s.b, "return", ship_body([(str(uuid.uuid4()), 1)])),
        404,
        "simulation_record_missing",
    ),
    (
        "return_overrefund",
        "UPDATE sales_order SET refunded_minor = paid_minor WHERE status = 'partially_shipped'",
        lambda s: _act(s.b, "return", ship_body([(s.b_line, 1)])),
        409,
        "simulation_overrefund",
    ),
    (
        "return_lots_corrupt",
        "UPDATE shipped_cost_lot SET returned = quantity",
        lambda s: _act(s.b, "return", ship_body([(s.b_line, 1)])),
        409,
        "simulation_inventory_corrupt",
    ),
    (
        "return_business_insufficient",
        "UPDATE wallet SET balance_minor = 0 WHERE kind = 'business'",
        lambda s: _act(s.b, "return", ship_body([(s.b_line, 1)])),
        409,
        "simulation_insufficient_funds",
    ),
]


@pytest.mark.parametrize(
    ("name", "tamper", "make", "status", "code"), _CASES, ids=[c[0] for c in _CASES]
)
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient,
    db_engine: Engine,
    name: str,
    tamper: str | None,
    make: Make,
    status: int,
    code: str,
) -> None:
    scenario = Scenario(api)
    if tamper is not None:
        with db_engine.begin() as conn:
            conn.execute(text(tamper))
    before = api.snapshot()
    version = api.state()["version"]
    path, body = make(scenario)
    r = api.mutate("POST", path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


# --- 一致性檢查：竄改後下一個命令整筆拒絕 ---------------------------------------------


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("UPDATE product SET reserved = reserved - 1 WHERE sku = 'T-001'", "reservation_invalid"),
        (
            "UPDATE sales_order SET paid_minor = paid_minor + 1 WHERE status = 'pending'",
            "order_invalid",
        ),
        ("UPDATE sales_order SET status = 'paid' WHERE status = 'pending'", "order_invalid"),
        ("UPDATE sales_order SET status = 'bogus' WHERE status = 'pending'", "order_invalid"),
        (
            "UPDATE sales_order SET total_minor = total_minor + 1 WHERE status = 'pending'",
            "order_invalid",
        ),
        (
            "UPDATE sales_order SET refunded_minor = 1 WHERE status = 'partially_shipped'",
            "order_invalid",
        ),
        (
            "UPDATE order_line SET shipped_quantity = shipped_quantity + 1 "
            "WHERE shipped_quantity = 1",
            "order_invalid",
        ),
        ("UPDATE shipped_cost_lot SET returned = 1", "order_invalid"),
        (
            "UPDATE sales_order SET learning_run_id = 'x' WHERE status = 'pending'",
            "learning_id_invalid",
        ),
        ("UPDATE shipped_cost_lot SET cost_minor = cost_minor + 1", "stock_value_conservation"),
        (
            "UPDATE sales_order SET status = 'pending', paid_minor = 0 WHERE status = 'cancelled'",
            "reservation_invalid",
        ),
        (
            "UPDATE ledger SET reference_id = gen_random_uuid() WHERE kind = 'order.pay'",
            "record_missing",
        ),
        (
            "UPDATE ledger_entry SET wallet_id = (SELECT id FROM wallet WHERE kind = 'supplier') "
            "WHERE idx = 0 AND ledger_id IN (SELECT id FROM ledger WHERE kind = 'order.pay')",
            "ledger_invalid",
        ),
    ],
)
def test_tampered_orders_rejected(api: ApiClient, db_engine: Engine, sql: str, code: str) -> None:
    Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(text(sql))
    before = api.snapshot()
    r = api.mutate("POST", PRODUCTS, {"name": "x", "sku": "x", "price_minor": 1, "cost_minor": 1})
    assert r.json()["error"]["code"] == code, r.text
    assert api.snapshot() == before


def test_order_record_limit(api: ApiClient, db_engine: Engine) -> None:
    s = Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sales_order (id, workspace_id, buyer_wallet_id, status, total_minor,"
                " paid_minor, refunded_minor, created_at, updated_at)"
                " SELECT gen_random_uuid(), w.id, :buyer, 'pending', 0, 0, 0, now(), now()"
                " FROM workspace w, generate_series(1, 497)"
            ),
            {"buyer": s.buyer},
        )
    before = api.snapshot()
    r = api.mutate("POST", *_create(s))
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before


# --- service、快照 ------------------------------------------------------------------


def test_order_reserved_demand_registered(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    s = Scenario(api)
    assert sales.order_reserved_demand in inventory._RESERVED_DEMANDS
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        # A 1 件未出貨、B 2 件出了 1 件、C 已取消
        assert sales.order_reserved_demand(db, ctx.workspace_id) == {s.pid: 2}


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    s = Scenario(api)
    api.ok("POST", f"{ORDERS}/{s.b}/return", ship_body([(s.b_line, 1)]))
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = SALES_SPEC.snapshot(db, ctx.workspace_id)
        assert len(before["orders"]) == 3
        db.execute(text("DELETE FROM sales_order"))
        assert SALES_SPEC.snapshot(db, ctx.workspace_id) == {"orders": []}
        SALES_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert SALES_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()


def test_clear_cascades_orders(api: ApiClient, db_engine: Engine) -> None:
    Scenario(api)
    api.ok("POST", "/api/v1/workspace/clear", {})
    with db_engine.connect() as conn:
        for table in ("sales_order", "order_line", "shipped_cost_lot"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
