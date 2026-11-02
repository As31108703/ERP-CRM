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
CRM = "/api/v1/crm"
QUOTES = "/api/v1/crm/quotes"
SERVICES = "/api/v1/services"
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


def _demo_world_with_crm(api: ApiClient) -> dict[str, str]:
    """`_demo_world` 再加上已發出的報價與已交付的服務（摘要都含 id），回傳各類紀錄的 id。"""
    _demo_world(api)
    ws = api.snapshot()
    case = ws["cases"][0]["id"]
    quote = api.ok(
        "POST",
        QUOTES,
        {"case_id": case, "amount_minor": 5000, "expires_at": "2099-01-01T00:00:00Z"},
    )["result"]
    api.ok("POST", f"{QUOTES}/{quote}/issue", {})
    service = ws["services"][0]["id"]
    api.ok("POST", f"{SERVICES}/{service}/confirm", {})
    api.ok("POST", f"{SERVICES}/{service}/deliver", {"artifact_ref": "v1"})
    ws = api.snapshot()
    delivery = next(s for s in ws["services"] if s["id"] == service)["deliveries"][0]
    return {
        "product": next(p for p in ws["products"] if p["sku"] == "T-001")["id"],
        "delivery": delivery["id"],
        "delivery_digest": delivery["digest"],
        "buyer": _wallet(ws, "buyer")["id"],
        "order": ws["orders"][0]["id"],
        "case": case,
        "deal": ws["deals"][0]["id"],
        "quote": quote,
        "service": service,
        "bom": ws["boms"][-1]["id"],
        "work_order": ws["work_orders"][0]["id"],
        "unit": ws["administration"]["units"][0]["id"],
    }


def test_import_same_backup_into_two_sessions(api: ApiClient, make_client) -> None:
    """同一份備份可以匯入多個工作區（例如老師把一份備份發給全班）：紀錄 id 以工作區為範圍，
    匯入後各自操作互不影響。"""
    ids = _demo_world_with_crm(api)
    source = api.snapshot()
    backup = _export(api)

    other = ApiClient(make_client())
    r = _import(other, backup)
    assert r.status_code == 200, r.text
    imported = other.snapshot()
    assert _without_generation(imported) == _without_generation(source)
    assert api.snapshot() == source

    # 已有工作區的第三個 session 匯入同一份備份，以及原 session 再匯入自己的備份也都成功
    third = ApiClient(make_client())
    third.setup("retail", company="另一家店")
    assert _import(third, backup).status_code == 200
    assert _without_generation(third.snapshot()) == _without_generation(source)
    assert _import(api, backup).status_code == 200
    source = api.snapshot()

    # B 對匯入的 id 下命令：只改到 B 自己的紀錄
    other.ok("PATCH", f"{PRODUCTS}/{ids['product']}", {"name": "乙班商品"})
    other.ok("POST", f"/api/v1/wallets/{ids['buyer']}/fund", {"amount_minor": 10})
    other.ok("PATCH", f"{CRM}/cases/{ids['case']}", {"title": "乙班案件"})
    other.ok("POST", f"{CRM}/deals/{ids['deal']}/followups", {"note": "乙班跟進"})
    digest = next(q for q in imported["quotes"] if q["id"] == ids["quote"])["digest"]
    other.ok("POST", f"{QUOTES}/{ids['quote']}/confirm", {"digest": digest})
    delivery = next(s for s in imported["services"] if s["id"] == ids["service"])["deliveries"][0]
    other.ok(
        "POST",
        f"{SERVICES}/{ids['service']}/accept",
        {"delivery_id": delivery["id"], "digest": delivery["digest"]},
    )
    other.ok("POST", WORK_ORDERS, {"bom_id": ids["bom"], "quantity": 1})
    other.ok("PATCH", f"{ADMIN}/units/{ids['unit']}", {"name": "乙班單位"})

    changed = other.snapshot()
    assert next(p for p in changed["products"] if p["id"] == ids["product"])["name"] == "乙班商品"
    assert next(c for c in changed["cases"] if c["id"] == ids["case"])["title"] == "乙班案件"
    assert next(q for q in changed["quotes"] if q["id"] == ids["quote"])["status"] == (
        "simulated_confirmed"
    )
    assert next(s for s in changed["services"] if s["id"] == ids["service"])["status"] == (
        "accepted"
    )
    assert len(changed["work_orders"]) == len(source["work_orders"]) + 1
    # 原 session 與第三個 session 的資料都沒有被 B 的命令改到
    assert api.snapshot() == source
    assert _without_generation(third.snapshot()) == _without_generation(imported)


def test_ids_from_other_workspace_are_missing(api: ApiClient, make_client) -> None:
    """其他工作區的 id 一律視為不存在（404），不會 500，也不會讀到或改到其他工作區的資料。
    每個以 id 取得紀錄的共用查詢至少各測一個命令。"""
    ids = _demo_world_with_crm(api)
    source = api.snapshot()
    other = ApiClient(make_client())
    other.setup("general", company="另一家店")
    own = other.snapshot()
    own_buyer = _wallet(own, "buyer")["id"]
    own_product = own["products"][0]["id"]
    own_service = own["services"][0]["id"]

    order_body = {
        "buyer_wallet_id": own_buyer,
        "lines": [{"product_id": ids["product"], "quantity": 1}],
    }
    bom_body = {
        "product_id": own_product,
        "components": [{"product_id": ids["product"], "quantity": 1}],
    }
    attempts = [
        # inventory.get_product
        ("PATCH", f"{PRODUCTS}/{ids['product']}", {"name": "x"}, "simulation_record_missing"),
        ("POST", ORDERS, order_body, "simulation_record_missing"),
        # wallets.get_wallet
        (
            "POST",
            f"/api/v1/wallets/{ids['buyer']}/fund",
            {"amount_minor": 1},
            "simulation_record_missing",
        ),
        # sales.get_order
        ("POST", f"{ORDERS}/{ids['order']}/cancel", {}, "simulation_record_missing"),
        # crm.records.find_record
        ("PATCH", f"{CRM}/cases/{ids['case']}", {"title": "x"}, "record_missing"),
        ("POST", f"{CRM}/deals/{ids['deal']}/followups", {"note": "x"}, "record_missing"),
        # crm 報價
        ("POST", f"{QUOTES}/{ids['quote']}/issue", {}, "record_missing"),
        # services.get_service
        ("POST", f"{SERVICES}/{ids['service']}/confirm", {}, "simulation_record_missing"),
        # services._review 的交付查詢：自己的服務帶其他工作區的 delivery_id
        (
            "POST",
            f"{SERVICES}/{own_service}/accept",
            {"delivery_id": ids["delivery"], "digest": ids["delivery_digest"]},
            "simulation_record_missing",
        ),
        # manufacturing 的商品、BOM、工單
        ("POST", BOMS, bom_body, "record_missing"),
        ("POST", WORK_ORDERS, {"bom_id": ids["bom"], "quantity": 1}, "record_missing"),
        ("POST", f"{WORK_ORDERS}/{ids['work_order']}/cancel", {}, "record_missing"),
        # administration.row_by_id
        ("PATCH", f"{ADMIN}/units/{ids['unit']}", {"name": "x"}, "office_record_missing"),
    ]
    for method, path, body, code in attempts:
        assert _error(other.mutate(method, path, body)) == (404, code), path
    assert other.snapshot() == own
    assert api.snapshot() == source


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
    assert _error(_import(api, tampered)) == (422, "ledger_balance_invalid")
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
    # _demo_world 用 general 範本，一定有示範服務，服務相關的竄改案例才有意義
    assert backup["collections"]["services"]
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


# --- 識別碼在整份備份中唯一（B§2）：業務與行政資料共用同一個集合 ------------------------


def _with_admin(api: ApiClient) -> dict[str, Any]:
    _demo_world(api)
    backup = _export(api)
    assert backup["collections"]["administration"]["units"]
    return backup


@pytest.mark.parametrize(
    "mutate",
    [
        # 行政資料列沿用業務資料的 id（大小寫不同也算重複）
        lambda c: c["administration"]["units"][0].__setitem__("id", c["products"][0]["id"].upper()),
        # 行政更正紀錄沿用巢狀業務資料（訂單品項）的 id
        lambda c: c["administration"]["changes"][0].__setitem__(
            "id", c["orders"][0]["lines"][0]["id"]
        ),
        # 業務資料沿用行政資料的 id
        lambda c: c["customers"][0].__setitem__("id", c["administration"]["staff"][0]["id"]),
        # 行政資料彼此重複
        lambda c: c["administration"]["notices"][0].__setitem__(
            "id", c["administration"]["units"][0]["id"]
        ),
        # 業務資料與 history 重複
        lambda c: c["history"][0].__setitem__("id", c["wallets"][0]["id"]),
    ],
    ids=[
        "admin_reuses_business",
        "change_reuses_line",
        "business_reuses_admin",
        "admin_dup",
        "history",
    ],
)
def test_import_ids_unique_across_business_and_admin(api: ApiClient, mutate: Any) -> None:
    backup = _with_admin(api)
    assert backup["collections"]["administration"]["changes"]
    before = api.snapshot()
    bad = copy.deepcopy(backup)
    mutate(bad["collections"])
    assert _error(_import(api, bad)) == (422, "id_collision")
    assert api.snapshot() == before


def test_record_ids_walks_declared_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """各模組以 ModuleSpec.id_paths 宣告資料列位置；共用的走訪器收集所有 id。"""
    from src.platform import registry

    monkeypatch.setattr(registry, "_SPECS", {})
    registry.register(
        registry.ModuleSpec(
            "a",
            lambda _d, _w: {},
            lambda _d, _w, _x: None,
            id_paths=("rows", "rows.items", "nested.list"),
        )
    )
    collections = {
        "rows": [{"id": "r1", "items": [{"id": "i1"}, {"id": "i2"}]}, {"id": "r2", "items": []}],
        "nested": {"list": [{"id": "n1"}, "not-a-row"]},
        "ignored": [{"id": "x"}],
    }
    assert sorted(registry.record_ids(collections)) == ["i1", "i2", "n1", "r1", "r2"]
    # 缺少的鍵或型別不符時略過，交給各模組的結構檢查回正式錯誤碼
    assert list(registry.record_ids({"rows": "bad", "nested": None})) == []
