"""錢包與複式帳本：建立買家錢包、補幣、move()、帳本與守恆檢查、快照還原。"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.core.problem import Problem
from src.modules.wallets import service as wallets
from src.modules.wallets.router import SPEC as WALLETS_SPEC
from src.platform.context import CommandContext
from tests.helpers import ApiClient, workspace_ctx

WALLETS = "/api/v1/wallets"


def _fund_path(wallet_id: str) -> str:
    return f"{WALLETS}/{wallet_id}/fund"


def _wallet(ws: dict[str, Any], kind: str, name: str | None = None) -> dict[str, Any]:
    rows = [w for w in ws["wallets"] if w["kind"] == kind and (name is None or w["name"] == name)]
    assert len(rows) == 1, rows
    return rows[0]


def _buyer_id(api: ApiClient) -> str:
    return _wallet(api.snapshot(), "buyer", "示範買家")["id"]


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


# --- seed -----------------------------------------------------------------------


def test_seed_system_and_demo_buyer_wallets(api: ApiClient) -> None:
    api.setup("service")  # 未啟用 inventory 的範本也一樣建立錢包（B§3.0）
    ws = api.snapshot()
    assert [(w["kind"], w["name"], w["balance_minor"]) for w in ws["wallets"]] == [
        ("business", "business", 0),
        ("supplier", "supplier", 0),
        ("faucet", "faucet", 0),
        ("buyer", "示範買家", 0),
    ]
    assert ws["ledger"] == []


# --- wallet.create / wallet.fund -------------------------------------------------


def test_create_buyer_wallet(api: ApiClient) -> None:
    api.setup()
    body = api.ok("POST", WALLETS, {"kind": "buyer", "name": "王小明"})
    row = _wallet(api.snapshot(), "buyer", "王小明")
    assert row["id"] == body["result"]
    assert row["balance_minor"] == 0
    assert api.snapshot()["history"][-1]["action"] == "wallet.create"


def test_fund_moves_from_faucet(api: ApiClient) -> None:
    api.setup()
    buyer = _buyer_id(api)
    body = api.ok("POST", _fund_path(buyer), {"amount_minor": 100000})
    ws = api.snapshot()
    assert _wallet(ws, "faucet")["balance_minor"] == -100000
    assert _wallet(ws, "buyer", "示範買家")["balance_minor"] == 100000
    [ledger] = ws["ledger"]
    assert ledger["kind"] == "wallet.fund"
    assert ledger["id"] == body["result"]
    assert ledger["reference_id"] == ledger["id"]
    assert ledger["entries"] == [
        {"wallet_id": _wallet(ws, "faucet")["id"], "amount_minor": -100000},
        {"wallet_id": buyer, "amount_minor": 100000},
    ]


def test_fund_business_allowed(api: ApiClient) -> None:
    api.setup()
    business = _wallet(api.snapshot(), "business")["id"]
    api.ok("POST", _fund_path(business), {"amount_minor": 5})
    assert _wallet(api.snapshot(), "business")["balance_minor"] == 5


def test_fund_supplier_rejected(api: ApiClient) -> None:
    api.setup()
    supplier = _wallet(api.snapshot(), "supplier")["id"]
    r = api.mutate("POST", _fund_path(supplier), {"amount_minor": 100})
    assert _error(r) == (422, "simulation_wallet_invalid")


def test_payload_id_cannot_override_wallet(api: ApiClient) -> None:
    api.setup()
    forced = str(uuid.uuid4())
    body = api.ok("POST", WALLETS, {"kind": "buyer", "name": "甲", "id": forced})
    assert body["result"] != forced
    assert _wallet(api.snapshot(), "buyer", "甲")["id"] == body["result"]


def test_path_wallet_id_wins_over_body(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    buyer = _buyer_id(api)
    business = _wallet(ws, "business")["id"]
    api.ok("POST", _fund_path(buyer), {"wallet_id": business, "amount_minor": 7})
    ws = api.snapshot()
    assert _wallet(ws, "buyer", "示範買家")["balance_minor"] == 7
    assert _wallet(ws, "business")["balance_minor"] == 0


def test_forbidden_key_simulation_required_wallet(api: ApiClient) -> None:
    api.setup()
    r = api.mutate("POST", WALLETS, {"kind": "buyer", "name": "甲", "payer_account": "x"})
    assert _error(r) == (422, "simulation_required")


# --- invariants -----------------------------------------------------------------


def test_invariant_money_conservation(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    api.ok("POST", _fund_path(_buyer_id(api)), {"amount_minor": 100})
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE wallet SET balance_minor = balance_minor + 5 WHERE kind = 'buyer'")
        )
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", WALLETS, {"kind": "buyer", "name": "乙"})
    assert _error(r) == (422, "money_conservation")
    r = api.mutate(
        "POST",
        "/api/v1/inventory/products",
        {"name": "新品", "sku": "N-1", "price_minor": 1, "cost_minor": 1},
    )
    assert _error(r) == (422, "money_conservation")
    assert api.snapshot() == before
    assert api.state()["version"] == version


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        # 非 faucet 錢包為負
        (
            "UPDATE wallet SET balance_minor = balance_minor - 200 WHERE kind = 'buyer';"
            "UPDATE wallet SET balance_minor = balance_minor + 200 WHERE kind = 'faucet'",
            "wallet_invalid",
        ),
        # 餘額守恆但與帳本不符
        (
            "UPDATE wallet SET balance_minor = balance_minor - 10 WHERE kind = 'buyer';"
            "UPDATE wallet SET balance_minor = balance_minor + 10 WHERE kind = 'business'",
            "ledger_balance_invalid",
        ),
        # 分錄總和不為 0
        ("UPDATE ledger_entry SET amount_minor = amount_minor + 1 WHERE idx = 1", "ledger_invalid"),
        # 補幣流水的 reference 不是自己
        ("UPDATE ledger SET reference_id = gen_random_uuid()", "ledger_invalid"),
        # 未知流水種類
        ("UPDATE ledger SET kind = 'order.unknown'", "ledger_invalid"),
        # 方向相反：買家 → faucet
        ("UPDATE ledger_entry SET amount_minor = -amount_minor", "ledger_invalid"),
        # 少一個分錄
        ("DELETE FROM ledger_entry WHERE idx = 1", "ledger_invalid"),
        # 系統錢包重複
        (
            "INSERT INTO wallet (id, workspace_id, kind, name) "
            "SELECT gen_random_uuid(), workspace_id, 'supplier', 'x' FROM wallet LIMIT 1",
            "wallet_invalid",
        ),
    ],
)
def test_tampered_wallets_rejected(api: ApiClient, db_engine: Engine, sql: str, code: str) -> None:
    api.setup()
    api.ok("POST", _fund_path(_buyer_id(api)), {"amount_minor": 100})
    with db_engine.begin() as conn:
        for stmt in sql.split(";"):
            conn.execute(text(stmt))
    before = api.snapshot()
    r = api.mutate("POST", WALLETS, {"kind": "buyer", "name": "乙"})
    assert r.json()["error"]["code"] == code
    assert r.status_code == 422
    assert api.snapshot() == before


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


def _fill_wallets(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO wallet (id, workspace_id, kind, name) "
                "SELECT gen_random_uuid(), w.id, 'buyer', 'x' "
                "FROM workspace w, generate_series(1, 496)"
            )
        )


Case = tuple[str, Callable[[dict[str, Any]], tuple[str, dict[str, Any]]], int, str]

_CASES: list[Case] = [
    (
        "create_supplier",
        lambda ws: (WALLETS, {"kind": "supplier", "name": "x"}),
        422,
        "wallet_invalid",
    ),
    ("create_no_name", lambda ws: (WALLETS, {"kind": "buyer"}), 422, "wallet_invalid"),
    (
        "create_name_not_str",
        lambda ws: (WALLETS, {"kind": "buyer", "name": 1}),
        422,
        "wallet_invalid",
    ),
    (
        "create_bank",
        lambda ws: (WALLETS, {"kind": "buyer", "name": "x", "bank": "1"}),
        422,
        "simulation_required",
    ),
    (
        "create_balance",
        lambda ws: (WALLETS, {"kind": "buyer", "name": "x", "balance_minor": 9}),
        422,
        "protected_field",
    ),
    (
        "create_currency",
        lambda ws: (WALLETS, {"kind": "buyer", "name": "x", "currency": "TWD"}),
        422,
        "protected_field",
    ),
    (
        "create_learning",
        lambda ws: (WALLETS, {"kind": "buyer", "name": "x", "learning_run_id": "abcdefgh"}),
        422,
        "learning_id_invalid",
    ),
    (
        "create_lines_empty",
        lambda ws: (WALLETS, {"kind": "buyer", "name": "x", "lines": []}),
        422,
        "lines_invalid",
    ),
    (
        "fund_supplier",
        lambda ws: (_fund_path(_wallet(ws, "supplier")["id"]), {"amount_minor": 1}),
        422,
        "simulation_wallet_invalid",
    ),
    (
        "fund_faucet",
        lambda ws: (_fund_path(_wallet(ws, "faucet")["id"]), {"amount_minor": 1}),
        422,
        "simulation_wallet_invalid",
    ),
    (
        "fund_missing",
        lambda ws: (_fund_path(str(uuid.uuid4())), {"amount_minor": 1}),
        404,
        "simulation_record_missing",
    ),
    (
        "fund_not_uuid",
        lambda ws: (_fund_path("not-a-uuid"), {"amount_minor": 1}),
        404,
        "simulation_record_missing",
    ),
    (
        "fund_zero",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {"amount_minor": 0}),
        422,
        "number_invalid",
    ),
    (
        "fund_negative",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {"amount_minor": -5}),
        422,
        "number_invalid",
    ),
    (
        "fund_fraction",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {"amount_minor": 1.5}),
        422,
        "number_invalid",
    ),
    (
        "fund_string",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {"amount_minor": "5"}),
        422,
        "number_invalid",
    ),
    (
        "fund_too_big",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {"amount_minor": 1_000_000_001}),
        422,
        "number_invalid",
    ),
    (
        "fund_no_amount",
        lambda ws: (_fund_path(_wallet(ws, "buyer")["id"]), {}),
        422,
        "number_invalid",
    ),
    (
        "fund_finance",
        lambda ws: (
            _fund_path(_wallet(ws, "buyer")["id"]),
            {"amount_minor": 1, "Finance_ref": "x"},
        ),
        422,
        "simulation_required",
    ),
]


@pytest.mark.parametrize(("name", "make", "status", "code"), _CASES, ids=[c[0] for c in _CASES])
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient, name: str, make: Callable, status: int, code: str
) -> None:
    api.setup()
    before = api.snapshot()
    version = api.state()["version"]
    path, body = make(before)
    r = api.mutate("POST", path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_wallet_record_limit(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    _fill_wallets(db_engine)  # 4 個種子錢包 + 496 = 500
    before = api.snapshot()
    r = api.mutate("POST", WALLETS, {"kind": "buyer", "name": "第 501 個"})
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before


def test_wallets_module_disabled(api: ApiClient) -> None:
    api.setup("general", modules=["crm"])
    before = api.snapshot()
    r = api.mutate("POST", _fund_path(_wallet(before, "buyer")["id"]), {"amount_minor": 1})
    assert _error(r) == (403, "module_disabled")
    r = api.mutate("POST", WALLETS, {"kind": "buyer", "name": "x"})
    assert _error(r) == (403, "module_disabled")
    assert api.snapshot() == before


# --- service 單元測試 -----------------------------------------------------------


@pytest.fixture
def ctx(api: ApiClient, db_engine: Engine, test_settings: Settings):
    api.setup()
    with Session(db_engine) as db:
        yield workspace_ctx(db, test_settings)
        db.rollback()


def test_move_negative_amount_invalid(ctx: CommandContext) -> None:
    business = wallets.wallet_of_kind(ctx, "business")
    supplier = wallets.wallet_of_kind(ctx, "supplier")
    with pytest.raises(Problem) as e:
        wallets.move(ctx, "inventory.receive", str(business.id), str(supplier.id), -1)
    assert (e.value.status, e.value.code) == (422, "simulation_amount_invalid")


def test_move_insufficient_funds(ctx: CommandContext) -> None:
    business = wallets.wallet_of_kind(ctx, "business")
    supplier = wallets.wallet_of_kind(ctx, "supplier")
    with pytest.raises(Problem) as e:
        wallets.move(ctx, "inventory.receive", str(business.id), str(supplier.id), 1)
    assert (e.value.status, e.value.code) == (409, "simulation_insufficient_funds")


def test_move_zero_and_reference(ctx: CommandContext) -> None:
    business = wallets.wallet_of_kind(ctx, "business")
    supplier = wallets.wallet_of_kind(ctx, "supplier")
    ref = str(uuid.uuid4())
    ledger_id = wallets.move(ctx, "inventory.receive", str(business.id), str(supplier.id), 0, ref)
    snap = WALLETS_SPEC.snapshot(ctx.db, ctx.workspace_id)
    [row] = snap["ledger"]
    assert row["id"] == ledger_id
    assert row["reference_id"] == ref


def test_ensure_system_wallets_idempotent(ctx: CommandContext) -> None:
    wallets.ensure_system_wallets(ctx)
    kinds = [w["kind"] for w in WALLETS_SPEC.snapshot(ctx.db, ctx.workspace_id)["wallets"]]
    assert kinds == ["business", "supplier", "faucet", "buyer"]


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    api.setup()
    buyer = _buyer_id(api)
    api.ok("POST", _fund_path(buyer), {"amount_minor": 300})
    api.ok("POST", WALLETS, {"kind": "buyer", "name": "乙"})
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = WALLETS_SPEC.snapshot(db, ctx.workspace_id)
        db.execute(text("DELETE FROM ledger"))
        db.execute(text("DELETE FROM wallet"))
        assert WALLETS_SPEC.snapshot(db, ctx.workspace_id) == {"wallets": [], "ledger": []}
        WALLETS_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert WALLETS_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()
