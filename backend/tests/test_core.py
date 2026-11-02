"""核心工具與錯誤格式。"""

from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from src.app import create_app
from src.core import clock
from src.core.canonical import canonical_json, digest
from src.core.clock import iso, parse_instant, taipei_monday
from src.core.db import get_db, make_engine
from src.core.ids import new_id, token_hex
from src.core.money import check_int
from src.core.problem import Problem, ensure

INTERNAL_MESSAGE = "無法完成模擬操作，請確認原操作結果"


def _app_with_test_routes(test_settings):
    app = create_app(test_settings)
    router = APIRouter()

    @router.get("/api/v1/_test/problem")
    def raise_problem():
        raise Problem(429, "rate_limit", "x", 1500)

    @router.get("/api/v1/_test/boom")
    def raise_unexpected():
        raise RuntimeError("secret detail")

    @router.get("/api/v1/_test/db")
    def use_db(db: Annotated[Session, Depends(get_db)]):
        return {"one": db.execute(text("SELECT 1")).scalar_one()}

    @router.post("/api/v1/_test/typed")
    def typed(body: TypedBody):
        return {"quantity": body.quantity}

    app.include_router(router)
    return app


class TypedBody(BaseModel):
    quantity: int


@pytest.fixture
def test_client(test_settings, db_engine):
    app = _app_with_test_routes(test_settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _assert_security_headers(r):
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


# ── 錯誤格式 ──────────────────────────────────────────────


def test_problem_response_shape(test_client):
    r = test_client.get("/api/v1/_test/problem")
    assert r.status_code == 429
    assert r.json() == {"error": {"code": "rate_limit", "message": "x", "retry_after_ms": 1500}}
    assert r.headers["retry-after"] == "2"
    _assert_security_headers(r)


def test_problem_without_retry_omits_field_and_header(test_settings, db_engine):
    app = create_app(test_settings)

    @app.get("/api/v1/_test/missing")
    def missing():
        ensure(False, 404, "not_found", "找不到")

    with TestClient(app) as c:
        r = c.get("/api/v1/_test/missing")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "找不到"}}
    assert "retry-after" not in r.headers


def test_unexpected_error_is_internal_error(test_client):
    r = test_client.get("/api/v1/_test/boom")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": INTERNAL_MESSAGE}}
    assert "secret detail" not in r.text
    _assert_security_headers(r)


def test_security_headers_on_api_responses(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    _assert_security_headers(r)


def test_unknown_api_route_is_not_found(test_client):
    r = test_client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "找不到指定的 API"}}
    _assert_security_headers(r)


def test_wrong_method_is_method_invalid(test_client):
    r = test_client.post("/api/health")
    assert r.status_code == 405
    assert r.json() == {"error": {"code": "method_invalid", "message": "此 API 不支援這個請求方法"}}
    assert r.headers["allow"] == "GET"
    _assert_security_headers(r)


def test_other_http_exception_keeps_status(test_settings, db_engine):
    from fastapi import HTTPException

    app = create_app(test_settings)

    @app.get("/api/v1/_test/teapot")
    def teapot():
        raise HTTPException(418)

    with TestClient(app) as c:
        r = c.get("/api/v1/_test/teapot")
    assert r.status_code == 418
    assert r.json()["error"]["code"] == "http_error"
    _assert_security_headers(r)


def test_validation_error_is_payload_invalid_without_input(test_client):
    r = test_client.post("/api/v1/_test/typed", json={"quantity": "secret-value-123"})
    assert r.status_code == 422
    assert r.json() == {"error": {"code": "payload_invalid", "message": "請求內容格式不正確"}}
    assert "secret-value-123" not in r.text
    _assert_security_headers(r)


def test_ensure_passes_when_true():
    ensure(True, 422, "x", "y")
    with pytest.raises(Problem) as e:
        ensure(False, 422, "bad", "壞了")
    assert (e.value.status, e.value.code, e.value.message, e.value.retry_after_ms) == (
        422,
        "bad",
        "壞了",
        None,
    )


# ── canonical / digest ─────────────────────────────────────


def test_digest_is_key_order_independent():
    assert digest({"a": 1, "b": "中"}) == digest({"b": "中", "a": 1})


def test_canonical_json_format():
    assert canonical_json({"b": [1, {"d": 2, "c": "中"}], "a": None}) == (
        '{"a":null,"b":[1,{"c":"中","d":2}]}'
    )
    assert len(digest({})) == 64


# ── clock ─────────────────────────────────────────────────


def _problem(fn, *args, **kwargs) -> Problem:
    with pytest.raises(Problem) as e:
        fn(*args, **kwargs)
    return e.value


def test_parse_instant_rejects_rollover():
    p = _problem(parse_instant, "2026-02-30T00:00:00Z")
    assert (p.status, p.code) == (422, "office_time_invalid")


def test_parse_instant_minute_aligned():
    p = _problem(parse_instant, "2026-11-02T09:00:30+08:00", minute_aligned=True)
    assert (p.status, p.code) == (422, "office_time_invalid")
    assert parse_instant("2026-11-02T09:00:30+08:00") == datetime(2026, 11, 2, 1, 0, 30, tzinfo=UTC)
    assert parse_instant("2026-11-02T09:00:00.000+08:00", minute_aligned=True) == datetime(
        2026, 11, 2, 1, tzinfo=UTC
    )
    p = _problem(parse_instant, "2026-11-02T09:00:00.5+08:00", minute_aligned=True)
    assert p.code == "office_time_invalid"


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-02T09:00:00",  # 缺時區
        "2026-11-02 09:00:00Z",  # 缺 T
        "2026-11-02T24:00:00Z",
        "2026-11-02T09:60:00Z",
        "2026-11-02T09:00:60Z",
        "2026-11-02T09:00:00+14:01",
        "2026-11-02T09:00:00+15:00",
        "2026-11-02T09:00:00+08:60",
        "2026-11-02T09:00:00.1234Z",  # 小數最多三位
        "2026-13-01T00:00:00Z",
        "0000-01-01T00:00:00Z",
        "２０２６-11-02T09:00:00Z",  # 全形數字
        "2026-11-02T09:00:00Z\n",
        20261102,
    ],
)
def test_parse_instant_rejects_invalid(value):
    p = _problem(parse_instant, value)
    assert (p.status, p.code) == (422, "office_time_invalid")


def test_parse_instant_accepts_offsets_and_fraction():
    assert parse_instant("2026-11-02T00:00:00+14:00") == datetime(2026, 11, 1, 10, tzinfo=UTC)
    assert parse_instant("2026-11-02T00:00:00-14:00") == datetime(2026, 11, 2, 14, tzinfo=UTC)
    assert parse_instant("2026-11-02T00:00:00.12Z") == datetime(
        2026, 11, 2, 0, 0, 0, 120_000, tzinfo=UTC
    )
    assert parse_instant("2028-02-29T00:00:00Z").day == 29


def test_taipei_monday():
    assert taipei_monday("2026-11-02") == datetime(2026, 11, 2, tzinfo=clock.TAIPEI)
    assert taipei_monday("2026-11-02") == datetime(2026, 11, 1, 16, tzinfo=UTC)
    for bad in ["2026-11-03", "2026-02-30", "2026-11-2", "2026-11-02T00:00:00Z", None]:
        p = _problem(taipei_monday, bad)
        assert (p.status, p.code) == (422, "office_week_invalid"), bad


def test_iso_outputs_utc_milliseconds():
    dt = datetime(2026, 11, 2, 9, 0, 0, 123_456, tzinfo=clock.TAIPEI)
    assert iso(dt) == "2026-11-02T01:00:00.123Z"
    with pytest.raises(ValueError):
        iso(datetime(2026, 11, 2))


def test_utcnow_is_aware_and_patchable(monkeypatch):
    assert clock.utcnow().tzinfo is not None
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(clock, "utcnow", lambda: fixed)
    assert clock.utcnow() == fixed


# ── ids / money ───────────────────────────────────────────


def test_ids():
    a, b = new_id(), new_id()
    assert a != b and len(a) == 36 and a[14] == "4"
    t = token_hex(32)
    assert len(t) == 64 and all(c in "0123456789abcdef" for c in t)


def test_check_int():
    assert check_int(0) == 0
    assert check_int(1_000_000_000) == 1_000_000_000
    assert check_int(5.0) == 5
    assert check_int(3, min_=1) == 3
    for bad in [-1, 1_000_000_001, 1.5, True, "3", None, float("nan")]:
        p = _problem(check_int, bad)
        assert (p.status, p.code) == (422, "number_invalid"), bad
    p = _problem(check_int, 0, min_=1, code="office_number_invalid")
    assert p.code == "office_number_invalid"


# ── db ────────────────────────────────────────────────────


def test_make_engine_and_get_db(test_settings, test_client):
    engine = make_engine(test_settings)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
    r = test_client.get("/api/v1/_test/db")
    assert r.status_code == 200
    assert r.json() == {"one": 1}


def test_engine_hides_parameters_in_errors(test_settings, db_engine):
    """資料庫錯誤的訊息（會進日誌）不帶 SQL 參數值，避免 csrf、店名等內容外洩。

    PostgreSQL 自己的 DETAIL 仍會列出衝突的唯一鍵值（這裡是權杖的 sha256），不在此檢查範圍。
    """
    from sqlalchemy.exc import IntegrityError

    key = "f" * 64
    engine = make_engine(test_settings)
    try:
        insert = text(
            "INSERT INTO workspace_session (id, token_hash, csrf) "
            "VALUES (gen_random_uuid(), :token_hash, :csrf)"
        )
        with engine.begin() as conn:
            conn.execute(insert, {"token_hash": key, "csrf": "c" * 64})
        with pytest.raises(IntegrityError) as err, engine.begin() as conn:
            conn.execute(insert, {"token_hash": key, "csrf": "d" * 64})
    finally:
        engine.dispose()
    message = str(err.value)
    assert "hidden due to hide_parameters" in message
    assert "d" * 64 not in message


def test_format_sim() -> None:
    from src.core.money import format_sim

    assert format_sim(0) == "0.00 SIM"
    assert format_sim(123_450) == "1,234.50 SIM"
    assert format_sim(-5) == "-0.05 SIM"
