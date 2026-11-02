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
