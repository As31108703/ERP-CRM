"""命令管線：session cookie、速率限制、Origin/CSRF、冪等收據、版本鎖、模組閘與回滾。"""

import json
import re
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import Engine, text

from src.core import clock
from src.core.problem import Problem
from src.platform import pipeline, ratelimit, registry
from src.platform.context import WorkspaceSessionRow
from tests.helpers import ApiClient, new_key

ECHO = "/api/v1/_test/echo"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _scalar(db_engine: Engine, sql: str, **params) -> object:
    with db_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _seed_workspace(db_engine: Engine, modules: list[str] | None = None) -> None:
    """直接在資料庫替唯一的 session 建立最小的工作區（不經 setup，因此沒有示範資料）。"""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workspace (id, session_id, generation_id, industry, company_name,"
                " modules, template_version) SELECT gen_random_uuid(), id, 'gen-test', 'general',"
                " '測試公司', :modules, 1 FROM workspace_session"
            ),
            {"modules": modules if modules is not None else ["inventory"]},
        )
        # 合法的工作區一定有三個系統錢包（wallets 模組的一致性檢查）
        conn.execute(
            text(
                "INSERT INTO wallet (id, workspace_id, kind, name) "
                "SELECT gen_random_uuid(), w.id, k, k FROM workspace w, "
                "unnest(ARRAY['business', 'supplier', 'faucet']) AS k"
            )
        )


def _raw_post(api: ApiClient, path: str, content: bytes, **header_overrides: str):
    state = api.state()
    headers = {
        "Origin": "http://testserver",
        "x-csrf-token": state["csrf"],
        "Idempotency-Key": new_key(),
        "If-Match-Version": str(state["version"]),
        "Content-Type": "application/json",
    }
    headers.update(header_overrides)
    return api.client.post(path, content=content, headers=headers)


# --- session cookie -----------------------------------------------------------


def _set_cookie(r) -> str:
    cookies = [v for k, v in r.headers.multi_items() if k == "set-cookie"]
    assert len(cookies) == 1, cookies
    return cookies[0]


def test_cookie_attributes(client, make_client):
    r = client.get("/api/v1/_test/csrf")
    cookie = _set_cookie(r)
    assert re.match(r"^erpcrm_session=[0-9a-f]{64};", cookie)
    attrs = [a.strip() for a in cookie.split(";")]
    assert "HttpOnly" in attrs
    assert "SameSite=Strict" in attrs
    assert "Path=/" in attrs
    assert "Max-Age=31536000" in attrs
    assert "Secure" not in attrs

    demo = make_client(public_demo=True)
    attrs = [a.strip() for a in _set_cookie(demo.get("/api/v1/_test/csrf")).split(";")]
    assert "Max-Age=259200" in attrs

    https = make_client()
    r = https.get("/api/v1/_test/csrf", headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in [a.strip() for a in _set_cookie(r).split(";")]


def test_cookie_keeps_token_and_stores_only_hash(client, db_engine):
    r1 = client.get("/api/v1/_test/csrf")
    token = r1.cookies["erpcrm_session"]
    r2 = client.get("/api/v1/_test/csrf")
    assert r2.cookies["erpcrm_session"] == token
    assert r1.json()["csrf"] == r2.json()["csrf"]
    assert _scalar(db_engine, "SELECT count(*) FROM workspace_session") == 1
    stored = _scalar(db_engine, "SELECT token_hash FROM workspace_session")
    assert stored != token
    assert re.fullmatch(r"[0-9a-f]{64}", stored)


def test_malformed_cookie_gets_new_session(client):
    client.cookies.set("erpcrm_session", "not-a-token")
    r = client.get("/api/v1/_test/csrf")
    assert re.fullmatch(r"[0-9a-f]{64}", r.cookies["erpcrm_session"])


@pytest.mark.parametrize("sibling", ['x={"k":1}', "x=a b", 'x="unterminated', "x=\\bad"])
def test_malformed_sibling_cookie_keeps_session(client, sibling):
    # 其他網站寫入的非 RFC 嚴格 cookie 不能讓 session 遺失，否則工作區消失且寫入一律 csrf_invalid
    first = client.get("/api/v1/_test/csrf")
    token = first.cookies["erpcrm_session"]
    client.cookies.clear()
    header = {"Cookie": f"{sibling}; erpcrm_session={token}"}
    again = client.get("/api/v1/_test/csrf", headers=header)
    assert again.status_code == 200
    assert f"erpcrm_session={token};" in _set_cookie(again)
    assert again.json()["csrf"] == first.json()["csrf"]
    client.cookies.clear()
    state = again.json()
    r = client.post(
        ECHO,
        json={},
        headers={
            **header,
            "Origin": "http://testserver",
            "x-csrf-token": state["csrf"],
            "Idempotency-Key": new_key(),
            "If-Match-Version": str(state["version"]),
        },
    )
    assert r.status_code == 200, r.text


def test_csp_header_on_api_responses(client):
    r = client.get("/api/v1/_test/csrf")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


# --- 依序的前置檢查 -------------------------------------------------------------


def test_missing_csrf_403(api):
    r = api.mutate("POST", ECHO, {}, csrf="")
    assert _error(r) == (403, "csrf_invalid")
    r = api.mutate("POST", ECHO, {}, csrf="0" * 64)
    assert _error(r) == (403, "csrf_invalid")


def test_bad_origin_403(api):
    r = api.mutate("POST", ECHO, {}, origin="http://evil.example")
    assert _error(r) == (403, "origin_invalid")
    state = api.state()
    r = api.client.post(
        ECHO,
        json={},
        headers={
            "x-csrf-token": state["csrf"],
            "Idempotency-Key": new_key(),
            "If-Match-Version": str(state["version"]),
        },
    )
    assert _error(r) == (403, "origin_invalid")


def test_origin_uses_forwarded_headers(api):
    r = _raw_post(
        api,
        ECHO,
        b"{}",
        Origin="https://erp.example",
        **{"X-Forwarded-Proto": "https", "X-Forwarded-Host": "erp.example"},
    )
    assert r.status_code == 200, r.text


def test_forwarded_https_origin_and_secure_cookie(api):
    """前端 nginx 前面還有 TLS 代理時：沿用其 X-Forwarded-*，不設 ALLOWED_ORIGINS 也能寫入，
    且 cookie 帶 Secure。"""
    forwarded = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "h"}
    r = _raw_post(api, ECHO, b"{}", Origin="https://h", **forwarded)
    assert r.status_code == 200, r.text
    assert "Secure" in [a.strip() for a in _set_cookie(r).split(";")]


def test_origin_allow_list(make_client):
    api = ApiClient(make_client(allowed_origins=["https://ok.example"]))
    assert _error(api.mutate("POST", ECHO, {})) == (403, "origin_invalid")
    assert api.mutate("POST", ECHO, {}, origin="https://ok.example").status_code == 200


@pytest.mark.parametrize(
    "key", [None, "short", "has space!", "x" * 101, "ｋｅｙ１２３４５６７８".encode()]
)
def test_missing_key_422_key_required(api, key):
    state = api.state()
    headers = {
        "Origin": "http://testserver",
        "x-csrf-token": state["csrf"],
        "If-Match-Version": str(state["version"]),
    }
    if key is not None:
        headers["Idempotency-Key"] = key
    r = api.client.post(ECHO, json={}, headers=headers)
    assert _error(r) == (422, "key_required")


@pytest.mark.parametrize("version", [None, "", "abc", "-1", "1.0", "１".encode()])
def test_missing_version_428(api, version):
    state = api.state()
    headers = {
        "Origin": "http://testserver",
        "x-csrf-token": state["csrf"],
        "Idempotency-Key": new_key(),
    }
    if version is not None:
        headers["If-Match-Version"] = version
    r = api.client.post(ECHO, json={}, headers=headers)
    assert _error(r) == (428, "version_required")


def test_body_over_32k_413(api):
    body = json.dumps({"note": "x" * 32_768}).encode()
    assert _error(_raw_post(api, ECHO, body)) == (413, "body_limit")
    # 恰好 32 768 bytes 仍可接受
    pad = 32_768 - len(json.dumps({"note": ""}).encode())
    exact = json.dumps({"note": "x" * pad}).encode()
    assert len(exact) == 32_768
    assert _raw_post(api, ECHO, exact).status_code == 200


@pytest.mark.parametrize("content", [b"", b"{", b"\xff\xfe", b"NaN", b'{"a": Infinity}'])
def test_invalid_json_422(api, content):
    assert _error(_raw_post(api, ECHO, content)) == (422, "json_invalid")


@pytest.mark.parametrize("content", [b"[1, 2]", b'"text"', b"null"])
def test_non_object_body_422_payload_invalid(api, content):
    assert _error(_raw_post(api, ECHO, content)) == (422, "payload_invalid")


# --- 冪等與版本鎖 ---------------------------------------------------------------


def test_success_response_shape(api):
    state = api.state()
    r = api.mutate("POST", ECHO, {"a": 1})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["result"] == "ok"
    assert data["replayed"] is False
    assert data["version"] == state["version"] + 1
    assert data["csrf"] == state["csrf"]
    receipt = data["receipt"]
    assert receipt["action"] == "test.echo"
    assert receipt["expected_version"] == state["version"]
    assert receipt["version"] == data["version"]
    assert receipt["result"] == "ok"
    assert receipt["simulation"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["hash"])
    assert receipt["created_at"].endswith("Z")


def test_replay_same_body_returns_replayed(api, db_engine):
    key = new_key()
    first = api.mutate("POST", ECHO, {"a": 1}, key=key, version=0)
    assert first.status_code == 200, first.text
    second = api.mutate("POST", ECHO, {"a": 1}, key=key, version=0)
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["receipt"] == first.json()["receipt"]
    assert second.json()["result"] == "ok"
    assert api.state()["version"] == 1
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 1


def test_replay_checked_before_version(api):
    # 前端重送待確認的操作時，會帶原本的 If-Match-Version；此時版本已前進，仍要回重播結果
    key = new_key()
    assert api.mutate("POST", ECHO, {}, key=key, version=0).status_code == 200
    assert api.mutate("POST", ECHO, {}, version=1).status_code == 200
    r = api.mutate("POST", ECHO, {}, key=key, version=0)
    assert r.status_code == 200, r.text
    assert r.json()["replayed"] is True
    assert r.json()["version"] == 2


def test_replay_different_body_409(api):
    key = new_key()
    assert api.mutate("POST", ECHO, {"a": 1}, key=key, version=0).status_code == 200
    r = api.mutate("POST", ECHO, {"a": 2}, key=key, version=0)
    assert _error(r) == (409, "idempotency_conflict")
    # 同 body 但不同路徑或不同預期版本，也算衝突
    assert _error(api.mutate("POST", "/api/v1/_test/prune", {"a": 1}, key=key, version=0)) == (
        409,
        "idempotency_conflict",
    )
    assert _error(api.mutate("POST", ECHO, {"a": 1}, key=key, version=1)) == (
        409,
        "idempotency_conflict",
    )


def test_stale_version_412(api, db_engine):
    assert api.mutate("POST", ECHO, {}, version=0).status_code == 200
    r = api.mutate("POST", ECHO, {}, version=0)
    assert _error(r) == (412, "version_stale")
    assert _error(api.mutate("POST", ECHO, {}, version=5)) == (412, "version_stale")
    assert api.state()["version"] == 1
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 1


# --- 速率限制 -----------------------------------------------------------------


def test_rate_limit_120_per_minute(api, monkeypatch):
    # 固定時鐘：120 個請求都落在同一個視窗，retry_after_ms 必為 start + 60001 - now = 60001
    t0 = clock.utcnow()
    monkeypatch.setattr(clock, "utcnow", lambda: t0)
    # GET 也計入：1 次 state + 59 次 GET + 60 次寫入 = 120
    state = api.state()
    for _ in range(59):
        assert api.client.get("/api/v1/_test/csrf").status_code == 200
    for i in range(60):
        r = api.mutate("POST", ECHO, {}, csrf=state["csrf"], version=state["version"] + i)
        assert r.status_code == 200, (i, r.text)
    r = api.mutate("POST", ECHO, {}, csrf=state["csrf"], version=state["version"] + 60)
    assert _error(r) == (429, "rate_limit")
    assert r.json()["error"]["retry_after_ms"] == 60_001
    assert r.headers["retry-after"] == "61"
    assert _error(api.client.get("/api/v1/_test/csrf")) == (429, "rate_limit")


def test_rate_limit_retry_never_exceeds_window():
    """視窗起點晚於 now（並行請求先取得鎖並開了新視窗）時，retry_after_ms 仍不超過 60001。"""
    now = clock.utcnow()
    row = WorkspaceSessionRow(
        token_hash="x", csrf="x", rate_start=now + timedelta(milliseconds=1480), rate_count=120
    )
    with pytest.raises(Problem) as e:
        ratelimit.hit(row, now)
    assert (e.value.code, e.value.retry_after_ms) == ("rate_limit", 60_001)


def test_touch_session_reads_clock_after_lock(api, monkeypatch, db_engine):
    """GET 的速率計數與最後存取時間用取得 session 列鎖之後的時間，不是排隊前讀到的時間。"""
    api.state()
    ticks = iter(range(1, 1000))
    t0 = clock.utcnow()
    lock_tick: list[int] = []
    current = [0]

    def fake_now():
        current[0] = next(ticks)
        return t0 + timedelta(seconds=current[0])

    real_lock = pipeline.lock_session

    def tracking_lock(db, token, now):
        row = real_lock(db, token, now)
        lock_tick.append(current[0])
        return row

    monkeypatch.setattr(clock, "utcnow", fake_now)
    monkeypatch.setattr(pipeline, "lock_session", tracking_lock)
    assert api.client.get("/api/v1/_test/csrf").status_code == 200
    with db_engine.connect() as conn:
        seen = conn.execute(text("SELECT last_seen_at FROM workspace_session")).scalar_one()
    assert seen > t0 + timedelta(seconds=lock_tick[-1])


def test_rate_limit_counts_failed_writes_and_resets(api, monkeypatch):
    t0 = clock.utcnow()
    monkeypatch.setattr(clock, "utcnow", lambda: t0)
    state = api.state()
    for _ in range(119):
        assert _error(api.mutate("POST", ECHO, {}, csrf="bad", version=0)) == (403, "csrf_invalid")
    assert _error(api.mutate("POST", ECHO, {}, csrf=state["csrf"], version=0)) == (
        429,
        "rate_limit",
    )
    # 視窗開始後 59.999 秒仍在同一視窗：retry_after_ms = start + 60001 - now = 2
    monkeypatch.setattr(clock, "utcnow", lambda: t0 + timedelta(milliseconds=59_999))
    r = api.client.get("/api/v1/_test/csrf")
    assert _error(r) == (429, "rate_limit")
    assert r.json()["error"]["retry_after_ms"] == 2
    monkeypatch.setattr(clock, "utcnow", lambda: t0 + timedelta(seconds=60))
    assert api.client.get("/api/v1/_test/csrf").status_code == 200


# --- 回滾、收據上限、工作區與模組閘 -----------------------------------------------


def test_failed_handler_rolls_back(api, db_engine):
    api.state()
    _seed_workspace(db_engine)
    before = api.state()["version"]
    r = api.mutate("POST", "/api/v1/_test/boom", {})
    assert _error(r) == (422, "test_boom")
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 0
    assert api.state()["version"] == before


def test_command_writes_history(api, db_engine):
    api.state()
    _seed_workspace(db_engine)
    r = api.mutate("POST", "/api/v1/_test/command", {})
    assert r.status_code == 200, r.text
    row = None
    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT action, result, version FROM history")).one()
    assert tuple(row) == ("test.command", "ok", 1)


def test_echo_without_workspace_writes_no_history(api, db_engine):
    assert api.mutate("POST", ECHO, {}).status_code == 200
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 0


def test_workspace_missing_409(api):
    assert _error(api.mutate("POST", "/api/v1/_test/command", {})) == (409, "workspace_missing")


def test_module_gate_403(api, db_engine):
    api.state()
    _seed_workspace(db_engine, ["inventory", "wallets"])
    assert api.mutate("POST", "/api/v1/_test/module/inventory", {}).status_code == 200
    r = api.mutate("POST", "/api/v1/_test/module/sales", {})
    assert _error(r) == (403, "module_disabled")


def test_invariant_failure_rolls_back(api, db_engine, monkeypatch):
    def broken(_db, workspace_id: str) -> None:
        assert workspace_id
        raise Problem(422, "invariant_failed", "測試一致性錯誤")

    spec = registry.ModuleSpec(
        name="test-invariant",
        snapshot=lambda _db, _wid: {},
        restore=lambda _db, _wid, _data: None,
        invariants=(broken,),
    )
    monkeypatch.setattr(registry, "_SPECS", {})
    registry.register(spec)
    api.state()
    _seed_workspace(db_engine)
    r = api.mutate("POST", "/api/v1/_test/command", {})
    assert _error(r) == (422, "invariant_failed")
    assert api.state()["version"] == 0
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 0


def test_receipt_cap_500(api, db_engine):
    api.state()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO receipt (session_id, key, hash, expected_version, version, action)"
                " SELECT s.id, 'seed-key-' || g, repeat('0', 64), 0, 0, 'seed'"
                " FROM workspace_session s, generate_series(1, 500) g"
            )
        )
    r = api.mutate("POST", ECHO, {})
    assert _error(r) == (429, "receipt_limit")
    r = api.mutate("POST", "/api/v1/_test/prune", {})
    assert r.status_code == 200, r.text
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 101
    # 保留的是最近 100 筆（seed 401..500）加上新的一筆
    assert _scalar(db_engine, "SELECT count(*) FROM receipt WHERE key = 'seed-key-400'") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM receipt WHERE key = 'seed-key-401'") == 1
    assert api.mutate("POST", ECHO, {}).status_code == 200


def test_prune_below_cap_keeps_receipts(api, db_engine):
    for _ in range(3):
        assert api.mutate("POST", "/api/v1/_test/prune", {}).status_code == 200
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 3


def test_concurrent_same_version(api, db_engine):
    """Review Focus 1：兩個分頁同時以同一版本送出，一筆成功、一筆 412，沒有部分寫入。"""
    state = api.state()
    _seed_workspace(db_engine)
    barrier = threading.Barrier(2)
    results: list[int] = []
    elapsed: dict[int, float] = {}
    errors: list[BaseException] = []

    def send() -> None:
        try:
            barrier.wait(timeout=5)
            started = time.monotonic()
            r = api.mutate(
                "POST", "/api/v1/_test/slow", {}, csrf=state["csrf"], version=state["version"]
            )
            elapsed[r.status_code] = time.monotonic() - started
            results.append(r.status_code)
            if r.status_code != 200:
                assert r.json()["error"]["code"] == "version_stale"
        except BaseException as exc:  # 轉交主執行緒斷言
            errors.append(exc)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, errors
    assert sorted(results) == [200, 412]
    # 兩個請求確實重疊：失敗的那筆是在鎖上等到成功的那筆提交（handler 持鎖 0.3 秒）才被判定過期
    assert elapsed[412] >= 0.2, elapsed
    assert api.state()["version"] == state["version"] + 1
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 1
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 1


# --- registry -----------------------------------------------------------------


def test_registry_constants_and_register(monkeypatch):
    assert registry.MODULES == (
        "inventory",
        "sales",
        "wallets",
        "services",
        "crm",
        "projects",
        "manufacturing",
        "administration",
    )
    assert registry.MODULE_DEPENDENCIES == {
        "sales": ["inventory", "wallets"],
        "services": ["crm", "wallets"],
        "manufacturing": ["inventory", "wallets"],
    }
    monkeypatch.setattr(registry, "_SPECS", {})
    a = registry.ModuleSpec("a", lambda _d, _w: {}, lambda _d, _w, _x: None)
    b = registry.ModuleSpec("b", lambda _d, _w: {}, lambda _d, _w, _x: None)
    registry.register(a)
    registry.register(b)
    registry.register(a)  # 重複註冊同名模組會取代，不會重複
    assert [s.name for s in registry.all_specs()] == ["a", "b"]


@pytest.mark.parametrize(
    "names",
    [
        ["sales", "crm", "inventory", "wallets", "zeta"],
        ["zeta", "administration", "projects", "manufacturing", "services", "wallets"],
        ["crm", "wallets", "alpha", "sales", "zeta", "inventory"],
    ],
)
def test_all_specs_order_independent_of_import(monkeypatch, names):
    """不論模組匯入（登錄）先後，快照、一致性檢查與還原都依固定的模組順序；
    不在固定清單中的模組排在最後，彼此維持登錄順序。"""
    monkeypatch.setattr(registry, "_SPECS", {})
    for name in names:
        registry.register(registry.ModuleSpec(name, lambda _d, _w: {}, lambda _d, _w, _x: None))
    fixed = [n for n in registry.SPEC_ORDER if n in names]
    others = [n for n in names if n not in registry.SPEC_ORDER]
    assert [s.name for s in registry.all_specs()] == fixed + others
    assert registry.SPEC_ORDER == (
        "inventory",
        "wallets",
        "sales",
        "crm",
        "services",
        "manufacturing",
        "projects",
        "administration",
    )


def test_final_invariants_run_after_all_module_invariants(api, db_engine, monkeypatch):
    """最終檢查在所有模組的 invariants 之後依 FINAL_ORDER 執行，與登錄先後無關；
    檢查時版本號已加 1、本次 history 已寫入（與參考系統先記錄再驗證的順序一致）。"""
    calls: list[str] = []

    def record(name: str):
        def check(db, workspace_id: str) -> None:
            assert workspace_id
            calls.append(name)

        return check

    def versioned(db, workspace_id: str) -> None:
        version = db.execute(text("SELECT version FROM workspace_session")).scalar_one()
        history = db.execute(text("SELECT count(*) FROM history")).scalar_one()
        calls.append(f"version={version},history={history}")

    monkeypatch.setattr(registry, "_SPECS", {})
    monkeypatch.setattr(registry, "_FINALS", {})
    monkeypatch.setattr(registry, "FINAL_ORDER", ("second", "first", "last"))
    registry.register_final("last", versioned)
    registry.register_final("first", record("final-first"))
    registry.register_final("second", record("final-second"))
    registry.register_final("extra", record("final-extra"))
    for name in ("zeta", "inventory"):
        registry.register(
            registry.ModuleSpec(
                name,
                lambda _d, _w: {},
                lambda _d, _w, _x: None,
                invariants=(record(name),),
            )
        )
    api.state()
    _seed_workspace(db_engine)
    assert api.mutate("POST", "/api/v1/_test/command", {}).status_code == 200
    assert calls == [
        "inventory",
        "zeta",
        "final-second",
        "final-first",
        "version=1,history=1",
        "final-extra",
    ]


def test_final_invariant_failure_rolls_back(api, db_engine, monkeypatch):
    def broken(_db, _workspace_id: str) -> None:
        raise Problem(422, "invariant_failed", "測試一致性錯誤")

    monkeypatch.setattr(registry, "_SPECS", {})
    monkeypatch.setattr(registry, "_FINALS", {})
    registry.register_final("broken", broken)
    api.state()
    _seed_workspace(db_engine)
    assert _error(api.mutate("POST", "/api/v1/_test/command", {})) == (422, "invariant_failed")
    assert api.state()["version"] == 0
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 0


def test_final_order_constant():
    assert registry.FINAL_ORDER == ("reservations", "workspace_limit")
    assert set(registry._FINALS) == {"reservations", "workspace_limit"}
