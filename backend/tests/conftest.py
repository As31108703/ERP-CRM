"""測試基礎：建立獨立測試資料庫、跑 goose migration、每個測試後清空資料表。"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Engine, create_engine, text

from src.app import create_app
from src.config.settings import AppConfig, DatabaseConfig, Settings
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


@pytest.fixture
def client(test_settings: Settings, db_engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(test_settings), base_url="http://testserver") as c:
        yield c


@pytest.fixture
def api(client: TestClient) -> ApiClient:
    return ApiClient(client)
