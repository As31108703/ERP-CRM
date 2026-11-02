"""測試基礎：建立獨立測試資料庫、跑 goose migration、每個測試後清空資料表。"""

import os
import subprocess
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, text

from src.app import create_app
from src.config.settings import AppConfig, DatabaseConfig, Settings
from src.core import clock
from src.core.problem import Problem
from src.platform.context import CommandContext, HistoryRow
from src.platform.pipeline import (
    CommandPipeline,
    MutationResponse,
    get_pipeline,
    raw_body,
    touch_session,
)
from tests.helpers import ApiClient

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://erpcrm:erpcrm@localhost:5436/erpcrm_test"
)
BACKEND_DIR = Path(__file__).resolve().parent.parent

_url = urlsplit(TEST_DATABASE_URL)
TEST_DB_NAME = _url.path.lstrip("/")
# 連到維護用的 postgres 資料庫，才能 drop / create 測試資料庫
ADMIN_DATABASE_URL = urlunsplit(_url._replace(path="/postgres"))


def _sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        app=AppConfig(allowed_origins=[]),
        database=DatabaseConfig(
            host=_url.hostname or "localhost",
            port=_url.port or 5432,
            user=unquote(_url.username or ""),
            password=unquote(_url.password or ""),
            name=TEST_DB_NAME,
        ),
    )


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
        ident = sql.Identifier(TEST_DB_NAME)
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(ident))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(ident))

    subprocess.run(
        ["goose", "-dir", "migrations", "postgres", TEST_DATABASE_URL, "up"],
        cwd=BACKEND_DIR,
        check=True,
        capture_output=True,
    )

    engine = create_engine(_sqlalchemy_url(TEST_DATABASE_URL))
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _monotonic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """系統時鐘可能倒退（WSL 實測約 1.5 秒），測試中讓 utcnow 不倒退，避免時間順序規則誤判。

    測試自己再 monkeypatch `clock.utcnow`（例如固定時間）時，以測試的設定為準。
    """
    real = clock.utcnow
    last = [datetime.min.replace(tzinfo=UTC)]

    def now() -> datetime:
        last[0] = max(real(), last[0])
        return last[0]

    monkeypatch.setattr(clock, "utcnow", now)


@pytest.fixture(autouse=True)
def _truncate_tables(db_engine: Engine) -> Iterator[None]:
    yield
    with db_engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'goose_db_version'"
            )
        ).scalars()
        names = ", ".join(f'"public"."{t}"' for t in tables)
        if names:
            conn.execute(text(f"TRUNCATE {names} CASCADE"))


def _echo(_ctx: CommandContext, payload: dict) -> str | None:
    return "ok"


def _boom(ctx: CommandContext, _payload: dict) -> str | None:
    # 先寫入一筆 history 再失敗，用來確認整筆回滾
    assert ctx.workspace is not None
    ctx.db.add(HistoryRow(workspace_id=ctx.workspace.id, action="test.boom", version=999))
    ctx.db.flush()
    raise Problem(422, "test_boom", "測試用失敗")


def _slow(_ctx: CommandContext, _payload: dict) -> str | None:
    # 拉長持鎖時間，讓並行測試的兩個請求確實重疊
    time.sleep(0.3)
    return "slow"


def make_test_router() -> APIRouter:
    """只在測試時掛上的 `/api/v1/_test/*` 路由。"""
    router = APIRouter(prefix="/api/v1/_test")
    Pipeline = Depends(get_pipeline)
    Raw = Depends(raw_body)

    @router.get("/csrf")
    def csrf(ctx: CommandContext = Depends(touch_session)) -> dict[str, object]:
        return {"csrf": ctx.session_row.csrf, "version": ctx.session_row.version}

    @router.post("/echo")
    def echo(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(
            request, raw, action="test.echo", handler=_echo, needs_workspace=False
        )

    @router.post("/command")
    def command(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(request, raw, action="test.command", handler=_echo)

    @router.post("/boom")
    def boom(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(request, raw, action="test.boom", handler=_boom)

    @router.post("/slow")
    def slow(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(request, raw, action="test.slow", handler=_slow)

    @router.post("/prune")
    def prune(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(
            request,
            raw,
            action="test.prune",
            handler=_echo,
            needs_workspace=False,
            prunes_receipts=True,
            bypass_receipt_cap=True,
        )

    @router.post("/module/{name}")
    def module(
        name: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return pipeline.mutate(request, raw, action=f"{name}.test", handler=_echo, module=name)

    return router


def build_test_app(settings: Settings) -> FastAPI:
    app = create_app(settings)
    app.include_router(make_test_router())
    return app


@pytest.fixture
def make_client(test_settings: Settings, db_engine: Engine) -> Iterator[Callable[..., TestClient]]:
    """以覆寫過的 app 設定建立 TestClient，例如 `make_client(public_demo=True)`。"""
    opened: list[TestClient] = []

    def factory(**app_overrides: object) -> TestClient:
        settings = test_settings.model_copy(
            update={"app": test_settings.app.model_copy(update=app_overrides)}
        )
        c = TestClient(build_test_app(settings), base_url="http://testserver")
        c.__enter__()
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def client(test_settings: Settings, db_engine: Engine) -> Iterator[TestClient]:
    with TestClient(build_test_app(test_settings), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def api(client: TestClient) -> ApiClient:
    return ApiClient(client)
