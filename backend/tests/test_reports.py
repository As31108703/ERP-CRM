"""模擬報表（B§4）：FIFO 出貨成本與毛利、目錄成本估算毛利、庫存價值、服務收款，
以及啟用行政模組時的 `administration` 指標。"""

from typing import Any

from sqlalchemy import Engine, text
from sqlmodel import Session

from src.modules.administration.metrics import admin_metrics
from src.modules.reports.service import build_report
from tests.helpers import ApiClient
from tests.test_sales import (
    ORDERS,
    PRICE,
    _buyer,
    _create_order,
    _fund,
    _line_ids,
    _ship_body,
    _stocked_product,
)

REPORTS = "/api/v1/reports"
SERVICES = "/api/v1/services"
CASES = "/api/v1/crm/cases"
ADMIN_DEMO = "/api/v1/administration/demo"
ADMIN_ZERO = {
    "active_units": 0,
    "active_staff": 0,
    "scheduled_shifts": 0,
    "actual_work_minutes": 0,
    "open_requests": 0,
    "prepared_unreviewed_requests": 0,
    "available_equipment": 0,
    "active_reservations": 0,
    "pinned_notices": 0,
}
SALES_KEYS = [
    "sales_minor",
    "refunds_minor",
    "cost_of_goods_sold_minor",
    "gross_profit_minor",
    "estimated_gross_profit_minor",
    "gross_profit_basis",
    "inventory_value_minor",
    "service_payments_minor",
]


def _report(api: ApiClient) -> dict[str, Any]:
    """GET /reports 與 view.report 必須一致。"""
    r = api.get(REPORTS)
    assert r.status_code == 200, r.text
    report = r.json()
    assert api.view()["report"] == report
    return report


def _shipped_order(api: ApiClient) -> tuple[str, str, str]:
    """Task 6 流程：成本 100×2、200×2 兩批入庫（目錄成本最後改為 200），售出 3 件並出貨。"""
    pid = _stocked_product(api, [(2, 100), (2, 200)])
    buyer = _buyer(api)
    _fund(api, buyer, 3 * PRICE)
    oid = _create_order(api, buyer, [(pid, 3)])
    api.ok("POST", f"{ORDERS}/{oid}/pay", {"amount_minor": 3 * PRICE})
    [lid] = _line_ids(api, oid)
    api.ok("POST", f"{ORDERS}/{oid}/ship", _ship_body([(lid, 3)]))
    return pid, oid, lid


def _ws_id(engine: Engine) -> str:
    with Session(engine) as db:
        return str(db.execute(text("SELECT id FROM workspace")).scalar_one())


def test_report_fifo_cogs(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "sales", "wallets"])
    assert _report(api) == {
        "sales_minor": 0,
        "refunds_minor": 0,
        "cost_of_goods_sold_minor": 0,
        "gross_profit_minor": 0,
        "estimated_gross_profit_minor": 0,
        "gross_profit_basis": "actual_simulation_fifo",
        "inventory_value_minor": 0,
        "service_payments_minor": 0,
    }
    _shipped_order(api)
    report = _report(api)
    # 實際 FIFO：2×100 + 1×200；下單時的目錄成本快照是 200
    assert report["cost_of_goods_sold_minor"] == 400
    assert report["sales_minor"] == 3 * PRICE
    assert report["refunds_minor"] == 0
    assert report["gross_profit_minor"] == (
        report["sales_minor"] - report["refunds_minor"] - report["cost_of_goods_sold_minor"]
    )
    assert report["gross_profit_minor"] == 3 * PRICE - 400
    assert report["estimated_gross_profit_minor"] == 3 * PRICE - 3 * 200
    assert report["gross_profit_basis"] == "actual_simulation_fifo"
    # 剩下成本 200 的一件
    assert report["inventory_value_minor"] == 200
    assert report["service_payments_minor"] == 0
    # 沒啟用行政模組就沒有 administration 區塊；欄位順序照 B§4
    assert list(report) == SALES_KEYS


def test_report_after_partial_return(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "sales", "wallets"])
    _, oid, lid = _shipped_order(api)
    api.ok("POST", f"{ORDERS}/{oid}/return", _ship_body([(lid, 1)]))
    report = _report(api)
    # 退回的一件沖回第一個成本層：COGS = 100×(2−1) + 200×1
    assert report == {
        "sales_minor": 3 * PRICE,
        "refunds_minor": PRICE,
        "cost_of_goods_sold_minor": 300,
        "gross_profit_minor": 3 * PRICE - PRICE - 300,
        "estimated_gross_profit_minor": 3 * PRICE - PRICE - 2 * 200,
        "gross_profit_basis": "actual_simulation_fifo",
        "inventory_value_minor": 300,
        "service_payments_minor": 0,
    }
    # 全部退完：毛利歸零，成本全數回到庫存
    api.ok("POST", f"{ORDERS}/{oid}/return", _ship_body([(lid, 2)]))
    report = _report(api)
    assert (
        report["sales_minor"],
        report["refunds_minor"],
        report["cost_of_goods_sold_minor"],
        report["gross_profit_minor"],
        report["estimated_gross_profit_minor"],
        report["inventory_value_minor"],
    ) == (3 * PRICE, 3 * PRICE, 0, 0, 0, 600)


def test_report_service_payments(api: ApiClient) -> None:
    api.setup("general", modules=["crm", "services", "wallets"])
    case = api.ok("POST", CASES, {"title": "官網改版", "name": "不採用"})["result"]
    sid = api.ok("POST", SERVICES, {"case_id": case, "amount_minor": 1000})["result"]
    api.ok("POST", f"{SERVICES}/{sid}/confirm", {})
    api.ok("POST", f"{SERVICES}/{sid}/deliver", {"artifact_ref": "artifact://v1"})
    service = next(s for s in api.snapshot()["services"] if s["id"] == sid)
    delivery = service["deliveries"][-1]
    api.ok(
        "POST",
        f"{SERVICES}/{sid}/accept",
        {"delivery_id": delivery["id"], "digest": delivery["digest"]},
    )
    buyer = _buyer(api)
    _fund(api, buyer, 1000)
    api.ok("POST", f"{SERVICES}/{sid}/pay", {"buyer_wallet_id": buyer, "amount_minor": 400})
    assert _report(api)["service_payments_minor"] == 400


def test_report_includes_admin_metrics(api: ApiClient, db_engine: Engine) -> None:
    api.setup("general")
    report = _report(api)
    assert list(report) == [*SALES_KEYS, "administration"]
    assert report["administration"] == ADMIN_ZERO
    api.ok("POST", ADMIN_DEMO, {"preset": "office", "week_start": "2026-11-02"})
    report = _report(api)
    with Session(db_engine) as db:
        expected = admin_metrics(db, _ws_id(db_engine))
    assert report["administration"] == expected
    assert report["administration"]["actual_work_minutes"] == 2 * (470 - 60)
    assert list(report["administration"]) == list(ADMIN_ZERO)


def test_report_admin_enabled_later(api: ApiClient) -> None:
    api.setup("general", modules=["inventory"])
    assert "administration" not in _report(api)
    api.ok("POST", "/api/v1/administration/enable", {})
    assert _report(api)["administration"] == ADMIN_ZERO


def test_build_report_direct(api: ApiClient, db_engine: Engine) -> None:
    api.setup("general")
    with Session(db_engine) as db:
        assert build_report(db, _ws_id(db_engine)) == api.view()["report"]


def test_report_read_only(api: ApiClient) -> None:
    api.setup("general")
    _shipped_order(api)
    before = api.view()
    _report(api)
    after = api.view()
    assert after["version"] == before["version"]
    assert after["workspace"] == before["workspace"]


def test_report_without_workspace(api: ApiClient) -> None:
    view = api.view()
    assert view["workspace"] is None
    assert view["report"] is None
    r = api.get(REPORTS)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "workspace_missing")


def test_report_overflow_422(api: ApiClient, db_engine: Engine) -> None:
    """加總超出 JS 安全整數時回 422，不輸出失真的數字。"""
    api.setup("general", modules=["inventory"])
    with Session(db_engine) as db:
        db.execute(text("UPDATE product SET stock_value_minor = :v"), {"v": 2**53 - 1})
        db.commit()
    r = api.get(REPORTS)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "simulation_amount_overflow")
