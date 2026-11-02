"""備份匯出／匯入（嚴格結構檢查、整筆取代、一致性檢查、失敗整筆回滾）與本機啟動包。"""

import copy
import io
import json
import re
import uuid
import zipfile
from typing import Any

import pytest

from src.modules.workspace.service import NAME_MAX
from tests.helpers import ApiClient, new_key

EXPORT = "/api/v1/backup/export"
IMPORT = "/api/v1/backup/import"
LAUNCH_KIT = "/api/v1/backup/launch-kit"
PRODUCTS = "/api/v1/inventory/products"
ORDERS = "/api/v1/sales/orders"
BOMS = "/api/v1/manufacturing/boms"
WORK_ORDERS = "/api/v1/manufacturing/work-orders"
ADMIN = "/api/v1/administration"
WEEK = "2026-11-02"
MISSING = "00000000-0000-4000-8000-000000000000"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _without_generation(ws: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ws.items() if k not in ("generation_id", "version")}


def _export(api: ApiClient) -> dict[str, Any]:
    r = api.get(EXPORT)
    assert r.status_code == 200, r.text
    return r.json()


def _import(api: ApiClient, backup: Any):
    return api.mutate("POST", IMPORT, backup)


def _demo_world(api: ApiClient) -> None:
    """general 範本加上銷售（付款、出貨、退貨）、製造（完工）與行政示範（含封存公告）資料。"""
    api.setup("general", company="星軌示範商店")
    ws = api.snapshot()
    business = _wallet(ws, "business")["id"]
    buyer = _wallet(ws, "buyer")["id"]
    api.ok("POST", f"/api/v1/wallets/{business}/fund", {"amount_minor": 1_000_000})
    api.ok("POST", f"/api/v1/wallets/{buyer}/fund", {"amount_minor": 1_000_000})

    product = api.ok(
        "POST",
        PRODUCTS,
        {"name": "測試商品", "sku": "T-001", "price_minor": 900, "cost_minor": 100},
    )["result"]
    api.ok("POST", f"{PRODUCTS}/{product}/receive", {"quantity": 2})
    api.ok("PATCH", f"{PRODUCTS}/{product}", {"cost_minor": 200})
    api.ok("POST", f"{PRODUCTS}/{product}/receive", {"quantity": 3})
    order = api.ok(
        "POST",
        ORDERS,
        {"buyer_wallet_id": buyer, "lines": [{"product_id": product, "quantity": 3}]},
    )["result"]
    api.ok("POST", f"{ORDERS}/{order}/pay", {"amount_minor": 2700})
    [line] = next(o for o in api.snapshot()["orders"] if o["id"] == order)["lines"]
    api.ok("POST", f"{ORDERS}/{order}/ship", {"lines": [{"line_id": line["id"], "quantity": 3}]})
    api.ok("POST", f"{ORDERS}/{order}/return", {"lines": [{"line_id": line["id"], "quantity": 1}]})

    material = api.ok(
        "POST", PRODUCTS, {"name": "原料", "sku": "M-001", "price_minor": 0, "cost_minor": 50}
    )["result"]
    api.ok("POST", f"{PRODUCTS}/{material}/receive", {"quantity": 4})
    finished = api.ok(
        "POST", PRODUCTS, {"name": "成品", "sku": "F-001", "price_minor": 0, "cost_minor": 0}
    )["result"]
    bom = api.ok(
        "POST",
        BOMS,
        {"product_id": finished, "components": [{"product_id": material, "quantity": 2}]},
    )["result"]
    wo = api.ok("POST", WORK_ORDERS, {"bom_id": bom, "quantity": 2})["result"]
    for verb in ("reserve", "start", "complete"):
        api.ok("POST", f"{WORK_ORDERS}/{wo}/{verb}", {})

    api.ok("POST", f"{ADMIN}/demo", {"preset": "store", "week_start": WEEK})
    notice = api.snapshot()["administration"]["notices"][0]["id"]
    api.ok("POST", f"{ADMIN}/notices/{notice}/archive", {})


# --- 匯出 -----------------------------------------------------------------------


def test_export_format_and_headers(api: ApiClient) -> None:
    api.setup("general", company="星軌示範商店")
    r = api.get(EXPORT)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="erpcrm-sim-backup.json"'
    backup = r.json()
    assert set(backup) == {"format", "format_version", "exported_at", "workspace", "collections"}
    assert (backup["format"], backup["format_version"]) == ("erpcrm-sim-backup", 1)
    ws = api.snapshot()
    meta = backup["workspace"]
    assert meta["company_name"] == "星軌示範商店"
    assert meta["modules"] == ws["modules"]
    assert "csrf" not in json.dumps(backup)
    collections = backup["collections"]
    assert "history" in collections
    assert {**meta, **collections} == ws


def test_export_requires_workspace(api: ApiClient) -> None:
    assert _error(api.get(EXPORT)) == (409, "workspace_missing")


# --- 匯入 -----------------------------------------------------------------------


def test_export_import_roundtrip(api: ApiClient) -> None:
    _demo_world(api)
    before = api.snapshot()
    backup = _export(api)
    version = api.state()["version"]

    r = _import(api, backup)
    assert r.status_code == 200, r.text
    after = api.snapshot()
    assert _without_generation(after) == _without_generation(before)
    assert re.fullmatch(r"[0-9a-f]{32}", after["generation_id"])
    assert after["generation_id"] != before["generation_id"]
    assert r.json()["result"] == after["generation_id"]
    assert after["version"] == version + 1
    # 匯入不寫入 history
    assert after["history"] == before["history"]


def test_import_replaces_other_workspace(api: ApiClient) -> None:
    """備份匯入到另一個工作區（不同 session）也整筆取代原本的資料。"""
    _demo_world(api)
    source = api.snapshot()
    backup = _export(api)
    api.ok("POST", "/api/v1/workspace/clear")
    api.setup("retail", company="另一家店")
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    assert _without_generation(api.snapshot()) == _without_generation(source)


def test_import_without_existing_workspace(api: ApiClient) -> None:
    api.setup("general")
    backup = _export(api)
    api.ok("POST", "/api/v1/workspace/clear")
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    assert api.snapshot()["company_name"] == "測試公司"


def test_import_tampered_keeps_existing(api: ApiClient) -> None:
    _demo_world(api)
    backup = _export(api)
    before = api.snapshot()
    tampered = copy.deepcopy(backup)
    _wallet(tampered["collections"], "business")["balance_minor"] += 1
    assert _error(_import(api, tampered)) == (422, "money_conservation")
    assert api.snapshot() == before


def test_import_tampered_ledger_keeps_existing(api: ApiClient) -> None:
    _demo_world(api)
    backup = _export(api)
    before = api.snapshot()
    tampered = copy.deepcopy(backup)
    entries = tampered["collections"]["ledger"][0]["entries"]
    entries[0]["amount_minor"] -= 1
    entries[1]["amount_minor"] += 1
    status, _code = _error(_import(api, tampered))
    assert status == 422
    assert api.snapshot() == before


def _mutations() -> list[tuple[str, Any, int, str]]:
    def drop(key: str):
        def fn(b: dict[str, Any]) -> None:
            del b[key]

        return fn

    def put(path: list[Any], value: Any):
        def fn(b: dict[str, Any]) -> None:
            target = b
            for p in path[:-1]:
                target = target[p]
            target[path[-1]] = value

        return fn

    def first_product(key: str, value: Any):
        def fn(b: dict[str, Any]) -> None:
            b["collections"]["products"][0][key] = value

        return fn

    def duplicate_id(b: dict[str, Any]) -> None:
        b["collections"]["customers"][0]["id"] = b["collections"]["products"][0]["id"].upper()

    def missing_wallet(b: dict[str, Any]) -> None:
        b["collections"]["orders"][0]["buyer_wallet_id"] = MISSING

    def missing_product(b: dict[str, Any]) -> None:
        b["collections"]["purchases"][0]["product_id"] = MISSING

    def case_mismatch(b: dict[str, Any]) -> None:
        services = b["collections"]["services"]
        services[0]["source_snapshot"]["case"]["id"] = MISSING

    def real_finance(b: dict[str, Any]) -> None:
        b["workspace"]["real_finance"] = True

    def nul_text(b: dict[str, Any]) -> None:
        b["collections"]["products"][0]["name"] = "a\x00b"

    def legal(b: dict[str, Any]) -> None:
        b["collections"]["services"][0]["legal_confirmation"] = True

    return [
        ("format", put(["format"], "other-backup"), 422, "import_invalid"),
        ("format_version", put(["format_version"], 2), 422, "import_invalid"),
        ("format_version_bool", put(["format_version"], True), 422, "import_invalid"),
        ("history_bool", put(["collections", "history"], [True]), 422, "import_invalid"),
        ("no_collections", drop("collections"), 422, "import_invalid"),
        ("extra_top", put(["extra"], 1), 422, "import_invalid"),
        ("extra_row_key", first_product("bank", 1), 422, "import_invalid"),
        ("bool_as_int", first_product("on_hand", True), 422, "import_invalid"),
        ("float_int", first_product("on_hand", 1.5), 422, "import_invalid"),
        ("bad_uuid", first_product("id", "not-a-uuid"), 422, "import_invalid"),
        ("bad_time", first_product("created_at", "yesterday"), 422, "import_invalid"),
        ("naive_time", first_product("created_at", "2026-11-02T00:00:00"), 422, "import_invalid"),
        ("nul_text", nul_text, 422, "import_invalid"),
        ("missing_list", put(["collections", "orders"], None), 422, "import_invalid"),
        ("industry", put(["workspace", "industry"], "moon"), 422, "industry_invalid"),
        ("company", put(["workspace", "company_name"], " "), 422, "name_invalid"),
        ("company_long", put(["workspace", "company_name"], "x" * 101), 422, "name_invalid"),
        ("modules", put(["workspace", "modules"], ["sales"]), 422, "module_dependency"),
        ("real_finance", real_finance, 422, "simulation_required"),
        ("legal", legal, 422, "simulation_required"),
        ("duplicate_id", duplicate_id, 422, "id_collision"),
        ("missing_wallet", missing_wallet, 404, "record_missing"),
        ("missing_product", missing_product, 404, "record_missing"),
        ("case_mismatch", case_mismatch, 422, "import_invalid"),
    ]


@pytest.mark.parametrize(
    ("name", "mutate", "status", "code"), _mutations(), ids=[m[0] for m in _mutations()]
)
def test_import_rejections_keep_existing(
    api: ApiClient, name: str, mutate: Any, status: int, code: str
) -> None:
    _demo_world(api)
    backup = _export(api)
    if name in ("case_mismatch", "legal") and not backup["collections"]["services"]:
        pytest.skip("範本沒有服務資料")
    before = api.snapshot()
    bad = copy.deepcopy(backup)
    mutate(bad)
    assert _error(_import(api, bad)) == (status, code)
    assert api.snapshot() == before


def test_import_not_object_422(api: ApiClient) -> None:
    api.setup("general")
    before = api.snapshot()
    r = api.client.request(
        "POST",
        IMPORT,
        content=b"[]",
        headers={
            "Origin": "http://testserver",
            "x-csrf-token": api.state()["csrf"],
            "Idempotency-Key": new_key(),
            "If-Match-Version": str(api.state()["version"]),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 422
    assert api.snapshot() == before


def test_import_legacy_admin_defaults(api: ApiClient) -> None:
    """舊格式行政資料缺 changes、voided、archived：視為空陣列與 false，匯入成功且不改輸入。"""
    api.setup("general", company="星軌示範商店")
    api.ok("POST", f"{ADMIN}/demo", {"preset": "store", "week_start": WEEK})
    backup = _export(api)
    adm = backup["collections"]["administration"]
    assert adm["attendance"] and adm["notices"]
    assert adm["changes"] == []
    del adm["changes"]
    for row in adm["attendance"]:
        del row["voided"]
    for row in adm["notices"]:
        del row["archived"]
    legacy = copy.deepcopy(backup)

    r = _import(api, backup)
    assert r.status_code == 200, r.text
    # 驗證不寫回輸入
    assert backup == legacy
    restored = api.snapshot()["administration"]
    assert restored["changes"] == []
    assert all(row["voided"] is False for row in restored["attendance"])
    assert all(row["archived"] is False for row in restored["notices"])
    # 補上預設值後，其餘內容與原資料相同
    for name in ("attendance", "notices"):
        flag = "voided" if name == "attendance" else "archived"
        assert [{k: v for k, v in row.items() if k != flag} for row in restored[name]] == adm[name]


def test_import_admin_data_when_backup_enables_admin(api: ApiClient) -> None:
    """目前工作區未啟用行政，但備份的模組清單有行政：行政資料照樣還原。"""
    api.setup("general", company="星軌示範商店")
    api.ok("POST", f"{ADMIN}/demo", {"preset": "store", "week_start": WEEK})
    source = api.snapshot()
    backup = _export(api)
    api.ok("POST", "/api/v1/workspace/clear")
    api.setup("retail")
    assert "administration" not in api.snapshot()["modules"]
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    assert api.snapshot()["administration"] == source["administration"]


def test_import_restores_disabled_module_collections(api: ApiClient) -> None:
    """模組未啟用時也還原該模組的集合（例如 crm 關閉、projects 開啟時的 tasks）。"""
    api.setup("general")
    backup = _export(api)
    collections = backup["collections"]
    assert collections["tasks"]
    backup["workspace"]["modules"] = ["inventory", "wallets", "projects"]
    collections.pop("administration", None)
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    ws = api.snapshot()
    assert ws["modules"] == ["inventory", "wallets", "projects"]
    assert ws["tasks"] == collections["tasks"]
    assert ws["customers"] == collections["customers"]


def test_import_admin_data_without_module_rejected(api: ApiClient) -> None:
    api.setup("general")
    backup = _export(api)
    before = api.snapshot()
    backup["workspace"]["modules"] = [
        m for m in backup["workspace"]["modules"] if m != "administration"
    ]
    assert _error(_import(api, backup)) == (422, "office_schema_invalid")
    assert api.snapshot() == before


def test_import_over_3mib_413(api: ApiClient) -> None:
    api.setup("general")
    before = api.snapshot()
    state = api.state()
    backup = _export(api)
    backup["padding"] = "x" * (3 * 1024 * 1024)
    raw = json.dumps(backup).encode("utf-8")
    assert len(raw) > 3 * 1024 * 1024
    r = api.client.request(
        "POST",
        IMPORT,
        content=raw,
        headers={
            "Origin": "http://testserver",
            "x-csrf-token": state["csrf"],
            "Idempotency-Key": new_key(),
            "If-Match-Version": str(state["version"]),
            "Content-Type": "application/json",
        },
    )
    assert _error(r) == (413, "body_limit")
    assert api.snapshot() == before


def test_import_under_3mib_above_32k_accepted(api: ApiClient) -> None:
    """一般寫入的 32 KiB 上限不適用於匯入。"""
    _demo_world(api)
    backup = _export(api)
    history = backup["collections"]["history"]
    template = history[-1]
    history.extend(
        {**template, "id": str(uuid.uuid4()), "version": template["version"] + i}
        for i in range(1, 201)
    )
    assert len(json.dumps(backup).encode("utf-8")) > 32_768
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    assert api.snapshot()["history"] == history


def test_import_bypasses_receipt_cap_and_prunes(api: ApiClient, db_engine) -> None:
    from sqlalchemy import text

    api.setup("general")
    backup = _export(api)
    with db_engine.begin() as conn:
        session_id = conn.execute(text("SELECT id FROM workspace_session")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO receipt (session_id, key, hash, expected_version, version, action)"
                " SELECT :sid, 'k' || g, repeat('0', 64), 0, 0, 'x' FROM generate_series(1, 500) g"
            ),
            {"sid": session_id},
        )
    r = _import(api, backup)
    assert r.status_code == 200, r.text
    with db_engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM receipt")).scalar_one()
    assert count == 101


# --- 本機啟動包 -------------------------------------------------------------------


def _kit(api: ApiClient, **params: str):
    return api.get(LAUNCH_KIT, params=params)


def _env(text_: str) -> dict[str, str]:
    out = {}
    for line in text_.splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key] = value
    return out


def test_launch_kit_zip_contents(api: ApiClient) -> None:
    r = _kit(
        api,
        industry="general",
        company_name="  星軌示範商店  ",
        modules="inventory,wallets,sales,administration",
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="erpcrm-launch-kit.zip"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = set(zf.namelist())
        assert names == {".env", "start.sh", "start.cmd", "README.txt"}
        env = _env(zf.read(".env").decode("utf-8"))
        assert env["APP__AUTO_SETUP"] == "true"
        assert env["APP__PUBLIC_DEMO"] == "false"
        # 覆蓋原有 .env 後仍保留前端連接埠設定（docker compose 讀取）
        assert env["FRONTEND_PORT"] == "8080"
        assert env["APP__DEFAULT_INDUSTRY"] == "general"
        assert env["APP__DEFAULT_COMPANY"] == "'星軌示範商店'"
        assert json.loads(env["APP__DEFAULT_MODULES"]) == [
            "inventory",
            "wallets",
            "sales",
            "administration",
        ]
        start = zf.getinfo("start.sh")
        assert (start.external_attr >> 16) & 0o777 == 0o755
        assert "docker compose up -d --build" in zf.read("start.sh").decode("utf-8")
        assert "docker compose up -d --build" in zf.read("start.cmd").decode("utf-8")
        readme = zf.read("README.txt").decode("utf-8")
        assert "根目錄" in readme
        assert "start.sh" in readme and "start.cmd" in readme
        # 既有資料庫沿用初始化時的密碼：自訂過密碼的使用者要把它保留在新的 .env
        assert "./data/postgres" in readme
        assert "DATABASE__PASSWORD" in readme
        assert "FRONTEND_PORT" in readme


def test_launch_kit_default_modules_and_quoting(api: ApiClient) -> None:
    r = _kit(api, industry="retail", company_name='it\'s "A" $B')
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        env = _env(zf.read(".env").decode("utf-8"))
    assert env["APP__DEFAULT_COMPANY"] == '"it\'s \\"A\\" $$B"'
    from src.modules.catalog.templates import TEMPLATES

    assert json.loads(env["APP__DEFAULT_MODULES"]) == list(TEMPLATES["retail"].modules)


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"industry": "moon", "company_name": "店"}, "industry_invalid"),
        ({"company_name": "店"}, "industry_invalid"),
        ({"industry": "general"}, "name_invalid"),
        ({"industry": "general", "company_name": "   "}, "name_invalid"),
        ({"industry": "general", "company_name": "x" * (NAME_MAX + 1)}, "name_invalid"),
        ({"industry": "general", "company_name": "a\u0007b"}, "name_invalid"),
        ({"industry": "general", "company_name": "a\u0085b"}, "name_invalid"),
        ({"industry": "general", "company_name": "店", "modules": ""}, "module_invalid"),
        ({"industry": "general", "company_name": "店", "modules": "moon"}, "module_invalid"),
        (
            {"industry": "general", "company_name": "店", "modules": "inventory,inventory"},
            "module_invalid",
        ),
        ({"industry": "general", "company_name": "店", "modules": "sales"}, "module_dependency"),
    ],
)
def test_launch_kit_rejects_invalid(api: ApiClient, params: dict[str, str], code: str) -> None:
    assert _error(_kit(api, **params)) == (422, code)
