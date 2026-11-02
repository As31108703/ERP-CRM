"""範本目錄與工作區：建立、檢視、清除、收據查詢、自動建立與 72 小時保留。"""

from datetime import timedelta

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.core import clock
from src.modules.catalog import seed
from src.modules.catalog.templates import TEMPLATES
from src.modules.workspace.retention import purge_expired, run_purge
from src.platform.registry import MODULES
from tests.helpers import ApiClient, new_key

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


def test_seed_extension_point(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], str]] = []

    def fake_seed(ctx, template) -> None:
        assert ctx.workspace is not None
        calls.append((template.id, list(ctx.workspace.modules), ctx.workspace.company_name))

    monkeypatch.setattr(seed, "_SEEDERS", {})
    seed.register_seeder("test", fake_seed)
    api.setup("service", "甲")
    assert calls == [("service", TEMPLATES["service"].modules, "甲")]


@pytest.mark.skip(reason="TODO(Task 5+)：各模組接上 seed 函式後，驗證 B§3.0 的示範資料")
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
    assert run_purge(db_engine, clock.utcnow()) == 0
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
            assert run_purge(db_engine, clock.utcnow()) == 0
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(7310)"))
            holder.commit()
    assert run_purge(db_engine, clock.utcnow()) == 1


def test_scheduler_only_in_public_demo(make_client) -> None:
    demo = make_client(public_demo=True)
    jobs = demo.app.state.scheduler.get_jobs()
    assert [j.id for j in jobs] == ["retention_purge"]
    assert jobs[0].trigger.interval == timedelta(minutes=10)
    private = make_client()
    assert private.app.state.scheduler is None
