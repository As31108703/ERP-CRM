"""服務交付：由案件建立草稿、確認、版本化交付（摘要）、驗收或要求修改、驗收後分次付款，
以及服務付款流水、交付摘要與狀態的一致性檢查與快照還原。"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.core.canonical import digest
from src.modules.catalog.templates import TEMPLATES
from src.modules.services.router import SPEC as SERVICES_SPEC
from tests.helpers import ApiClient, workspace_ctx

SERVICES = "/api/v1/services"
CASES = "/api/v1/crm/cases"
SERVICE_KEYS = {
    "id",
    "case_id",
    "title",
    "source_snapshot",
    "amount_minor",
    "currency",
    "status",
    "paid_minor",
    "deliveries",
    "latest_delivery_id",
    "legal_confirmation",
    "created_at",
    "updated_at",
}


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _wallet(ws: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in ws["wallets"] if w["kind"] == kind)


def _service(ws: dict[str, Any], service_id: str) -> dict[str, Any]:
    return next(s for s in ws["services"] if s["id"] == service_id)


def _fund(api: ApiClient, wallet_id: str, amount: int) -> None:
    api.ok("POST", f"/api/v1/wallets/{wallet_id}/fund", {"amount_minor": amount})


def _create(api: ApiClient, case_id: str, amount: int = 1000) -> str:
    return api.ok("POST", SERVICES, {"case_id": case_id, "amount_minor": amount})["result"]


def _act(api: ApiClient, service_id: str, verb: str, body: dict[str, Any] | None = None) -> None:
    api.ok("POST", f"{SERVICES}/{service_id}/{verb}", body or {})


def _deliver(api: ApiClient, service_id: str, ref: str) -> dict[str, Any]:
    """交付並回傳新的交付紀錄（最後一筆）。"""
    _act(api, service_id, "deliver", {"artifact_ref": ref})
    return _service(api.snapshot(), service_id)["deliveries"][-1]


def _review(api: ApiClient, service_id: str, verb: str, delivery: dict[str, Any]) -> None:
    _act(api, service_id, verb, {"delivery_id": delivery["id"], "digest": delivery["digest"]})


def _case(api: ApiClient) -> str:
    return api.snapshot()["cases"][0]["id"]


# --- seed -----------------------------------------------------------------------


@pytest.mark.parametrize("industry", ["service", "projects", "general"])
def test_seed_draft_service(api: ApiClient, industry: str) -> None:
    api.setup(industry)
    sample = TEMPLATES[industry].sample
    ws = api.snapshot()
    [case] = ws["cases"]
    [service] = ws["services"]
    assert set(service) == SERVICE_KEYS
    assert {k: v for k, v in service.items() if k not in ("id", "created_at", "updated_at")} == {
        "case_id": case["id"],
        "title": sample.service,
        "source_snapshot": {
            "case": {"id": case["id"], "title": sample.service},
            "price_source": "industry_template_demo",
        },
        "amount_minor": sample.price_minor,
        "currency": "SIM",
        "status": "draft",
        "paid_minor": 0,
        "deliveries": [],
        "latest_delivery_id": None,
        "legal_confirmation": False,
    }
    assert ws["history"] == []


@pytest.mark.parametrize(
    ("industry", "modules"),
    [("retail", None), ("general", ["inventory", "wallets", "crm"])],
)
def test_seed_no_service_without_module(
    api: ApiClient, industry: str, modules: list[str] | None
) -> None:
    api.setup(industry, modules=modules)
    assert api.snapshot()["services"] == []


# --- 流程 -----------------------------------------------------------------------


def test_service_happy_path(api: ApiClient) -> None:
    api.setup()
    case = api.ok("POST", CASES, {"title": "官網改版", "name": "不採用"})["result"]
    sid = _create(api, case, 1000)
    ws = api.snapshot()
    service = _service(ws, sid)
    assert service["source_snapshot"] == {
        "case": {"id": case, "title": "官網改版"},
        "price_source": "explicit_simulation_input",
    }
    assert service["title"] == "官網改版"
    assert service["status"] == "draft"
    assert ws["history"][-1]["action"] == "service.create"
    assert ws["history"][-1]["result"] == sid

    _act(api, sid, "confirm")
    assert _service(api.snapshot(), sid)["status"] == "confirmed"

    delivery = _deliver(api, sid, "artifact://v1")
    assert delivery["revision"] == 1
    assert delivery["artifact_ref"] == "artifact://v1"
    assert delivery["digest"] == digest(
        {"service_id": sid, "revision": 1, "artifact_ref": "artifact://v1"}
    )
    service = _service(api.snapshot(), sid)
    assert service["status"] == "submitted"
    assert service["latest_delivery_id"] == delivery["id"]

    _review(api, sid, "accept", delivery)
    assert _service(api.snapshot(), sid)["status"] == "accepted"

    ws = api.snapshot()
    buyer = _wallet(ws, "buyer")["id"]
    business = _wallet(ws, "business")["id"]
    _fund(api, buyer, 1000)
    _act(api, sid, "pay", {"buyer_wallet_id": buyer, "amount_minor": 400})
    service = _service(api.snapshot(), sid)
    assert service["paid_minor"] == 400
    assert service["status"] == "accepted"
    _act(api, sid, "pay", {"buyer_wallet_id": buyer, "amount_minor": 600})
    ws = api.snapshot()
    assert _service(ws, sid)["paid_minor"] == 1000
    assert _wallet(ws, "buyer")["balance_minor"] == 0
    assert _wallet(ws, "business")["balance_minor"] == 1000
    pays = [entry for entry in ws["ledger"] if entry["kind"] == "service.pay"]
    assert [p["reference_id"] for p in pays] == [sid, sid]
    assert pays[0]["entries"] == [
        {"wallet_id": buyer, "amount_minor": -400},
        {"wallet_id": business, "amount_minor": 400},
    ]
    assert [h["action"] for h in ws["history"][-6:]] == [
        "service.confirm",
        "service.deliver",
        "service.accept",
        "wallet.fund",
        "service.pay",
        "service.pay",
    ]


def test_case_name_and_default_title(api: ApiClient) -> None:
    """來源標題依序取案件的 title、name，都沒有時為「模擬服務」。"""
    api.setup()
    named = api.ok("POST", CASES, {"name": "只有名稱"})["result"]
    blank = api.ok("POST", CASES, {"status": "open"})["result"]
    ws_ids = [_create(api, named), _create(api, blank)]
    ws = api.snapshot()
    assert [_service(ws, s)["title"] for s in ws_ids] == ["只有名稱", "模擬服務"]
    assert _service(ws, ws_ids[1])["source_snapshot"]["case"] == {"id": blank, "title": "模擬服務"}


def test_request_changes_then_redeliver(api: ApiClient) -> None:
    api.setup()
    sid = _create(api, _case(api))
    _act(api, sid, "confirm")
    v1 = _deliver(api, sid, "draft-1")
    _review(api, sid, "request-changes", v1)
    assert _service(api.snapshot(), sid)["status"] == "changes_requested"
    v2 = _deliver(api, sid, "draft-1")
    assert v2["revision"] == 2
    # 同一個 artifact_ref，版本不同摘要就不同
    assert v2["digest"] != v1["digest"]
    service = _service(api.snapshot(), sid)
    assert [d["id"] for d in service["deliveries"]] == [v1["id"], v2["id"]]
    assert service["latest_delivery_id"] == v2["id"]
    assert service["status"] == "submitted"
    _review(api, sid, "accept", v2)
    # 驗收後、付款前仍可再交付，狀態回到 submitted
    v3 = _deliver(api, sid, "final")
    assert v3["revision"] == 3
    assert _service(api.snapshot(), sid)["status"] == "submitted"


def test_deliver_after_payment_409_simulation_service_paid(api: ApiClient) -> None:
    api.setup()
    sid = _create(api, _case(api))
    _act(api, sid, "confirm")
    _review(api, sid, "accept", _deliver(api, sid, "v1"))
    buyer = _wallet(api.snapshot(), "buyer")["id"]
    _fund(api, buyer, 100)
    _act(api, sid, "pay", {"buyer_wallet_id": buyer, "amount_minor": 100})
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{SERVICES}/{sid}/deliver", {"artifact_ref": "v2"})
    assert _error(r) == (409, "simulation_service_paid")
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_accept_stale_delivery_409(api: ApiClient) -> None:
    api.setup()
    sid = _create(api, _case(api))
    _act(api, sid, "confirm")
    v1 = _deliver(api, sid, "v1")
    v2 = _deliver(api, sid, "v2")
    before = api.snapshot()
    version = api.state()["version"]
    for body in (
        {"delivery_id": v1["id"], "digest": v1["digest"]},
        # 最新版本配上舊摘要也不行
        {"delivery_id": v2["id"], "digest": v1["digest"]},
    ):
        for verb in ("accept", "request-changes"):
            r = api.mutate("POST", f"{SERVICES}/{sid}/{verb}", body)
            assert _error(r) == (409, "simulation_delivery_outdated"), (verb, body)
    assert api.snapshot() == before
    assert api.state()["version"] == version
    _review(api, sid, "accept", v2)


def test_pay_before_accept_409(api: ApiClient) -> None:
    api.setup()
    sid = _create(api, _case(api))
    buyer = _wallet(api.snapshot(), "buyer")["id"]
    _fund(api, buyer, 1000)
    body = {"buyer_wallet_id": buyer, "amount_minor": 100}
    for step in ("draft", "confirm", "deliver", "request-changes"):
        if step == "confirm":
            _act(api, sid, "confirm")
        elif step == "deliver":
            _deliver(api, sid, "v1")
        elif step == "request-changes":
            _review(api, sid, "request-changes", _service(api.snapshot(), sid)["deliveries"][-1])
        before = api.snapshot()
        version = api.state()["version"]
        r = api.mutate("POST", f"{SERVICES}/{sid}/pay", body)
        assert _error(r) == (409, "simulation_acceptance_required"), step
        assert api.snapshot() == before
        assert api.state()["version"] == version


def test_services_disabled_403_module_disabled(api: ApiClient) -> None:
    api.setup("general", modules=["inventory", "wallets", "crm"])
    case = _case(api)
    ws = api.snapshot()
    version = api.state()["version"]
    for path, body in (
        (SERVICES, {"case_id": case, "amount_minor": 1}),
        (f"{SERVICES}/{case}/confirm", {}),
        (f"{SERVICES}/{case}/deliver", {"artifact_ref": "x"}),
        (f"{SERVICES}/{case}/accept", {"delivery_id": case, "digest": "x"}),
        (f"{SERVICES}/{case}/request-changes", {"delivery_id": case, "digest": "x"}),
        (f"{SERVICES}/{case}/pay", {"buyer_wallet_id": case, "amount_minor": 1}),
        # 禁用鍵名與模組未啟用同時成立時，模組閘優先
        (SERVICES, {"legal_confirmation": True}),
    ):
        r = api.mutate("POST", path, body)
        assert _error(r) == (403, "module_disabled"), path
    assert api.snapshot() == ws
    assert api.state()["version"] == version


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


class Scenario:
    """general 範本（全模組）。買家先補 500，各服務金額 1000：

    - draft：seed 的草稿服務
    - confirmed：已確認、尚未交付
    - submitted：交付 v1 → 要求修改 → 交付 v2（目前待驗收的是 v2）
    - changes：交付 v1 → 要求修改
    - accepted：交付 v1 → 驗收，已付款 100（買家餘額剩 400）
    """

    def __init__(self, api: ApiClient) -> None:
        api.setup()
        ws = api.snapshot()
        self.case = ws["cases"][0]["id"]
        self.deal = ws["deals"][0]["id"]
        self.draft = ws["services"][0]["id"]
        self.buyer = _wallet(ws, "buyer")["id"]
        self.business = _wallet(ws, "business")["id"]
        _fund(api, self.buyer, 500)

        self.confirmed = _create(api, self.case)
        _act(api, self.confirmed, "confirm")

        self.submitted = _create(api, self.case)
        _act(api, self.submitted, "confirm")
        self.v1 = _deliver(api, self.submitted, "v1")
        _review(api, self.submitted, "request-changes", self.v1)
        self.v2 = _deliver(api, self.submitted, "v2")

        self.changes = _create(api, self.case)
        _act(api, self.changes, "confirm")
        self.changes_v1 = _deliver(api, self.changes, "v1")
        _review(api, self.changes, "request-changes", self.changes_v1)

        self.accepted = _create(api, self.case)
        _act(api, self.accepted, "confirm")
        self.accepted_v1 = _deliver(api, self.accepted, "v1")
        _review(api, self.accepted, "accept", self.accepted_v1)
        _act(api, self.accepted, "pay", {"buyer_wallet_id": self.buyer, "amount_minor": 100})


Make = Callable[[Scenario], tuple[str, Any]]
MISSING = "00000000-0000-4000-8000-000000000000"


def _review_body(d: dict[str, Any]) -> dict[str, Any]:
    return {"delivery_id": d["id"], "digest": d["digest"]}


def _pay(s: Scenario, service_id: str, amount: Any = 1, wallet: str | None = None) -> Any:
    return (
        f"{SERVICES}/{service_id}/pay",
        {"buyer_wallet_id": wallet or s.buyer, "amount_minor": amount},
    )


_CASES: list[tuple[str, Make, int, str]] = [
    # B§3.1 通用前置檢查
    ("payload_list", lambda s: (SERVICES, [1]), 422, "payload_invalid"),
    (
        "forbidden_legal_confirmation",
        lambda s: (
            f"{SERVICES}/{s.submitted}/accept",
            {**_review_body(s.v2), "legal_confirmation": True},
        ),
        422,
        "simulation_required",
    ),
    (
        "forbidden_payer",
        lambda s: (f"{SERVICES}/{s.accepted}/pay", {**_pay(s, s.accepted)[1], "payer": "x"}),
        422,
        "simulation_required",
    ),
    (
        "protected_field",
        lambda s: (SERVICES, {"case_id": s.case, "amount_minor": 1, "currency": "SIM"}),
        422,
        "protected_field",
    ),
    (
        "learning_id",
        lambda s: (
            SERVICES,
            {"case_id": s.case, "amount_minor": 1, "learning_run_id": "run-abcdef01"},
        ),
        422,
        "learning_id_invalid",
    ),
    # service.create
    (
        "create_case_missing",
        lambda s: (SERVICES, {"case_id": MISSING, "amount_minor": 1}),
        404,
        "record_missing",
    ),
    (
        "create_case_is_deal",
        lambda s: (SERVICES, {"case_id": s.deal, "amount_minor": 1}),
        404,
        "record_missing",
    ),
    (
        "create_case_bad_id",
        lambda s: (SERVICES, {"case_id": "not-a-uuid", "amount_minor": 1}),
        404,
        "record_missing",
    ),
    (
        "create_amount_missing",
        lambda s: (SERVICES, {"case_id": s.case}),
        422,
        "number_invalid",
    ),
    (
        "create_amount_zero",
        lambda s: (SERVICES, {"case_id": s.case, "amount_minor": 0}),
        422,
        "number_invalid",
    ),
    (
        "create_amount_fraction",
        lambda s: (SERVICES, {"case_id": s.case, "amount_minor": 1.5}),
        422,
        "number_invalid",
    ),
    (
        "create_amount_over_limit",
        lambda s: (SERVICES, {"case_id": s.case, "amount_minor": 1_000_000_001}),
        422,
        "number_invalid",
    ),
    # service.confirm
    (
        "confirm_missing",
        lambda s: (f"{SERVICES}/{MISSING}/confirm", {}),
        404,
        "simulation_record_missing",
    ),
    (
        "confirm_bad_id",
        lambda s: (f"{SERVICES}/not-a-uuid/confirm", {}),
        404,
        "simulation_record_missing",
    ),
    (
        "confirm_confirmed",
        lambda s: (f"{SERVICES}/{s.confirmed}/confirm", {}),
        409,
        "simulation_service_state",
    ),
    (
        "confirm_accepted",
        lambda s: (f"{SERVICES}/{s.accepted}/confirm", {}),
        409,
        "simulation_service_state",
    ),
    # service.deliver
    (
        "deliver_missing",
        lambda s: (f"{SERVICES}/{MISSING}/deliver", {"artifact_ref": "x"}),
        404,
        "simulation_record_missing",
    ),
    (
        "deliver_draft",
        lambda s: (f"{SERVICES}/{s.draft}/deliver", {"artifact_ref": "x"}),
        409,
        "simulation_service_state",
    ),
    (
        "deliver_paid",
        lambda s: (f"{SERVICES}/{s.accepted}/deliver", {"artifact_ref": "x"}),
        409,
        "simulation_service_paid",
    ),
    (
        "deliver_ref_missing",
        lambda s: (f"{SERVICES}/{s.confirmed}/deliver", {}),
        422,
        "delivery_invalid",
    ),
    (
        "deliver_ref_type",
        lambda s: (f"{SERVICES}/{s.confirmed}/deliver", {"artifact_ref": 1}),
        422,
        "delivery_invalid",
    ),
    # service.accept / service.request_changes
    (
        "accept_service_missing",
        lambda s: (f"{SERVICES}/{MISSING}/accept", _review_body(s.v2)),
        404,
        "simulation_record_missing",
    ),
    (
        "accept_delivery_missing",
        lambda s: (f"{SERVICES}/{s.submitted}/accept", {"delivery_id": MISSING, "digest": "x"}),
        404,
        "simulation_record_missing",
    ),
    (
        "accept_other_service_delivery",
        lambda s: (f"{SERVICES}/{s.submitted}/accept", _review_body(s.changes_v1)),
        404,
        "simulation_record_missing",
    ),
    (
        "accept_stale",
        lambda s: (f"{SERVICES}/{s.submitted}/accept", _review_body(s.v1)),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "accept_wrong_digest",
        lambda s: (
            f"{SERVICES}/{s.submitted}/accept",
            {"delivery_id": s.v2["id"], "digest": "0" * 64},
        ),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "accept_no_digest",
        lambda s: (f"{SERVICES}/{s.submitted}/accept", {"delivery_id": s.v2["id"]}),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "accept_changes_requested",
        lambda s: (f"{SERVICES}/{s.changes}/accept", _review_body(s.changes_v1)),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "accept_accepted",
        lambda s: (f"{SERVICES}/{s.accepted}/accept", _review_body(s.accepted_v1)),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "request_changes_stale",
        lambda s: (f"{SERVICES}/{s.submitted}/request-changes", _review_body(s.v1)),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "request_changes_twice",
        lambda s: (f"{SERVICES}/{s.changes}/request-changes", _review_body(s.changes_v1)),
        409,
        "simulation_delivery_outdated",
    ),
    (
        "request_changes_delivery_missing",
        lambda s: (
            f"{SERVICES}/{s.submitted}/request-changes",
            {"delivery_id": "x", "digest": "x"},
        ),
        404,
        "simulation_record_missing",
    ),
    # service.pay
    (
        "pay_service_missing",
        lambda s: _pay(s, MISSING),
        404,
        "simulation_record_missing",
    ),
    (
        "pay_draft",
        lambda s: _pay(s, s.draft),
        409,
        "simulation_acceptance_required",
    ),
    (
        "pay_submitted",
        lambda s: _pay(s, s.submitted),
        409,
        "simulation_acceptance_required",
    ),
    (
        # 狀態先於錢包檢查
        "pay_changes_with_business_wallet",
        lambda s: _pay(s, s.changes, wallet=s.business),
        409,
        "simulation_acceptance_required",
    ),
    (
        "pay_wallet_missing",
        lambda s: _pay(s, s.accepted, wallet=MISSING),
        404,
        "simulation_record_missing",
    ),
    (
        "pay_business_wallet",
        lambda s: _pay(s, s.accepted, wallet=s.business),
        422,
        "simulation_buyer_required",
    ),
    (
        # 已付 100，剩 900；超收檢查先於餘額檢查（買家只剩 400）
        "pay_overpayment",
        lambda s: _pay(s, s.accepted, 901),
        409,
        "simulation_overpayment",
    ),
    (
        "pay_insufficient_funds",
        lambda s: _pay(s, s.accepted, 401),
        409,
        "simulation_insufficient_funds",
    ),
    (
        "pay_amount_zero",
        lambda s: _pay(s, s.accepted, 0),
        422,
        "number_invalid",
    ),
    (
        "pay_amount_missing",
        lambda s: (f"{SERVICES}/{s.accepted}/pay", {"buyer_wallet_id": s.buyer}),
        422,
        "number_invalid",
    ),
]


@pytest.mark.parametrize(("name", "make", "status", "code"), _CASES, ids=[c[0] for c in _CASES])
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient, name: str, make: Make, status: int, code: str
) -> None:
    scenario = Scenario(api)
    before = api.snapshot()
    version = api.state()["version"]
    path, body = make(scenario)
    r = api.mutate("POST", path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


# --- 一致性檢查：竄改後下一個命令整筆拒絕 ---------------------------------------------


_ACCEPTED = "(SELECT id FROM service WHERE status = 'accepted')"


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        (f"UPDATE service SET paid_minor = 50 WHERE id = {_ACCEPTED}", "service_invalid"),
        (f"UPDATE service SET status = 'submitted' WHERE id = {_ACCEPTED}", "service_invalid"),
        ("UPDATE service SET status = 'bogus' WHERE status = 'draft'", "service_invalid"),
        ("UPDATE service SET legal_confirmation = TRUE WHERE status = 'draft'", "service_invalid"),
        (
            f"UPDATE service SET amount_minor = 50, paid_minor = 100 WHERE id = {_ACCEPTED}",
            "service_invalid",
        ),
        ("UPDATE service SET amount_minor = -1 WHERE status = 'draft'", "number_invalid"),
        ("UPDATE service SET case_id = gen_random_uuid()", "record_missing"),
        ("UPDATE service_delivery SET artifact_ref = 'tampered'", "delivery_invalid"),
        ("UPDATE service_delivery SET digest = 'x'", "delivery_invalid"),
        ("UPDATE service_delivery SET revision = 0", "number_invalid"),
        (
            "UPDATE service SET latest_delivery_id = NULL WHERE latest_delivery_id IS NOT NULL",
            "delivery_invalid",
        ),
        (
            "UPDATE service SET latest_delivery_id = gen_random_uuid() WHERE status = 'draft'",
            "delivery_invalid",
        ),
        # 服務付款流水：參照不存在的服務、或付款來源不是買家
        (
            "UPDATE ledger SET reference_id = gen_random_uuid() WHERE kind = 'service.pay'",
            "record_missing",
        ),
        (
            "UPDATE ledger_entry SET wallet_id = (SELECT id FROM wallet WHERE kind = 'supplier')"
            " WHERE amount_minor < 0 AND ledger_id IN"
            " (SELECT id FROM ledger WHERE kind = 'service.pay')",
            "ledger_invalid",
        ),
    ],
)
def test_tampered_services_rejected(api: ApiClient, db_engine: Engine, sql: str, code: str) -> None:
    Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(text(sql))
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", "/api/v1/crm/customers", {"name": "x"})
    assert r.json()["error"]["code"] == code, r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_service_record_limit(api: ApiClient, db_engine: Engine) -> None:
    api.setup()
    case = _case(api)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO service (id, workspace_id, case_id, title, source_case_title,"
                " price_source, amount_minor, status, created_at, updated_at)"
                " SELECT gen_random_uuid(), w.id, :case, 't', 't', 'explicit_simulation_input',"
                " 1, 'draft', now(), now() FROM workspace w, generate_series(1, 499)"
            ),
            {"case": case},
        )
    before = api.snapshot()
    assert len(before["services"]) == 500
    r = api.mutate("POST", SERVICES, {"case_id": case, "amount_minor": 1})
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before


# --- 快照還原與清除 ---------------------------------------------------------------


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    Scenario(api)
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = SERVICES_SPEC.snapshot(db, ctx.workspace_id)
        assert len(before["services"]) == 5
        assert sum(len(s["deliveries"]) for s in before["services"]) == 4
        db.execute(text("DELETE FROM service"))
        empty = SERVICES_SPEC.snapshot(db, ctx.workspace_id)
        assert empty == {"services": []}
        SERVICES_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert SERVICES_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()


def test_clear_cascades_services(api: ApiClient, db_engine: Engine) -> None:
    Scenario(api)
    api.ok("POST", "/api/v1/workspace/clear", {})
    with db_engine.connect() as conn:
        for table in ("service", "service_delivery"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
