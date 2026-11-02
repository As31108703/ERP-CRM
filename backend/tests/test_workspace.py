"""範本目錄與工作區：建立、檢視、清除、收據查詢、自動建立與 72 小時保留。"""

from datetime import timedelta

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.app import create_app
from src.core import clock
from src.core.problem import Problem
from src.modules.catalog import seed
from src.modules.catalog.templates import TEMPLATES
from src.modules.workspace import service as ws_service
from src.modules.workspace.retention import purge_abandoned, purge_expired, run_purge
from src.platform import registry
from src.platform.pipeline import IMPORT_BODY_LIMIT
from src.platform.registry import MODULES
from tests.helpers import ApiClient, new_key, workspace_ctx

SETUP = "/api/v1/workspace/setup"
CLEAR = "/api/v1/workspace/clear"
ALL_MODULES = list(MODULES)


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _scalar(db_engine: Engine, sql: str, **params) -> object:
    with db_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


# --- 範本目錄 -------------------------------------------------------------------


def test_templates_lists_eight(api: ApiClient) -> None:
    r = api.get("/api/templates")
    assert r.status_code == 200
    body = r.json()
    items = {t["id"]: t for t in body["items"]}
    assert list(items) == [
        "retail",
        "wholesale",
        "service",
        "restaurant",
        "manufacturing",
        "ecommerce",
        "projects",
        "general",
    ]
    general = items["general"]
    assert general["modules"] == ALL_MODULES
    assert general["version"] == 2
    assert general["name"] == "一般企業"
    assert all(t["version"] == 1 for k, t in items.items() if k != "general")
    assert general["default_config"] == {
        "currency": "SIM",
        "simulation": True,
        "real_finance": False,
    }
    assert general["module_dependencies"]["sales"] == ["inventory", "wallets"]
    assert items["retail"]["sample"] == {
        "sku": "SHOP-MUG-001",
        "product": "示範陶瓷杯",
        "customer": "社區顧客林小姐",
        "service": "商品客製服務",
        "component": "杯體材料",
        "price_minor": 35000,
        "cost_minor": 16000,
    }
    assert items["manufacturing"]["sample"]["bom_quantity"] == 2
    assert items["projects"]["sample"]["milestone"] == "原型驗收"
    assert items["restaurant"]["terminology"] == {
        "customer": "用餐顧客",
        "product": "餐點",
        "work_order": "餐點製作單",
    }
    assert body["defaults"] == {
        "industry": "retail",
        "company_name": "星軌示範商店",
        "modules": None,
        "public_demo": False,
        "auto_setup": False,
        "retention_hours": None,
    }


def test_templates_defaults_public_demo(make_client) -> None:
    c = make_client(public_demo=True, auto_setup=True, default_modules=["inventory", "nope"])
    defaults = c.get("/api/templates").json()["defaults"]
    assert defaults["public_demo"] is True
    assert defaults["auto_setup"] is False
    assert defaults["retention_hours"] == 72
    assert defaults["modules"] == ["inventory"]


# --- 建立 -----------------------------------------------------------------------


def test_setup_rejects_missing_dependency(api: ApiClient) -> None:
    r = api.mutate(
        "POST", SETUP, {"industry": "general", "company_name": "甲", "modules": ["sales"]}
    )
    assert _error(r) == (422, "module_dependency")
    assert r.json()["error"]["message"] == "sales 需要 inventory、wallets"
    assert api.view()["workspace"] is None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"industry": "nope", "company_name": "甲"}, "industry_invalid"),
        ({"industry": 1, "company_name": "甲"}, "industry_invalid"),
        ({"industry": "retail", "company_name": "   "}, "name_invalid"),
        ({"industry": "retail", "company_name": "甲" * 101}, "name_invalid"),
        ({"industry": "retail"}, "name_invalid"),
        ({"industry": "retail", "company_name": "甲", "modules": ["nope"]}, "module_invalid"),
        (
            {"industry": "retail", "company_name": "甲", "modules": ["crm", "crm"]},
            "module_invalid",
        ),
        ({"industry": "retail", "company_name": "甲", "modules": "crm"}, "module_invalid"),
    ],
)
def test_setup_validation(api: ApiClient, body: dict, code: str) -> None:
    r = api.mutate("POST", SETUP, body)
    assert _error(r) == (422, code)
    assert api.state()["version"] == 0


def test_setup_twice_409(api: ApiClient) -> None:
    api.setup()
    r = api.mutate("POST", SETUP, {"industry": "retail", "company_name": "乙"})
    assert _error(r) == (409, "workspace_exists")
    assert api.view()["version"] == 1


def test_view_without_workspace(api: ApiClient) -> None:
    body = api.view()
    assert body["workspace"] is None
    assert len(body["csrf"]) == 64
    assert body["version"] == 0
    assert body["retention_hours"] is None
    assert body["expires_at"] is None
    assert body["report"] is None


def test_setup_then_view(api: ApiClient) -> None:
    res = api.setup("restaurant", "  星軌餐館  ")
    generation_id = res["result"]
    assert res["version"] == 1
    assert res["receipt"]["action"] == "workspace.setup"

    body = api.view()
    assert body["version"] == 1
    ws = body["workspace"]
    meta = {
        k: ws[k]
        for k in (
            "generation_id",
            "version",
            "industry",
            "company_name",
            "modules",
            "template_version",
            "schema_version",
            "currency",
            "simulation",
            "real_finance",
        )
    }
    assert meta == {
        "generation_id": generation_id,
        "version": 1,
        "industry": "restaurant",
        "company_name": "星軌餐館",
        "modules": TEMPLATES["restaurant"].modules,
        "template_version": 1,
        "schema_version": 1,
        "currency": "SIM",
        "simulation": True,
        "real_finance": False,
    }
    # setup 不寫 history
    assert ws["history"] == []


def test_setup_custom_modules(api: ApiClient) -> None:
    api.setup("general", "甲", ["crm", "projects"])
    assert api.snapshot()["modules"] == ["crm", "projects"]
    assert api.snapshot()["template_version"] == 2


def test_view_public_demo_expires(make_client) -> None:
    api = ApiClient(make_client(public_demo=True))
    before = clock.utcnow()
    body = api.view()
    assert body["retention_hours"] == 72
    expires = clock.parse_instant(body["expires_at"])
    assert (
        timedelta(hours=72) - timedelta(seconds=5)
        <= expires - before
        <= timedelta(hours=72, seconds=5)
    )


def test_history_sorted_by_version(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    with db_engine.begin() as conn:
        for v in (3, 2):
            conn.execute(
                text(
                    "INSERT INTO history (workspace_id, action, result, version)"
                    " SELECT id, 'test.x', NULL, :v FROM workspace"
                ),
                {"v": v},
            )
    assert [h["version"] for h in api.snapshot()["history"]] == [2, 3]


# --- 清除 -----------------------------------------------------------------------


def test_clear_rotates_csrf(api: ApiClient) -> None:
    api.setup()
    old = api.state()["csrf"]
    res = api.ok("POST", CLEAR, {})
    assert res["result"] is None
    assert res["version"] == 2
    assert res["csrf"] != old
    body = api.view()
    assert body["workspace"] is None
    assert body["csrf"] == res["csrf"]
    # 舊的 csrf 不能再用
    r = api.mutate("POST", SETUP, {"industry": "retail", "company_name": "甲"}, csrf=old, version=2)
    assert _error(r) == (403, "csrf_invalid")
    # 清除後可重新建立
    assert api.setup()["version"] == 3


def test_clear_removes_history(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO history (workspace_id, action, version)"
                " SELECT id, 'x', 2 FROM workspace"
            )
        )
    api.ok("POST", CLEAR, {})
    assert _scalar(db_engine, "SELECT count(*) FROM history") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 0


def test_setup_and_clear_bypass_receipt_cap(api: ApiClient, db_engine: Engine) -> None:
    api.state()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO receipt (session_id, key, hash, expected_version, version, action)"
                " SELECT s.id, 'k' || lpad(g::text, 8, '0'), repeat('0', 64), 0, 0, 'x'"
                " FROM workspace_session s, generate_series(1, 500) g"
            )
        )
    api.setup()
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 101
    api.ok("POST", CLEAR, {})
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 102


# --- 收據 -----------------------------------------------------------------------


def test_receipt_lookup(api: ApiClient) -> None:
    key = new_key()
    r = api.mutate("POST", SETUP, {"industry": "retail", "company_name": "甲"}, key=key)
    assert r.status_code == 200
    got = api.get(f"/api/v1/workspace/receipts/{key}")
    assert got.status_code == 200
    receipt = got.json()["receipt"]
    assert receipt == r.json()["receipt"]
    assert receipt["id"] == key
    assert receipt["result"] == r.json()["result"]

    missing = api.get(f"/api/v1/workspace/receipts/{new_key()}")
    assert _error(missing) == (404, "receipt_missing")


# --- 自動建立 -------------------------------------------------------------------


def test_auto_setup(make_client) -> None:
    api = ApiClient(make_client(auto_setup=True))
    body = api.view()
    assert body["version"] == 1
    ws = body["workspace"]
    assert ws["industry"] == "retail"
    assert ws["company_name"] == "星軌示範商店"
    assert ws["modules"] == TEMPLATES["retail"].modules
    # 第二次檢視不會重建
    assert api.view()["workspace"]["generation_id"] == ws["generation_id"]
    # 清除後不再自動建立
    api.ok("POST", CLEAR, {})
    assert api.view()["workspace"] is None


def test_auto_setup_uses_default_modules(make_client) -> None:
    c = make_client(auto_setup=True, default_industry="general", default_modules=["crm"])
    assert ApiClient(c).snapshot()["modules"] == ["crm"]


def test_auto_setup_skipped_in_public_demo(make_client) -> None:
    api = ApiClient(make_client(auto_setup=True, public_demo=True))
    body = api.view()
    assert body["workspace"] is None
    assert body["version"] == 0


# --- 種子資料 -------------------------------------------------------------------


def _without_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """只留測試用的 seed：同時移除模組登錄，否則缺少系統錢包會被一致性檢查擋下。"""
    monkeypatch.setattr(seed, "_SEEDERS", {})
    monkeypatch.setattr(registry, "_SPECS", {})


def test_seed_extension_point(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], str]] = []

    def fake_seed(ctx, template) -> None:
        assert ctx.workspace is not None
        calls.append((template.id, list(ctx.workspace.modules), ctx.workspace.company_name))

    _without_modules(monkeypatch)
    seed.register_seeder("test", fake_seed, order=10)
    api.setup("service", "甲")
    assert calls == [("service", TEMPLATES["service"].modules, "甲")]


def test_seeders_run_in_explicit_order(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """執行順序只看 order，與註冊（匯入）順序無關；同名重複註冊時取代原本的設定。"""
    calls: list[str] = []

    def make(name: str):
        return lambda ctx, template: calls.append(name)

    _without_modules(monkeypatch)
    seed.register_seeder("bom", make("bom"), order=50)
    seed.register_seeder("customer", make("customer"), order=30)
    seed.register_seeder("wallets", make("wallets"), order=10)
    seed.register_seeder("products", make("old-products"), order=99)
    seed.register_seeder("products", make("products"), order=20)
    api.setup("general", "甲")
    assert calls == ["wallets", "products", "customer", "bom"]


def test_seeder_order_must_be_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "_SEEDERS", {})
    seed.register_seeder("a", lambda ctx, t: None, order=10)
    with pytest.raises(ValueError):
        seed.register_seeder("b", lambda ctx, t: None, order=10)


def test_seed_contents_per_template(api: ApiClient) -> None:
    api.setup("manufacturing", "甲")
    ws = api.snapshot()
    assert len(ws["products"]) == 2
    assert len(ws["boms"]) == 1


# --- 保留 -----------------------------------------------------------------------


def test_purge_expired_public_demo(make_client, db_engine: Engine) -> None:
    api = ApiClient(make_client(public_demo=True))
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE workspace_session SET last_seen_at = now() - interval '73 hours'")
        )
    with Session(db_engine) as db:
        assert purge_expired(db, clock.utcnow()) == 1
        db.commit()
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM workspace_session") == 0
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 0


def test_purge_keeps_recent(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE workspace_session SET last_seen_at = now() - interval '71 hours'")
        )
    assert run_purge(db_engine, clock.utcnow(), public_demo=True) == 0
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 1


def test_run_purge_skips_when_locked(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE workspace_session SET last_seen_at = now() - interval '73 hours'")
        )
    with db_engine.connect() as holder:
        assert holder.execute(text("SELECT pg_try_advisory_lock(7310)")).scalar_one()
        try:
            assert run_purge(db_engine, clock.utcnow(), public_demo=True) == 0
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(7310)"))
            holder.commit()
    assert run_purge(db_engine, clock.utcnow(), public_demo=True) == 1


def _insert_session(db_engine: Engine, *, version: int, hours_ago: int) -> str:
    """直接建立一筆 session（沒有工作區），回傳 id。"""
    with db_engine.begin() as conn:
        return str(
            conn.execute(
                text(
                    "INSERT INTO workspace_session (id, token_hash, csrf, version, last_seen_at)"
                    " VALUES (gen_random_uuid(), md5(random()::text), 'csrf', :version,"
                    " now() - make_interval(hours => :hours)) RETURNING id"
                ),
                {"version": version, "hours": hours_ago},
            ).scalar_one()
        )


def test_purge_abandoned_sessions(api: ApiClient, db_engine: Engine) -> None:
    """沒有 cookie 的請求也會建立 session；從未寫入（版本 0、無工作區）且 24 小時沒存取的就清掉。"""
    stale = _insert_session(db_engine, version=0, hours_ago=25)
    _insert_session(db_engine, version=0, hours_ago=23)
    # 清除過工作區的 session 版本已大於 0，保留（自架模式資料永久保留）
    _insert_session(db_engine, version=2, hours_ago=25)
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE workspace_session SET last_seen_at = now() - interval '25 hours'"
                " WHERE id IN (SELECT session_id FROM workspace)"
            )
        )
    with Session(db_engine) as db:
        assert purge_abandoned(db, clock.utcnow()) == 1
        db.commit()
    ids = _scalar(db_engine, "SELECT array_agg(id::text) FROM workspace_session")
    assert stale not in ids
    assert len(ids) == 3
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 1


def test_run_purge_private_mode_keeps_workspaces(api: ApiClient, db_engine: Engine) -> None:
    """自架模式只清從未寫入的 session，72 小時沒存取的工作區仍保留。"""
    _insert_session(db_engine, version=0, hours_ago=25)
    api.setup()
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE workspace_session SET last_seen_at = now() - interval '73 hours'")
        )
    assert run_purge(db_engine, clock.utcnow(), public_demo=False) == 1
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 1
    assert _scalar(db_engine, "SELECT count(*) FROM workspace_session") == 1
    assert run_purge(db_engine, clock.utcnow(), public_demo=True) == 1
    assert _scalar(db_engine, "SELECT count(*) FROM workspace") == 0


@pytest.mark.parametrize("public_demo", [True, False])
def test_scheduler_runs_in_both_modes(make_client, public_demo: bool) -> None:
    c = make_client(public_demo=public_demo)
    jobs = c.app.state.scheduler.get_jobs()
    assert [j.id for j in jobs] == ["retention_purge"]
    assert jobs[0].trigger.interval == timedelta(minutes=10)
    assert jobs[0].kwargs == {"public_demo": public_demo}


# --- 啟動時檢查自動建立的預設值 -------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"default_industry": "moon"}, "industry_invalid"),
        ({"default_company": "   "}, "name_invalid"),
        ({"default_company": "祕密\u0007店"}, "name_invalid"),
        ({"default_company": "x" * 101}, "name_invalid"),
        ({"default_modules": []}, "module_invalid"),
        ({"default_modules": ["moon"]}, "module_invalid"),
        ({"default_modules": ["sales"]}, "module_dependency"),
    ],
)
def test_invalid_auto_setup_defaults_fail_at_startup(
    test_settings, overrides: dict, code: str
) -> None:
    """APP__AUTO_SETUP=true 時預設值不合法，啟動就失敗，而不是每個第一次 /view 都出錯；
    錯誤訊息不印出設定值。"""
    app_config = test_settings.app.model_copy(update={"auto_setup": True, **overrides})
    settings = test_settings.model_copy(update={"app": app_config})
    with pytest.raises(ValueError) as err:
        create_app(settings)
    message = str(err.value)
    assert code in message
    assert "APP__DEFAULT_" in message
    assert "祕密" not in message and "moon" not in message


@pytest.mark.parametrize(
    "overrides",
    [
        # 沒開 auto_setup，或公開展示模式（auto_setup 一律忽略）時不檢查
        {"auto_setup": False, "default_industry": "moon"},
        {"auto_setup": True, "public_demo": True, "default_modules": ["moon"]},
        # 合法的預設值，公司名稱前後空白會在建立時去掉
        {"auto_setup": True, "default_industry": "general", "default_company": " 甲 "},
    ],
)
def test_auto_setup_defaults_not_checked_or_valid(test_settings, overrides: dict) -> None:
    app_config = test_settings.app.model_copy(update=overrides)
    create_app(test_settings.model_copy(update={"app": app_config}))


# --- 工作區大小上限（B§2 workspace_limit）---------------------------------------------


def test_serialized_length_counts_utf16_units() -> None:
    """與 JavaScript `JSON.stringify(w).length` 相同：緊湊 JSON、非 ASCII 不跳脫、
    BMP 外的字元算 2 個字元。"""
    assert (
        ws_service.serialized_length({"a": "中😀", "b": [1, True, None]})
        == len('{"a":"中","b":[1,true,null]}') + 2
    )
    assert ws_service.serialized_length({"q": 'x"y'}) == len('{"q":"x\\"y"}')


def _pad_notes(db_engine: Engine, chars: int, fill: str = "中") -> None:
    """把第一位客戶的備註填成 `chars` 個字元，用來把工作區撐到指定大小。"""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE crm_record SET notes = repeat(:fill, :n) WHERE id ="
                " (SELECT id FROM crm_record WHERE collection = 'customers' ORDER BY seq LIMIT 1)"
            ),
            {"fill": fill, "n": chars},
        )


def _pad_to(api: ApiClient, db_engine: Engine, target: int) -> None:
    """把工作區快照撐到恰好 `target` 個字元（以「中」填充備註，UTF-8 下最肥的 BMP 字元）。"""
    _pad_notes(db_engine, 0)
    base = ws_service.serialized_length(api.snapshot())
    _pad_notes(db_engine, target - base)
    assert ws_service.serialized_length(api.snapshot()) == target


def test_workspace_limit_boundary(
    api: ApiClient, db_engine: Engine, test_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """恰好等於上限通過，多 1 個字元就 422 workspace_limit；檢查的是含版本號的完整快照。"""
    api.setup("general")
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        length = ws_service.serialized_length(
            ws_service.snapshot(db, ctx.workspace, ctx.session_row.version)  # type: ignore[arg-type]
        )
        monkeypatch.setattr(ws_service, "WORKSPACE_LIMIT", length)
        ws_service.check_workspace_limit(db, ctx.workspace_id)
        monkeypatch.setattr(ws_service, "WORKSPACE_LIMIT", length - 1)
        with pytest.raises(Problem) as exc:
            ws_service.check_workspace_limit(db, ctx.workspace_id)
        assert (exc.value.status, exc.value.code) == (422, "workspace_limit")


def test_command_cannot_grow_past_workspace_limit(api: ApiClient, db_engine: Engine) -> None:
    """接近上限的合法工作區，再新增一筆紀錄就超過上限：整筆回滾、版本與資料不變。"""
    api.setup("general")
    _pad_to(api, db_engine, ws_service.WORKSPACE_LIMIT - 50)
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", "/api/v1/crm/customers", {"name": "新客戶"})
    assert _error(r) == (422, "workspace_limit")
    assert api.snapshot() == before
    assert api.state()["version"] == version
    assert _scalar(db_engine, "SELECT count(*) FROM receipt") == 1  # 只有 setup


def test_legal_workspace_export_fits_import_cap(api: ApiClient, db_engine: Engine) -> None:
    """合法工作區的上限（1,000,000 字元，每字元 UTF-8 最多 3 bytes）保證匯出的備份不會超過
    3 MiB 匯入上限：以最肥的 BMP 字元撐到接近上限，匯出後原樣匯入仍然成功。"""
    assert ws_service.WORKSPACE_LIMIT * 3 < IMPORT_BODY_LIMIT
    api.setup("general")
    _pad_to(api, db_engine, ws_service.WORKSPACE_LIMIT - 1_000)
    r = api.get("/api/v1/backup/export")
    assert r.status_code == 200
    raw = r.content
    assert 2_900_000 < len(raw) <= IMPORT_BODY_LIMIT
    state = api.state()
    r = api.client.request(
        "POST",
        "/api/v1/backup/import",
        content=raw,
        headers={
            "Origin": "http://testserver",
            "x-csrf-token": state["csrf"],
            "Idempotency-Key": new_key(),
            "If-Match-Version": str(state["version"]),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text[:300]
    assert ws_service.serialized_length(api.snapshot()) <= ws_service.WORKSPACE_LIMIT


def test_import_over_workspace_limit_rejected(api: ApiClient, db_engine: Engine) -> None:
    """備份本身小於 3 MiB 但還原後超過 1,000,000 字元：422 workspace_limit，原資料保留。"""
    api.setup("general")
    backup = api.get("/api/v1/backup/export").json()
    before = api.snapshot()
    backup["collections"]["customers"][0]["notes"] = "x" * ws_service.WORKSPACE_LIMIT
    r = api.mutate("POST", "/api/v1/backup/import", backup)
    assert _error(r) == (422, "workspace_limit")
    assert api.snapshot() == before
