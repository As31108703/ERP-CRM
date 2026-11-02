"""測試用 API 輔助：寫入請求自動帶 csrf、Idempotency-Key 與 If-Match-Version。"""

import uuid
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from src.config.settings import Settings
from src.core import clock
from src.platform.context import CommandContext, WorkspaceRow, WorkspaceSessionRow

# conftest 只在測試時註冊的路由：回傳目前 session 的 csrf 與版本號
TEST_STATE_PATH = "/api/v1/_test/csrf"
VIEW_PATH = "/api/v1/workspace/view"
PRODUCTS = "/api/v1/inventory/products"
ORDERS = "/api/v1/sales/orders"
PRICE = 900


def new_key() -> str:
    return uuid.uuid4().hex


class ApiClient:
    """包一層 TestClient，讓測試以一致的方式呼叫 API。"""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.put(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.patch(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.delete(path, **kwargs)

    def state(self) -> dict[str, Any]:
        """`{"csrf", "version"}`；不依賴工作區模組，任何 Task 都能用。"""
        r = self.client.get(TEST_STATE_PATH)
        assert r.status_code == 200, r.text
        return r.json()

    def view(self) -> dict[str, Any]:
        r = self.client.get(VIEW_PATH)
        assert r.status_code == 200, r.text
        return r.json()

    def snapshot(self) -> dict[str, Any]:
        return self.view()["workspace"]

    def mutate(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        key: str | None = None,
        version: int | None = None,
        csrf: str | None = None,
        origin: str = "http://testserver",
    ) -> httpx.Response:
        if csrf is None or version is None:
            current = self.state()
            csrf = current["csrf"] if csrf is None else csrf
            version = current["version"] if version is None else version
        headers = {
            "Origin": origin,
            "x-csrf-token": csrf,
            "Idempotency-Key": key or new_key(),
            "If-Match-Version": str(version),
            "Content-Type": "application/json",
        }
        return self.client.request(method, path, json=body or {}, headers=headers)

    def ok(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.mutate(method, path, body)
        assert 200 <= r.status_code < 300, r.text
        return r.json()

    def setup(
        self,
        industry: str = "general",
        company: str = "測試公司",
        modules: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"industry": industry, "company_name": company}
        if modules is not None:
            body["modules"] = modules
        return self.ok("POST", "/api/v1/workspace/setup", body)


def workspace_ctx(db: Session, settings: Settings) -> CommandContext:
    """直接呼叫 service 的單元測試用：以資料庫中唯一的工作區組出 CommandContext。"""
    workspace = db.exec(select(WorkspaceRow)).one()
    session_row = db.get(WorkspaceSessionRow, workspace.session_id)
    assert session_row is not None
    return CommandContext(
        db=db, session_row=session_row, workspace=workspace, now=clock.utcnow(), settings=settings
    )


# --- 銷售流程輔助（test_sales、test_reports 共用） ------------------------------------


def wallet_of(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def fund(api: ApiClient, wallet_id: str, amount: int) -> None:
    api.ok("POST", f"/api/v1/wallets/{wallet_id}/fund", {"amount_minor": amount})


def buyer_wallet(api: ApiClient) -> str:
    return wallet_of(api.snapshot(), "buyer")["id"]


def stocked_product(api: ApiClient, batches: list[tuple[int, int]], price: int = PRICE) -> str:
    """建立商品並依序以 (數量, 成本) 分批入庫。"""
    business = wallet_of(api.snapshot(), "business")["id"]
    fund(api, business, sum(q * c for q, c in batches) or 1)
    first_cost = batches[0][1] if batches else 0
    pid = api.ok(
        "POST",
        PRODUCTS,
        {"name": "測試商品", "sku": "T-001", "price_minor": price, "cost_minor": first_cost},
    )["result"]
    for quantity, cost in batches:
        api.ok("PATCH", f"{PRODUCTS}/{pid}", {"cost_minor": cost})
        api.ok("POST", f"{PRODUCTS}/{pid}/receive", {"quantity": quantity})
    return pid


def create_order(api: ApiClient, buyer: str, lines: list[tuple[str, int]], **extra: Any) -> str:
    body = {
        "buyer_wallet_id": buyer,
        "lines": [{"product_id": pid, "quantity": q} for pid, q in lines],
        **extra,
    }
    return api.ok("POST", ORDERS, body)["result"]


def line_ids(api: ApiClient, order_id: str) -> list[str]:
    order = next(o for o in api.snapshot()["orders"] if o["id"] == order_id)
    return [line["id"] for line in order["lines"]]


def ship_body(lines: list[tuple[str, int]]) -> dict[str, Any]:
    return {"lines": [{"line_id": lid, "quantity": q} for lid, q in lines]}
