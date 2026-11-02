"""專案任務與里程碑：通用紀錄（B§3.2）的 task／milestone 建立與更新、模組閘、範本示範資料，
以及錯誤碼、筆數上限與參照的一致性檢查。資料存在 crm 的通用紀錄表，快照鍵為 tasks、milestones。"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from src.modules.catalog.templates import TEMPLATES
from tests.helpers import ApiClient

PROJECTS = "/api/v1/projects"
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
MISSING = "00000000-0000-4000-8000-000000000000"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _row(ws: dict[str, Any], collection: str, record_id: str) -> dict[str, Any]:
    return next(r for r in ws[collection] if r["id"] == record_id)


def _create(api: ApiClient, collection: str, body: dict[str, Any]) -> str:
    return api.ok("POST", f"{PROJECTS}/{collection}", body)["result"]


# --- seed -----------------------------------------------------------------------


def test_seed_projects_template(api: ApiClient) -> None:
    api.setup("projects")
    ws = api.snapshot()
    [task] = ws["tasks"]
    [milestone] = ws["milestones"]
    assert set(task) == RECORD_KEYS and set(milestone) == RECORD_KEYS
    assert task["title"] == "確認需求與交付範圍"
    assert task["status"] == "todo"
    assert milestone["title"] == TEMPLATES["projects"].sample.milestone == "原型驗收"
    assert milestone["status"] == "planned"
    # 只有 title 與 status，其他欄位都是 null
    for row in (task, milestone):
        assert all(
            row[k] is None
            for k in RECORD_KEYS - {"id", "title", "status"} - {"created_at", "updated_at"}
        )
    assert len(ws["history"]) == 0


@pytest.mark.parametrize("industry", ["service", "general"])
def test_seed_fallback_titles(api: ApiClient, industry: str) -> None:
    """範本沒有 sample.task／sample.milestone 時用「確認需求」與「原型驗收」。"""
    assert TEMPLATES[industry].sample.task is None
    assert TEMPLATES[industry].sample.milestone is None
    api.setup(industry)
    ws = api.snapshot()
    assert [(t["title"], t["status"]) for t in ws["tasks"]] == [("確認需求", "todo")]
    assert [(m["title"], m["status"]) for m in ws["milestones"]] == [("原型驗收", "planned")]


def test_seed_skipped_without_projects(api: ApiClient) -> None:
    api.setup("projects", modules=["services", "wallets", "crm"])
    ws = api.snapshot()
    assert ws["tasks"] == [] and ws["milestones"] == []


# --- 建立與更新 -------------------------------------------------------------------


def test_task_crud(api: ApiClient) -> None:
    api.setup("projects")
    ws = api.snapshot()
    case = ws["cases"][0]["id"]
    customer = ws["customers"][0]["id"]
    tid = _create(
        api,
        "tasks",
        {
            "id": "ignored",
            "title": "撰寫規格",
            "status": "todo",
            "case_id": case,
            "customer_id": customer,
            "due_at": "2026-12-01T08:00:00+08:00",
            "notes": "第一版",
        },
    )
    assert tid != "ignored"
    ws = api.snapshot()
    assert ws["history"][-1]["action"] == "task.create"
    row = _row(ws, "tasks", tid)
    assert set(row) == RECORD_KEYS
    assert row["title"] == "撰寫規格"
    assert row["status"] == "todo"
    assert row["case_id"] == case and row["customer_id"] == customer
    assert row["due_at"] == "2026-12-01T00:00:00.000Z"
    assert row["notes"] == "第一版"
    # 任務不會出現在其他集合
    assert all(r["id"] != tid for r in ws["milestones"] + ws["cases"])

    r = api.ok(
        "PATCH", f"{PROJECTS}/tasks/{tid}", {"id": "other", "status": "done", "due_at": None}
    )
    assert r["result"] == tid
    ws = api.snapshot()
    assert ws["history"][-1]["action"] == "task.update"
    updated = _row(ws, "tasks", tid)
    assert updated["status"] == "done"
    assert updated["due_at"] is None
    assert updated["title"] == "撰寫規格" and updated["notes"] == "第一版"
    assert updated["created_at"] == row["created_at"]
    # 只有日期的 ISO 字串視為 UTC 午夜
    api.ok("PATCH", f"{PROJECTS}/tasks/{tid}", {"due_at": "2027-01-15"})
    assert _row(api.snapshot(), "tasks", tid)["due_at"] == "2027-01-15T00:00:00.000Z"


def test_milestone_crud(api: ApiClient) -> None:
    api.setup("projects")
    mid = _create(
        api, "milestones", {"title": "上線", "status": "planned", "due_at": "2027-03-01T00:00:00Z"}
    )
    ws = api.snapshot()
    assert ws["history"][-1]["action"] == "milestone.create"
    row = _row(ws, "milestones", mid)
    assert (row["title"], row["status"], row["due_at"]) == (
        "上線",
        "planned",
        "2027-03-01T00:00:00.000Z",
    )
    api.ok("PATCH", f"{PROJECTS}/milestones/{mid}", {"status": "achieved", "case_id": ""})
    ws = api.snapshot()
    assert ws["history"][-1]["action"] == "milestone.update"
    updated = _row(ws, "milestones", mid)
    assert updated["status"] == "achieved" and updated["case_id"] is None
    assert updated["due_at"] == "2027-03-01T00:00:00.000Z"


def test_seeded_task_updatable(api: ApiClient) -> None:
    api.setup("projects")
    task = api.snapshot()["tasks"][0]["id"]
    api.ok("PATCH", f"{PROJECTS}/tasks/{task}", {"status": "in_progress"})
    assert _row(api.snapshot(), "tasks", task)["status"] == "in_progress"


def test_projects_without_crm(api: ApiClient) -> None:
    """projects 不依賴 crm：沒有啟用 crm 時也能建立任務與里程碑。"""
    api.setup("general", modules=["projects"])
    _create(api, "tasks", {"title": "x"})
    _create(api, "milestones", {"title": "y"})
    ws = api.snapshot()
    assert len(ws["tasks"]) == 2 and len(ws["milestones"]) == 2


# --- 模組閘 ---------------------------------------------------------------------


def test_projects_disabled_403(api: ApiClient) -> None:
    api.setup("projects", modules=["services", "wallets", "crm"])
    ws = api.snapshot()
    case = ws["cases"][0]["id"]
    version = api.state()["version"]
    for method, path, body in (
        ("POST", f"{PROJECTS}/tasks", {"title": "x"}),
        ("PATCH", f"{PROJECTS}/tasks/{case}", {"title": "x"}),
        ("POST", f"{PROJECTS}/milestones", {"title": "x"}),
        ("PATCH", f"{PROJECTS}/milestones/{case}", {"title": "x"}),
        # 禁用鍵名與模組未啟用同時成立時，模組閘優先
        ("POST", f"{PROJECTS}/tasks", {"finance_note": "x"}),
    ):
        r = api.mutate(method, path, body)
        assert _error(r) == (403, "module_disabled"), path
    assert api.snapshot() == ws
    assert api.state()["version"] == version


# --- 錯誤碼：每一案都不改變快照與版本 ---------------------------------------------


class Scenario:
    """projects 範本：示範客戶、案件 K、商機 D、任務 T 與里程碑 M（皆為 seed）。"""

    def __init__(self, api: ApiClient) -> None:
        api.setup("projects")
        ws = api.snapshot()
        self.customer = ws["customers"][0]["id"]
        self.case = ws["cases"][0]["id"]
        self.deal = ws["deals"][0]["id"]
        self.task = ws["tasks"][0]["id"]
        self.milestone = ws["milestones"][0]["id"]


Make = Callable[[Scenario], tuple[str, str, Any]]
TASKS = f"{PROJECTS}/tasks"
MILESTONES = f"{PROJECTS}/milestones"

_CASES: list[tuple[str, Make, int, str]] = [
    # B§3.1 通用前置檢查
    ("payload_list", lambda s: ("POST", TASKS, [1]), 422, "payload_invalid"),
    (
        "forbidden_key",
        lambda s: ("POST", TASKS, {"title": "x", "bank_account": "x"}),
        422,
        "simulation_required",
    ),
    (
        "forbidden_key_update",
        lambda s: ("PATCH", f"{MILESTONES}/{s.milestone}", {"payment_url": "x"}),
        422,
        "simulation_required",
    ),
    (
        "protected_field",
        lambda s: ("PATCH", f"{TASKS}/{s.task}", {"currency": "SIM"}),
        422,
        "protected_field",
    ),
    (
        "learning_id",
        lambda s: ("POST", MILESTONES, {"learning_run_id": "run-abcdef01"}),
        422,
        "learning_id_invalid",
    ),
    (
        "amount_zero",
        lambda s: ("POST", TASKS, {"title": "x", "amount_minor": 0}),
        422,
        "number_invalid",
    ),
    (
        "amount_fraction",
        lambda s: ("PATCH", f"{TASKS}/{s.task}", {"amount_minor": 1.5}),
        422,
        "number_invalid",
    ),
    (
        "quantity_zero",
        lambda s: ("POST", MILESTONES, {"title": "x", "quantity": 0}),
        422,
        "number_invalid",
    ),
    (
        "lines_empty",
        lambda s: ("POST", TASKS, {"title": "x", "lines": []}),
        422,
        "lines_invalid",
    ),
    # B§3.2 通用紀錄
    (
        "unknown_key",
        lambda s: ("POST", TASKS, {"title": "x", "priority": "high"}),
        422,
        "fields_invalid",
    ),
    (
        "unknown_key_update",
        lambda s: ("PATCH", f"{MILESTONES}/{s.milestone}", {"owner": "x"}),
        422,
        "fields_invalid",
    ),
    (
        "title_not_string",
        lambda s: ("POST", TASKS, {"title": 5}),
        422,
        "fields_invalid",
    ),
    (
        "due_at_unparseable",
        lambda s: ("POST", TASKS, {"title": "x", "due_at": "下週一"}),
        422,
        "fields_invalid",
    ),
    (
        "due_at_number",
        lambda s: ("PATCH", f"{MILESTONES}/{s.milestone}", {"due_at": 20270101}),
        422,
        "fields_invalid",
    ),
    (
        "text_limit",
        lambda s: ("POST", TASKS, {"notes": "長" * 4000}),
        422,
        "text_limit",
    ),
    (
        "lost_without_reason",
        lambda s: ("PATCH", f"{TASKS}/{s.task}", {"status": "lost"}),
        422,
        "lost_reason_required",
    ),
    (
        "lost_blank_reason",
        lambda s: ("POST", MILESTONES, {"status": "lost", "lost_reason": "  "}),
        422,
        "lost_reason_required",
    ),
    (
        "update_missing",
        lambda s: ("PATCH", f"{TASKS}/{MISSING}", {"title": "x"}),
        404,
        "record_missing",
    ),
    (
        "update_not_uuid",
        lambda s: ("PATCH", f"{MILESTONES}/not-a-uuid", {"title": "x"}),
        404,
        "record_missing",
    ),
    (
        "update_other_collection",
        lambda s: ("PATCH", f"{TASKS}/{s.milestone}", {"title": "x"}),
        404,
        "record_missing",
    ),
    (
        "update_case_as_milestone",
        lambda s: ("PATCH", f"{MILESTONES}/{s.case}", {"title": "x"}),
        404,
        "record_missing",
    ),
    # 參照由一致性檢查擋下
    (
        "dangling_case",
        lambda s: ("POST", TASKS, {"title": "x", "case_id": MISSING}),
        404,
        "record_missing",
    ),
    (
        "dangling_customer",
        lambda s: ("PATCH", f"{MILESTONES}/{s.milestone}", {"customer_id": MISSING}),
        404,
        "record_missing",
    ),
    (
        "case_ref_not_uuid",
        lambda s: ("POST", MILESTONES, {"title": "x", "case_id": "K-1"}),
        404,
        "record_missing",
    ),
    (
        "case_ref_is_deal",
        lambda s: ("PATCH", f"{TASKS}/{s.task}", {"case_id": s.deal}),
        404,
        "record_missing",
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


# --- 一致性檢查與上限 -------------------------------------------------------------


@pytest.mark.parametrize("collection", ["tasks", "milestones"])
def test_tampered_reference_rejected(api: ApiClient, db_engine: Engine, collection: str) -> None:
    Scenario(api)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE crm_record SET case_id = gen_random_uuid() WHERE collection = :c"),
            {"c": collection},
        )
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", TASKS, {"title": "x"})
    assert _error(r) == (404, "record_missing")
    assert api.snapshot() == before
    assert api.state()["version"] == version


@pytest.mark.parametrize("collection", ["tasks", "milestones"])
def test_record_limit(api: ApiClient, db_engine: Engine, collection: str) -> None:
    Scenario(api)
    # seed 已有 1 筆，再補 499 筆剛好 500 筆
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crm_record (id, workspace_id, collection, title, created_at,"
                " updated_at) SELECT gen_random_uuid(), w.id, :c, 'x', now(), now()"
                " FROM workspace w, generate_series(1, 499)"
            ),
            {"c": collection},
        )
    before = api.snapshot()
    version = api.state()["version"]
    r = api.mutate("POST", f"{PROJECTS}/{collection}", {"title": "第 501 筆"})
    assert _error(r) == (422, "record_limit")
    assert api.snapshot() == before
    assert api.state()["version"] == version
    # 其他集合不受影響
    other = "milestones" if collection == "tasks" else "tasks"
    _create(api, other, {"title": "y"})
