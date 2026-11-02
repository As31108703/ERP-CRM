"""CRM：客戶、聯絡人、商機、案件的通用紀錄、商機跟進、報價（建立、發出取代舊版、摘要確認），
以及參照、失單原因、報價的一致性檢查與快照還原。"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.config.settings import Settings
from src.core import clock
from src.core.canonical import digest
from src.modules.catalog.templates import TEMPLATES
from src.modules.crm.router import SPEC as CRM_SPEC
from tests.helpers import ApiClient, workspace_ctx

CRM = "/api/v1/crm"
QUOTES = f"{CRM}/quotes"
FAR = "2099-12-31T00:00:00.000Z"
RECORD_KEYS = {
    "id",
    "name",
    "title",
    "customer_id",
    "case_id",
    "status",
    "notes",
    "lost_reason",
    "due_at",
    "email",
    "phone",
    "amount_minor",
    "created_at",
    "updated_at",
}


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _row(ws: dict[str, Any], collection: str, row_id: str) -> dict[str, Any]:
    return next(x for x in ws[collection] if x["id"] == row_id)


def _create(api: ApiClient, collection: str, body: dict[str, Any]) -> str:
    return api.ok("POST", f"{CRM}/{collection}", body)["result"]


def _quote(api: ApiClient, case_id: str, amount: int = 1000, expires_at: str = FAR) -> str:
    body = {"case_id": case_id, "amount_minor": amount, "expires_at": expires_at}
    return api.ok("POST", QUOTES, body)["result"]


def _issue(api: ApiClient, quote_id: str) -> None:
    api.ok("POST", f"{QUOTES}/{quote_id}/issue", {})


# --- seed -----------------------------------------------------------------------


@pytest.mark.parametrize("industry", ["retail", "service", "general"])
def test_seed_crm(api: ApiClient, industry: str) -> None:
    api.setup(industry)
    sample = TEMPLATES[industry].sample
    ws = api.snapshot()
    [customer] = ws["customers"]
    assert customer["name"] == sample.customer
    assert set(customer) == RECORD_KEYS
    [case] = ws["cases"]
    assert {k: case[k] for k in ("title", "customer_id", "status")} == {
        "title": sample.service,
        "customer_id": customer["id"],
        "status": "open",
    }
    [deal] = ws["deals"]
    assert {k: deal[k] for k in ("name", "customer_id", "status", "notes", "followups")} == {
        "name": sample.service,
        "customer_id": customer["id"],
        "status": "new",
        "notes": "這是可清除的產業示範商機",
        "followups": [],
    }
    assert ws["contacts"] == []
    assert ws["quotes"] == []
    assert ws["tasks"] == [] and ws["milestones"] == []
    assert len(ws["history"]) == 0


def test_seed_customer_without_crm(api: ApiClient) -> None:
    api.setup("retail", modules=["inventory"])
    ws = api.snapshot()
    assert [c["name"] for c in ws["customers"]] == [TEMPLATES["retail"].sample.customer]
    assert ws["cases"] == [] and ws["deals"] == []


# --- 通用紀錄 ---------------------------------------------------------------------


def test_generic_create_and_update(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    customer = ws["customers"][0]["id"]
    cid = _create(
        api,
        "contacts",
        {
            "id": "ignored",
            "name": "王小明",
            "customer_id": customer,
            "email": "",
            "phone": "0900",
            "due_at": "2026-12-01T08:00:00+08:00",
            "amount_minor": 5.0,
        },
    )
    assert cid != "ignored"
    row = _row(api.snapshot(), "contacts", cid)
    assert set(row) == RECORD_KEYS
    assert row["name"] == "王小明"
    assert row["customer_id"] == customer
    assert row["email"] == ""
    assert row["due_at"] == "2026-12-01T00:00:00.000Z"
    assert row["amount_minor"] == 5
    assert row["title"] is None
    r = api.ok("PATCH", f"{CRM}/contacts/{cid}", {"id": "other", "phone": None, "notes": "備註"})
    assert r["result"] == cid
    updated = _row(api.snapshot(), "contacts", cid)
    assert updated["phone"] is None and updated["notes"] == "備註"
    assert updated["name"] == "王小明"
    assert updated["created_at"] == row["created_at"]
    assert api.snapshot()["history"][-1]["action"] == "contact.update"
    # 商機階段以 deal.update 改 status；status 可以是任意字串
    deal = ws["deals"][0]["id"]
    api.ok("PATCH", f"{CRM}/deals/{deal}", {"status": "proposal"})
    assert _row(api.snapshot(), "deals", deal)["status"] == "proposal"
    case = _create(api, "cases", {"title": "新案件", "customer_id": customer})
    assert _row(api.snapshot(), "cases", case)["title"] == "新案件"
    new_customer = _create(api, "customers", {"name": "新客戶"})
    assert _row(api.snapshot(), "customers", new_customer)["name"] == "新客戶"


def test_deal_lost_requires_reason(api: ApiClient) -> None:
    api.setup()
    deal = api.snapshot()["deals"][0]["id"]
    before = api.snapshot()
    version = api.state()["version"]
    for body in ({"status": "lost"}, {"status": "lost", "lost_reason": "   "}):
        r = api.mutate("PATCH", f"{CRM}/deals/{deal}", body)
        assert _error(r) == (422, "lost_reason_required")
    r = api.mutate("POST", f"{CRM}/deals", {"name": "x", "status": "lost"})
    assert _error(r) == (422, "lost_reason_required")
    assert api.snapshot() == before
    assert api.state()["version"] == version
    api.ok("PATCH", f"{CRM}/deals/{deal}", {"status": "lost", "lost_reason": "預算不足"})
    assert _row(api.snapshot(), "deals", deal)["lost_reason"] == "預算不足"
    # 已失單的商機清空原因：由一致性檢查擋下
    before = api.snapshot()
    r = api.mutate("PATCH", f"{CRM}/deals/{deal}", {"lost_reason": ""})
    assert _error(r) == (422, "lost_reason_required")
    assert api.snapshot() == before


def test_dangling_customer_404(api: ApiClient) -> None:
    api.setup()
    ws = api.snapshot()
    deal = ws["deals"][0]["id"]
    customer = ws["customers"][0]["id"]
    version = api.state()["version"]
    missing = "00000000-0000-4000-8000-000000000000"
    for method, path, body in (
        ("POST", f"{CRM}/contacts", {"name": "x", "customer_id": missing}),
        ("PATCH", f"{CRM}/deals/{deal}", {"customer_id": missing}),
        ("POST", f"{CRM}/cases", {"title": "x", "customer_id": "not-a-uuid"}),
        ("POST", f"{CRM}/contacts", {"name": "x", "case_id": missing}),
        # 參照必須是對應集合的紀錄：把商機 id 當成客戶也不行
        ("POST", f"{CRM}/contacts", {"name": "x", "customer_id": deal}),
    ):
        r = api.mutate(method, path, body)
        assert _error(r) == (404, "record_missing"), (path, body)
    assert api.snapshot() == ws
    assert api.state()["version"] == version
    # 空字串與 null 代表沒有參照
    cid = _create(api, "contacts", {"name": "y", "customer_id": "", "case_id": None})
    assert _row(api.snapshot(), "contacts", cid)["customer_id"] is None
    api.ok("PATCH", f"{CRM}/contacts/{cid}", {"customer_id": customer})


def test_followup_appends(api: ApiClient) -> None:
    api.setup()
    deal = api.snapshot()["deals"][0]["id"]
    r = api.ok("POST", f"{CRM}/deals/{deal}/followups", {"note": "已電話聯繫"})
    assert r["result"] == deal
    api.ok("POST", f"{CRM}/deals/{deal}/followups", {"note": ""})
    api.ok("POST", f"{CRM}/deals/{deal}/followups", {"note": "長" * 2000})
    followups = _row(api.snapshot(), "deals", deal)["followups"]
    assert [f["note"] for f in followups] == ["已電話聯繫", "", "長" * 2000]
    assert all(set(f) == {"id", "note", "created_at"} for f in followups)
    assert len({f["id"] for f in followups}) == 3
    assert api.snapshot()["history"][-1]["action"] == "followup.create"


# --- 報價 -----------------------------------------------------------------------


def test_quote_create_and_issue(api: ApiClient) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    qid = _quote(api, case, 2500, "2099-12-31T08:00:00+08:00")
    q = _row(api.snapshot(), "quotes", qid)
    assert set(q) == {
        "id",
        "case_id",
        "amount_minor",
        "expires_at",
        "status",
        "digest",
        "issued_at",
        "created_at",
        "updated_at",
        "legal_confirmation",
    }
    assert {k: q[k] for k in ("case_id", "amount_minor", "expires_at", "status")} == {
        "case_id": case,
        "amount_minor": 2500,
        "expires_at": "2099-12-31T00:00:00.000Z",
        "status": "draft",
    }
    assert q["digest"] is None and q["issued_at"] is None and q["legal_confirmation"] is False
    _issue(api, qid)
    q = _row(api.snapshot(), "quotes", qid)
    assert q["status"] == "issued"
    assert q["issued_at"] is not None
    assert q["digest"] == digest(
        {"id": qid, "case_id": case, "amount_minor": 2500, "expires_at": q["expires_at"]}
    )


def test_issue_supersedes_previous(api: ApiClient) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    other_case = _create(api, "cases", {"title": "另一案"})
    first = _quote(api, case)
    _issue(api, first)
    elsewhere = _quote(api, other_case)
    _issue(api, elsewhere)
    second = _quote(api, case, 2000)
    _issue(api, second)
    ws = api.snapshot()
    assert _row(ws, "quotes", first)["status"] == "superseded"
    assert _row(ws, "quotes", second)["status"] == "issued"
    assert _row(ws, "quotes", elsewhere)["status"] == "issued"
    # 已發出或已被取代的報價不能再發出
    for qid in (first, second):
        before = api.snapshot()
        r = api.mutate("POST", f"{QUOTES}/{qid}/issue", {})
        assert _error(r) == (409, "quote_immutable")
        assert api.snapshot() == before


def test_confirm_success(api: ApiClient) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    qid = _quote(api, case)
    _issue(api, qid)
    d = _row(api.snapshot(), "quotes", qid)["digest"]
    r = api.ok("POST", f"{QUOTES}/{qid}/confirm", {"digest": d})
    assert r["result"] == qid
    q = _row(api.snapshot(), "quotes", qid)
    assert q["status"] == "simulated_confirmed"
    assert q["legal_confirmation"] is False


def test_confirm_with_wrong_digest_409_quote_outdated(api: ApiClient) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    old = _quote(api, case)
    _issue(api, old)
    old_digest = _row(api.snapshot(), "quotes", old)["digest"]
    new = _quote(api, case, 3000)
    _issue(api, new)
    before = api.snapshot()
    version = api.state()["version"]
    for qid, body in (
        (new, {"digest": "0" * 64}),
        (new, {"digest": old_digest}),
        (new, {}),
        # 被取代的舊版就算摘要正確也不能確認
        (old, {"digest": old_digest}),
    ):
        r = api.mutate("POST", f"{QUOTES}/{qid}/confirm", body)
        assert _error(r) == (409, "quote_outdated")
    # 草稿也不能確認
    draft = _quote(api, case)
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{QUOTES}/{draft}/confirm", {"digest": None})
    assert _error(r) == (409, "quote_outdated")
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_confirm_expired_409(api: ApiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    api.setup()
    case = api.snapshot()["cases"][0]["id"]
    qid = _quote(api, case, expires_at="2030-01-01T00:00:00Z")
    _issue(api, qid)
    d = _row(api.snapshot(), "quotes", qid)["digest"]
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2030, 1, 1, tzinfo=UTC))
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{QUOTES}/{qid}/confirm", {"digest": d})
    assert _error(r) == (409, "quote_outdated")
    assert api.snapshot() == before
    assert api.state()["version"] == version
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2029, 12, 31, 23, 59, tzinfo=UTC))
    api.ok("POST", f"{QUOTES}/{qid}/confirm", {"digest": d})


# --- 模組閘 ---------------------------------------------------------------------


def test_crm_disabled_403_module_disabled(api: ApiClient) -> None:
    api.setup("retail", modules=["inventory"])
    ws = api.snapshot()
    customer = ws["customers"][0]["id"]
    version = api.state()["version"]
    for method, path, body in (
        ("POST", f"{CRM}/customers", {"name": "x"}),
        ("PATCH", f"{CRM}/customers/{customer}", {"name": "x"}),
        ("POST", f"{CRM}/contacts", {"name": "x"}),
        ("POST", f"{CRM}/deals", {"name": "x"}),
        ("POST", f"{CRM}/cases", {"title": "x"}),
        ("POST", f"{CRM}/deals/{customer}/followups", {"note": "x"}),
        ("POST", QUOTES, {"case_id": customer, "amount_minor": 1, "expires_at": FAR}),
        ("POST", f"{QUOTES}/{customer}/issue", {}),
        ("POST", f"{QUOTES}/{customer}/confirm", {"digest": "x"}),
        # 禁用鍵名與模組未啟用同時成立時，模組閘優先
        ("POST", f"{CRM}/customers", {"bank_name": "x"}),
    ):
        r = api.mutate(method, path, body)
        assert _error(r) == (403, "module_disabled"), path
    assert api.snapshot() == ws
    assert api.state()["version"] == version


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


class Scenario:
    """示範客戶、案件 K 與商機 D（皆為 seed），K 上有草稿報價 Q。"""

    def __init__(self, api: ApiClient) -> None:
        api.setup()
        ws = api.snapshot()
        self.customer = ws["customers"][0]["id"]
        self.case = ws["cases"][0]["id"]
        self.deal = ws["deals"][0]["id"]
        self.quote = _quote(api, self.case)


Make = Callable[[Scenario], tuple[str, str, Any]]
MISSING = "00000000-0000-4000-8000-000000000000"

_CASES: list[tuple[str, Make, int, str]] = [
    # B§3.1 通用前置檢查
    ("payload_list", lambda s: ("POST", f"{CRM}/customers", [1]), 422, "payload_invalid"),
    (
        "forbidden_key",
        lambda s: ("POST", f"{CRM}/customers", {"name": "x", "payer": "x"}),
        422,
        "simulation_required",
    ),
    (
        "forbidden_legal_confirmation",
        lambda s: ("POST", f"{QUOTES}/{s.quote}/confirm", {"legal_confirmation": True}),
        422,
        "simulation_required",
    ),
    (
        "protected_field",
        lambda s: ("PATCH", f"{CRM}/deals/{s.deal}", {"currency": "SIM"}),
        422,
        "protected_field",
    ),
    (
        "learning_id",
        lambda s: ("POST", f"{CRM}/contacts", {"learning_run_id": "run-abcdef01"}),
        422,
        "learning_id_invalid",
    ),
    (
        "amount_zero",
        lambda s: ("POST", f"{CRM}/deals", {"name": "x", "amount_minor": 0}),
        422,
        "number_invalid",
    ),
    # B§3.2 通用紀錄
    (
        "fields_invalid",
        lambda s: ("POST", f"{CRM}/customers", {"name": "x", "vip": True}),
        422,
        "fields_invalid",
    ),
    (
        "fields_invalid_update",
        lambda s: ("PATCH", f"{CRM}/cases/{s.case}", {"followups": []}),
        422,
        "fields_invalid",
    ),
    (
        "field_type",
        lambda s: ("POST", f"{CRM}/customers", {"name": 123}),
        422,
        "fields_invalid",
    ),
    (
        "due_at_invalid",
        lambda s: ("POST", f"{CRM}/cases", {"title": "x", "due_at": "明天"}),
        422,
        "fields_invalid",
    ),
    (
        "text_limit",
        lambda s: ("POST", f"{CRM}/customers", {"notes": "x" * 3990}),
        422,
        "text_limit",
    ),
    (
        "text_limit_utf16",
        # 「𝄞」在 JavaScript 字串長度為 2
        lambda s: ("POST", f"{CRM}/customers", {"notes": "𝄞" * 1995}),
        422,
        "text_limit",
    ),
    (
        "lost_without_reason",
        lambda s: ("PATCH", f"{CRM}/deals/{s.deal}", {"status": "lost"}),
        422,
        "lost_reason_required",
    ),
    (
        "update_missing",
        lambda s: ("PATCH", f"{CRM}/contacts/{MISSING}", {"name": "x"}),
        404,
        "record_missing",
    ),
    (
        "update_wrong_collection",
        lambda s: ("PATCH", f"{CRM}/contacts/{s.deal}", {"name": "x"}),
        404,
        "record_missing",
    ),
    (
        "update_bad_id",
        lambda s: ("PATCH", f"{CRM}/customers/not-a-uuid", {"name": "x"}),
        404,
        "record_missing",
    ),
    (
        "dangling_case",
        lambda s: ("PATCH", f"{CRM}/deals/{s.deal}", {"case_id": MISSING}),
        404,
        "record_missing",
    ),
    # B§3.3 跟進
    (
        "followup_deal_missing",
        lambda s: ("POST", f"{CRM}/deals/{s.case}/followups", {"note": "x"}),
        404,
        "record_missing",
    ),
    (
        "followup_note_missing",
        lambda s: ("POST", f"{CRM}/deals/{s.deal}/followups", {}),
        422,
        "note_invalid",
    ),
    (
        "followup_note_type",
        lambda s: ("POST", f"{CRM}/deals/{s.deal}/followups", {"note": 1}),
        422,
        "note_invalid",
    ),
    (
        "followup_note_long",
        lambda s: ("POST", f"{CRM}/deals/{s.deal}/followups", {"note": "x" * 2001}),
        422,
        "note_invalid",
    ),
    # B§3.4 報價
    (
        "quote_case_missing",
        lambda s: ("POST", QUOTES, {"case_id": MISSING, "amount_minor": 1, "expires_at": FAR}),
        404,
        "record_missing",
    ),
    (
        "quote_case_is_deal",
        lambda s: ("POST", QUOTES, {"case_id": s.deal, "amount_minor": 1, "expires_at": FAR}),
        404,
        "record_missing",
    ),
    (
        "quote_amount_missing",
        lambda s: ("POST", QUOTES, {"case_id": s.case, "expires_at": FAR}),
        422,
        "number_invalid",
    ),
    (
        "quote_amount_zero",
        lambda s: ("POST", QUOTES, {"case_id": s.case, "amount_minor": 0, "expires_at": FAR}),
        422,
        "number_invalid",
    ),
    (
        "quote_expiry_missing",
        lambda s: ("POST", QUOTES, {"case_id": s.case, "amount_minor": 1}),
        422,
        "expiry_invalid",
    ),
    (
        "quote_expiry_invalid",
        lambda s: ("POST", QUOTES, {"case_id": s.case, "amount_minor": 1, "expires_at": "x"}),
        422,
        "expiry_invalid",
    ),
    (
        "quote_expiry_type",
        lambda s: ("POST", QUOTES, {"case_id": s.case, "amount_minor": 1, "expires_at": 1}),
        422,
        "expiry_invalid",
    ),
    (
        "issue_missing",
        lambda s: ("POST", f"{QUOTES}/{MISSING}/issue", {}),
        404,
        "record_missing",
    ),
    (
        "confirm_missing",
        lambda s: ("POST", f"{QUOTES}/{MISSING}/confirm", {"digest": "x"}),
        404,
        "record_missing",
    ),
    (
        "confirm_draft",
        lambda s: ("POST", f"{QUOTES}/{s.quote}/confirm", {"digest": None}),
        409,
        "quote_outdated",
    ),
]


@pytest.mark.parametrize(("name", "make", "status", "code"), _CASES, ids=[c[0] for c in _CASES])
def test_rejections_leave_snapshot_unchanged(
    api: ApiClient, name: str, make: Make, status: int, code: str
) -> None:
    scenario = Scenario(api)
    before = api.snapshot()
    version = api.state()["version"]
    method, path, body = make(scenario)
    r = api.mutate(method, path, body)
    assert _error(r) == (status, code), r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


# --- 一致性檢查：竄改後下一個命令整筆拒絕 ---------------------------------------------


def _issued_scenario(api: ApiClient) -> Scenario:
    s = Scenario(api)
    _issue(api, s.quote)
    return s


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        (
            "UPDATE crm_record SET status = 'lost', lost_reason = NULL WHERE collection = 'deals'",
            "lost_reason_required",
        ),
        (
            "UPDATE crm_record SET status = 'lost', lost_reason = ' ' WHERE collection = 'deals'",
            "lost_reason_required",
        ),
        ("UPDATE crm_record SET customer_id = gen_random_uuid()", "record_missing"),
        (
            "UPDATE crm_record SET case_id = (SELECT id FROM crm_record WHERE collection = "
            "'deals') WHERE collection = 'cases'",
            "record_missing",
        ),
        ("UPDATE quote SET case_id = gen_random_uuid()", "record_missing"),
        (
            "INSERT INTO quote (id, workspace_id, case_id, amount_minor, expires_at, status,"
            " digest, issued_at, created_at, updated_at)"
            " SELECT gen_random_uuid(), workspace_id, case_id, amount_minor, expires_at, status,"
            " digest, issued_at, created_at, updated_at FROM quote",
            "quote_invalid",
        ),
        ("UPDATE quote SET amount_minor = amount_minor + 1", "quote_invalid"),
        ("UPDATE quote SET digest = NULL", "quote_invalid"),
        ("UPDATE quote SET status = 'bogus'", "quote_invalid"),
        ("UPDATE quote SET legal_confirmation = TRUE", "quote_invalid"),
        ("UPDATE quote SET amount_minor = -1, status = 'draft', digest = NULL", "number_invalid"),
    ],
)
def test_tampered_crm_rejected(api: ApiClient, db_engine: Engine, sql: str, code: str) -> None:
    _issued_scenario(api)
    with db_engine.begin() as conn:
        conn.execute(text(sql))
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{CRM}/customers", {"name": "x"})
    assert r.json()["error"]["code"] == code, r.text
    assert api.snapshot() == before
    assert api.state()["version"] == version


def test_draft_quote_needs_no_digest(api: ApiClient, db_engine: Engine) -> None:
    Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE quote SET amount_minor = amount_minor + 1"))
    api.ok("POST", f"{CRM}/customers", {"name": "x"})


@pytest.mark.parametrize(("collection", "table"), [("contacts", "crm_record"), (None, "quote")])
def test_crm_record_limit(
    api: ApiClient, db_engine: Engine, collection: str | None, table: str
) -> None:
    s = Scenario(api)
    with db_engine.begin() as conn:
        if table == "crm_record":
            conn.execute(
                text(
                    "INSERT INTO crm_record (id, workspace_id, collection, name, created_at,"
                    " updated_at) SELECT gen_random_uuid(), w.id, :c, 'x', now(), now()"
                    " FROM workspace w, generate_series(1, 500)"
                ),
                {"c": collection},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO quote (id, workspace_id, case_id, amount_minor, expires_at,"
                    " status, created_at, updated_at) SELECT gen_random_uuid(), w.id, :case,"
                    " 1, now(), 'draft', now(), now() FROM workspace w, generate_series(1, 499)"
                ),
                {"case": s.case},
            )
    before = api.snapshot()
    if table == "crm_record":
        r = api.mutate("POST", f"{CRM}/contacts", {"name": "x"})
    else:
        r = api.mutate("POST", QUOTES, {"case_id": s.case, "amount_minor": 1, "expires_at": FAR})
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before
    # 其他集合不受影響
    if table == "crm_record":
        api.ok("POST", f"{CRM}/customers", {"name": "y"})


# --- 快照還原與清除 ---------------------------------------------------------------


def test_snapshot_restore_roundtrip(
    api: ApiClient, db_engine: Engine, test_settings: Settings
) -> None:
    s = _issued_scenario(api)
    api.ok("POST", f"{CRM}/deals/{s.deal}/followups", {"note": "第一次"})
    api.ok("POST", f"{CRM}/deals/{s.deal}/followups", {"note": "第二次"})
    _create(api, "contacts", {"name": "甲", "customer_id": s.customer, "due_at": FAR})
    _create(api, "contacts", {"name": "乙", "case_id": s.case, "amount_minor": 7})
    second = _quote(api, s.case)
    _issue(api, second)
    third = _quote(api, s.case)
    _issue(api, third)
    api.ok(
        "POST",
        f"{QUOTES}/{third}/confirm",
        {"digest": _row(api.snapshot(), "quotes", third)["digest"]},
    )
    with Session(db_engine) as db:
        ctx = workspace_ctx(db, test_settings)
        before = CRM_SPEC.snapshot(db, ctx.workspace_id)
        assert len(before["contacts"]) == 2
        assert len(before["quotes"]) == 3
        assert len(before["deals"][0]["followups"]) == 2
        db.execute(text("DELETE FROM quote"))
        db.execute(text("DELETE FROM crm_record"))
        empty = CRM_SPEC.snapshot(db, ctx.workspace_id)
        assert all(v == [] for v in empty.values())
        assert set(empty) == {
            "customers",
            "contacts",
            "deals",
            "cases",
            "tasks",
            "milestones",
            "quotes",
        }
        CRM_SPEC.restore(db, ctx.workspace_id, before)
        db.flush()
        assert CRM_SPEC.snapshot(db, ctx.workspace_id) == before
        db.rollback()


def test_clear_cascades_crm(api: ApiClient, db_engine: Engine) -> None:
    s = _issued_scenario(api)
    api.ok("POST", f"{CRM}/deals/{s.deal}/followups", {"note": "x"})
    api.ok("POST", "/api/v1/workspace/clear", {})
    with db_engine.connect() as conn:
        for table in ("crm_record", "deal_followup", "quote"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
