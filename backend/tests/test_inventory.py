"""商品與 FIFO 採購入庫：建立、更新、入庫、成本層、預留、庫存檢查與快照還原。"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.core.problem import Problem
from src.modules.catalog.templates import TEMPLATES
from src.modules.inventory import service as inventory
from src.modules.inventory.router import SPEC as INVENTORY_SPEC
from src.platform.context import CommandContext
from tests.helpers import ApiClient, workspace_ctx

PRODUCTS = "/api/v1/inventory/products"
NEW_PRODUCT = {"name": "測試商品", "sku": "T-001", "price_minor": 900, "cost_minor": 500}


def _product_path(product_id: str) -> str:
    return f"{PRODUCTS}/{product_id}"


def _receive_path(product_id: str) -> str:
    return f"{PRODUCTS}/{product_id}/receive"


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _product(ws: dict[str, Any], product_id: str) -> dict[str, Any]:
    return next(p for p in ws["products"] if p["id"] == product_id)


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _fund_business(api: ApiClient, amount: int) -> None:
    business = _wallet(api.snapshot(), "business")["id"]
    api.ok("POST", f"/api/v1/wallets/{business}/fund", {"amount_minor": amount})


def _create(api: ApiClient, **overrides: Any) -> str:
    return api.ok("POST", PRODUCTS, {**NEW_PRODUCT, **overrides})["result"]


# --- seed -----------------------------------------------------------------------


@pytest.mark.parametrize("industry", ["retail", "service", "general"])
def test_seed_products(api: ApiClient, industry: str) -> None:
    api.setup(industry)
    sample = TEMPLATES[industry].sample
    ws = api.snapshot()
    got = [
        (
            p["sku"],
            p["name"],
            p["price_minor"],
            p["cost_minor"],
            p["active"],
            p["on_hand"],
            p["lots"],
        )
        for p in ws["products"]
    ]
    assert got == [
        (sample.sku, sample.product, sample.price_minor, sample.cost_minor, True, 0, []),
        ("MAT-001", sample.component, 1000, 500, True, 0, []),
    ]
    assert ws["purchases"] == []


# --- product.create / product.update -------------------------------------------


def test_product_create(api: ApiClient) -> None:
    api.setup()
    pid = _create(api, active=False)
    p = _product(api.snapshot(), pid)
    assert {k: p[k] for k in ("name", "sku", "price_minor", "cost_minor")} == NEW_PRODUCT
    assert p["active"] is True  # 建立時一律啟用
    assert (p["on_hand"], p["reserved"], p["stock_value_minor"], p["lots"]) == (0, 0, 0, [])
    assert api.snapshot()["history"][-1] == {
        **api.snapshot()["history"][-1],
        "action": "product.create",
        "result": pid,
    }


def test_product_create_forces_stock_zero(api: ApiClient) -> None:
    api.setup()
    r = api.mutate("POST", PRODUCTS, {**NEW_PRODUCT, "on_hand": 5})
    assert _error(r) == (422, "protected_field")


def test_forbidden_key_simulation_required(api: ApiClient) -> None:
    api.setup()
    r = api.mutate("POST", PRODUCTS, {**NEW_PRODUCT, "bank_account": "012-345"})
    assert _error(r) == (422, "simulation_required")


def test_payload_id_cannot_override(api: ApiClient) -> None:
    api.setup()
    forced = str(uuid.uuid4())
    pid = _create(api, id=forced)
    assert pid != forced
    ids = [p["id"] for p in api.snapshot()["products"]]
    assert pid in ids and forced not in ids


def test_product_update(api: ApiClient) -> None:
    api.setup()
    pid = _create(api)
    api.ok("PATCH", _product_path(pid), {"name": "改名", "price_minor": 1200, "active": False})
    p = _product(api.snapshot(), pid)
    assert (p["name"], p["sku"], p["price_minor"], p["cost_minor"], p["active"]) == (
        "改名",
        "T-001",
        1200,
        500,
        False,
    )


def test_cost_change_only_affects_future_receipts(api: ApiClient) -> None:
    api.setup()
    _fund_business(api, 10_000)
    pid = _create(api)
    api.ok("POST", _receive_path(pid), {"quantity": 2})
    api.ok("PATCH", _product_path(pid), {"cost_minor": 700})
    api.ok("POST", _receive_path(pid), {"quantity": 1})
    p = _product(api.snapshot(), pid)
    assert p["lots"] == [{"quantity": 2, "cost_minor": 500}, {"quantity": 1, "cost_minor": 700}]
    assert (p["on_hand"], p["stock_value_minor"]) == (3, 1700)


# --- inventory.receive ----------------------------------------------------------


def test_receive_creates_lot_and_purchase(api: ApiClient) -> None:
    api.setup()
    _fund_business(api, 10_000)
    pid = _create(api)
    body = api.ok("POST", _receive_path(pid), {"quantity": 3})
    ws = api.snapshot()
    p = _product(ws, pid)
    assert (p["on_hand"], p["stock_value_minor"]) == (3, 1500)
    assert p["lots"] == [{"quantity": 3, "cost_minor": 500}]
    assert _wallet(ws, "business")["balance_minor"] == 10_000 - 1500
    assert _wallet(ws, "supplier")["balance_minor"] == 1500
    [purchase] = ws["purchases"]
    assert purchase["id"] == body["result"]
    assert {
        k: purchase[k] for k in ("product_id", "name", "quantity", "cost_minor", "total_minor")
    } == {
        "product_id": pid,
        "name": "測試商品",
        "quantity": 3,
        "cost_minor": 500,
        "total_minor": 1500,
    }
    receive = ws["ledger"][-1]
    assert receive["kind"] == "inventory.receive"
    assert receive["reference_id"] == purchase["id"]
    assert receive["entries"] == [
        {"wallet_id": _wallet(ws, "business")["id"], "amount_minor": -1500},
        {"wallet_id": _wallet(ws, "supplier")["id"], "amount_minor": 1500},
    ]


def test_receive_zero_cost_allowed(api: ApiClient) -> None:
    api.setup()
    pid = _create(api, cost_minor=0)
    api.ok("POST", _receive_path(pid), {"quantity": 4})
    p = _product(api.snapshot(), pid)
    assert (p["on_hand"], p["stock_value_minor"], p["lots"]) == (
        4,
        0,
        [{"quantity": 4, "cost_minor": 0}],
    )


def test_receive_insufficient_funds_409(api: ApiClient) -> None:
    api.setup()
    _fund_business(api, 1499)
    pid = _create(api)
    before = api.snapshot()
    r = api.mutate("POST", _receive_path(pid), {"quantity": 3})
    assert _error(r) == (409, "simulation_insufficient_funds")
    assert api.snapshot() == before


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


def _seed_product(ws: dict[str, Any]) -> str:
    return ws["products"][0]["id"]


Case = tuple[str, str, Callable[[dict[str, Any]], tuple[str, dict[str, Any]]], int, str]

_CASES: list[Case] = [
    (
        "create_no_name",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "name": ""}),
        422,
        "product_invalid",
    ),
    (
        "create_name_missing",
        "POST",
        lambda ws: (PRODUCTS, {"sku": "x", "price_minor": 1, "cost_minor": 1}),
        422,
        "product_invalid",
    ),
    (
        "create_name_long",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "name": "長" * 101}),
        422,
        "product_invalid",
    ),
    (
        "create_sku_number",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "sku": 1}),
        422,
        "product_invalid",
    ),
    (
        "create_extra_key",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "color": "red"}),
        422,
        "product_invalid",
    ),
    (
        "create_price_negative",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "price_minor": -1}),
        422,
        "number_invalid",
    ),
    (
        "create_cost_fraction",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "cost_minor": 0.5}),
        422,
        "number_invalid",
    ),
    (
        "create_price_missing",
        "POST",
        lambda ws: (PRODUCTS, {"name": "x", "sku": "x", "cost_minor": 1}),
        422,
        "number_invalid",
    ),
    (
        "create_cost_missing",
        "POST",
        lambda ws: (PRODUCTS, {"name": "x", "sku": "x", "price_minor": 1}),
        422,
        "number_invalid",
    ),
    (
        "create_on_hand",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "on_hand": 1}),
        422,
        "protected_field",
    ),
    (
        "create_lots",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "lots": []}),
        422,
        "protected_field",
    ),
    (
        "create_stock_value",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "stock_value_minor": 1}),
        422,
        "protected_field",
    ),
    (
        "create_bank",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "BankCode": "1"}),
        422,
        "simulation_required",
    ),
    (
        "create_payment_url",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "payment_url": "x"}),
        422,
        "simulation_required",
    ),
    (
        "create_learning",
        "POST",
        lambda ws: (PRODUCTS, {**NEW_PRODUCT, "learning_run_id": "abcdefgh"}),
        422,
        "learning_id_invalid",
    ),
    (
        "update_missing",
        "PATCH",
        lambda ws: (_product_path(str(uuid.uuid4())), {"name": "x"}),
        404,
        "simulation_record_missing",
    ),
    (
        "update_not_uuid",
        "PATCH",
        lambda ws: (_product_path("nope"), {"name": "x"}),
        404,
        "simulation_record_missing",
    ),
    (
        "update_empty_name",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"name": ""}),
        422,
        "product_invalid",
    ),
    (
        "update_sku_null",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"sku": None}),
        422,
        "product_invalid",
    ),
    (
        "update_active_str",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"active": "yes"}),
        422,
        "product_invalid",
    ),
    (
        "update_extra_key",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"on_sale": True}),
        422,
        "product_invalid",
    ),
    (
        "update_price_null",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"price_minor": None}),
        422,
        "number_invalid",
    ),
    (
        "update_reserved",
        "PATCH",
        lambda ws: (_product_path(_seed_product(ws)), {"reserved": 0}),
        422,
        "protected_field",
    ),
    (
        "receive_insufficient",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {"quantity": 1}),
        409,
        "simulation_insufficient_funds",
    ),
    (
        "receive_missing",
        "POST",
        lambda ws: (_receive_path(str(uuid.uuid4())), {"quantity": 1}),
        404,
        "simulation_record_missing",
    ),
    (
        "receive_zero",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {"quantity": 0}),
        422,
        "number_invalid",
    ),
    (
        "receive_no_quantity",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {}),
        422,
        "number_invalid",
    ),
    (
        "receive_quantity_big",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {"quantity": 10**9 + 1}),
        422,
        "number_invalid",
    ),
    (
        "receive_lines",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {"quantity": 1, "lines": [{"quantity": 0}]}),
        422,
        "number_invalid",
    ),
    (
        "receive_lines_many",
        "POST",
        lambda ws: (
            _receive_path(_seed_product(ws)),
            {"quantity": 1, "lines": [{"quantity": 1}] * 51},
        ),
        422,
        "lines_invalid",
    ),
    (
        "receive_legal",
        "POST",
        lambda ws: (_receive_path(_seed_product(ws)), {"quantity": 1, "legal_name": "x"}),
        422,
        "simulation_required",
    ),
]


@pytest.mark.parametrize(
    ("name", "method", "make", "status", "code"), _CASES, ids=[c[0] for c in _CASES]
)
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient, name: str, method: str, make: Callable, status: int, code: str
) -> None:
    api.setup()
    before = api.snapshot()
    version = api.state()["version"]
    path, body = make(before)
    r = api.mutate(method, path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_receive_overflow_rejected(api: ApiClient) -> None:
    api.setup()
    pid = _create(api, cost_minor=1_000_000_000)
    before = api.snapshot()
    r = api.mutate("POST", _receive_path(pid), {"quantity": 1_000_000_000})
    assert _error(r) == (422, "simulation_amount_overflow")
    assert api.snapshot() == before


def test_stock_value_over_limit_rejected(api: ApiClient) -> None:
    api.setup()
    _fund_business(api, 1_000_000_000)
    _fund_business(api, 1_000_000_000)
    pid = _create(api, cost_minor=1_000_000_000)
    before = api.snapshot()
    r = api.mutate("POST", _receive_path(pid), {"quantity": 2})
    assert _error(r) == (422, "number_invalid")
    assert api.snapshot() == before


def test_inventory_module_disabled(api: ApiClient) -> None:
    api.setup("service")  # services, wallets, crm, projects：沒有 inventory
    before = api.snapshot()
    r = api.mutate("POST", PRODUCTS, NEW_PRODUCT)
    assert _error(r) == (403, "module_disabled")
    r = api.mutate("POST", _receive_path(_seed_product(before)), {"quantity": 1})
    assert _error(r) == (403, "module_disabled")
    assert api.snapshot() == before


def test_product_record_limit(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product (id, workspace_id, sku, name, price_minor, cost_minor) "
                "SELECT gen_random_uuid(), w.id, 'S', 'x', 1, 1 "
                "FROM workspace w, generate_series(1, 498)"
            )
        )
    before = api.snapshot()
    r = api.mutate("POST", PRODUCTS, NEW_PRODUCT)
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("UPDATE product SET on_hand = on_hand + 1 WHERE sku = 'T-001'", "stock_invalid"),
        (
            "UPDATE product SET stock_value_minor = stock_value_minor - 1 WHERE sku = 'T-001'",
            "stock_invalid",
        ),
        ("UPDATE product SET reserved = on_hand + 1 WHERE sku = 'T-001'", "stock_invalid"),
        ("UPDATE product_lot SET quantity = 0", "number_invalid"),
        ("UPDATE product_lot SET quantity = 2", "stock_invalid"),
        ("UPDATE product SET price_minor = -1 WHERE sku = 'T-001'", "number_invalid"),
        ("UPDATE purchase SET total_minor = total_minor + 1", "purchase_invalid"),
        (
            "UPDATE ledger_entry SET amount_minor = amount_minor - 500 "
            "WHERE idx = 0 AND ledger_id IN "
            "(SELECT id FROM ledger WHERE kind = 'inventory.receive')",
            "ledger_invalid",
        ),
        ("UPDATE product SET name = '' WHERE sku = 'T-001'", "product_invalid"),
    ],
)
def test_tampered_stock_rejected(api: ApiClient, db_engine: Engine, sql: str, code: str) -> None:
    api.setup()
    _fund_business(api, 10_000)
    pid = _create(api)
    api.ok("POST", _receive_path(pid), {"quantity": 3})
    with db_engine.begin() as conn:
        conn.execute(text(sql))
    before = api.snapshot()
    r = api.mutate("POST", PRODUCTS, NEW_PRODUCT)
    assert r.json()["error"]["code"] == code
    assert api.snapshot() == before


# --- service 單元測試：成本層與預留 ------------------------------------------------


@pytest.fixture
def ctx(api: ApiClient, db_engine: Engine, test_settings: Settings):
    api.setup()
    with Session(db_engine) as db:
        yield workspace_ctx(db, test_settings)
        db.rollback()


def _pid(ctx: CommandContext) -> str:
    return INVENTORY_SPEC.snapshot(ctx.db, ctx.workspace_id)["products"][0]["id"]


def _snap_product(ctx: CommandContext, pid: str) -> dict[str, Any]:
    return _product(INVENTORY_SPEC.snapshot(ctx.db, ctx.workspace_id), pid)


def test_consume_fifo_across_lots(ctx: CommandContext) -> None:
    pid = _pid(ctx)
    inventory.push_lot(ctx, pid, 2, 100)
    inventory.push_lot(ctx, pid, 3, 200)
    taken = inventory.consume_fifo(ctx, pid, 4, corrupt_code="stock_invalid")
    assert taken == [(2, 100), (2, 200)]
    p = _snap_product(ctx, pid)
    assert (p["on_hand"], p["stock_value_minor"], p["lots"]) == (
        1,
        200,
        [{"quantity": 1, "cost_minor": 200}],
    )


def test_consume_fifo_short_uses_caller_code(ctx: CommandContext) -> None:
    pid = _pid(ctx)
    inventory.push_lot(ctx, pid, 1, 100)
    with pytest.raises(Problem) as e:
        inventory.consume_fifo(ctx, pid, 2, corrupt_code="order_stock_invalid")
    assert (e.value.status, e.value.code) == (409, "order_stock_invalid")


def test_reserve_and_release(ctx: CommandContext) -> None:
    pid = _pid(ctx)
    inventory.push_lot(ctx, pid, 3, 100)
    inventory.reserve(ctx, pid, 2, code="simulation_out_of_stock", message="模擬庫存不足。")
    assert _snap_product(ctx, pid)["reserved"] == 2
    with pytest.raises(Problem) as e:
        inventory.reserve(ctx, pid, 2, code="simulation_out_of_stock", message="模擬庫存不足。")
    assert (e.value.status, e.value.code) == (409, "simulation_out_of_stock")
    inventory.release_reserved(ctx, pid, 2)
    assert _snap_product(ctx, pid)["reserved"] == 0


def test_reserved_demand_hook(ctx: CommandContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "_RESERVED_DEMANDS", [])
    inventory.register_reserved_demand(lambda db, ws: {"a": 2, "b": 1})
    inventory.register_reserved_demand(lambda db, ws: {"a": 3})
    assert inventory.reserved_demand(ctx.db, ctx.workspace_id) == {"a": 5, "b": 1}


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    api.setup()
    _fund_business(api, 10_000)
    pid = _create(api)
    api.ok("POST", _receive_path(pid), {"quantity": 2})
    api.ok("PATCH", _product_path(pid), {"cost_minor": 300})
    api.ok("POST", _receive_path(pid), {"quantity": 1})
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = INVENTORY_SPEC.snapshot(db, ctx.workspace_id)
        db.execute(text("DELETE FROM purchase"))
        db.execute(text("DELETE FROM product"))
        assert INVENTORY_SPEC.snapshot(db, ctx.workspace_id) == {"products": [], "purchases": []}
        INVENTORY_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert INVENTORY_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()


def test_clear_cascades_business_data(api: ApiClient, db_engine: Engine) -> None:
    """清除工作區時，錢包、帳本、商品、成本層與採購都以外鍵串聯刪除。"""
    api.setup()
    _fund_business(api, 10_000)
    api.ok("POST", _receive_path(_create(api)), {"quantity": 2})
    api.ok("POST", "/api/v1/workspace/clear", {})
    with db_engine.connect() as conn:
        for table in ("wallet", "ledger", "ledger_entry", "product", "product_lot", "purchase"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
