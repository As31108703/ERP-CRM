"""行政申請狀態機、合成示範資料與行政指標（A§1–A§4）。"""

import copy
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.core.problem import Problem
from src.modules.administration import invariants as adm_invariants
from src.modules.administration import snapshot as adm_snapshot
from src.modules.administration.metrics import admin_metrics
from tests.helpers import ApiClient

BASE = "/api/v1/administration"
UNITS = f"{BASE}/units"
STAFF = f"{BASE}/staff"
REQUESTS = f"{BASE}/requests"
ATTENDANCE = f"{BASE}/attendance"
NOTICES = f"{BASE}/notices"
DEMO = f"{BASE}/demo"
MISSING = "00000000-0000-4000-8000-000000000000"
COLLECTIONS = (
    "units",
    "staff",
    "shifts",
    "attendance",
    "requests",
    "equipment",
    "reservations",
    "notices",
)


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _t(day: str, hm: str) -> str:
    return f"{day}T{hm}:00+08:00"


def _adm(api: ApiClient) -> dict[str, Any]:
    return api.snapshot()["administration"]


def _by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(r for r in rows if r["id"] == row_id)


def _base(api: ApiClient) -> tuple[str, str]:
    api.setup("general")
    unit = api.ok("POST", UNITS, {"name": "行政組", "kind": "department"})["result"]
    staff = api.ok("POST", STAFF, {"code": "S-01", "alias": "示範夥伴甲", "unit_id": unit})[
        "result"
    ]
    return unit, staff


def _request(api: ApiClient, unit: str, **extra: Any) -> str:
    body = {"type": "general", "unit_id": unit, "title": "一般申請", **extra}
    return api.ok("POST", REQUESTS, body)["result"]


def _rejected(api: ApiClient, method: str, path: str, body: dict[str, Any]) -> tuple[int, str]:
    """送出應被拒絕的命令，並確認快照與版本完全沒變。"""
    before = api.snapshot()
    r = api.mutate(method, path, body)
    after = api.snapshot()
    assert after == before
    assert after["version"] == before["version"]
    return _error(r)


def _ws_id(db_engine: Engine) -> str:
    with db_engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM workspace")).scalar_one())


# --- 申請狀態機 ---------------------------------------------------------------------


def test_request_lifecycle(api: ApiClient) -> None:
    unit, staff = _base(api)
    rid = _request(api, unit, type="purchase", staff_id=staff, amount_minor=1200)
    row = _by_id(_adm(api)["requests"], rid)
    assert row["status"] == "draft"
    assert (row["currency"], row["processing_note"], row["description"]) == ("SIM", "", "")
    assert (row["start_at"], row["end_at"]) == (None, None)
    assert row["transitions"] == [{"status": "draft", "at": row["created_at"], "note": ""}]

    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    api.ok("POST", f"{REQUESTS}/{rid}/return", {"processing_note": "請補報價單"})
    row = _by_id(_adm(api)["requests"], rid)
    assert (row["status"], row["processing_note"]) == ("returned", "請補報價單")

    api.ok("PATCH", f"{REQUESTS}/{rid}", {"amount_minor": 1500, "description": "已補報價"})
    row = _by_id(_adm(api)["requests"], rid)
    assert (row["status"], row["amount_minor"]) == ("draft", 1500)

    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    api.ok("POST", f"{REQUESTS}/{rid}/prepare", {})
    row = _by_id(_adm(api)["requests"], rid)
    assert row["status"] == "prepared_unreviewed"
    assert [t["status"] for t in row["transitions"]] == [
        "draft",
        "submitted",
        "returned",
        "draft",
        "submitted",
        "prepared_unreviewed",
    ]
    assert len(row["transitions"]) == 6
    assert [t["note"] for t in row["transitions"]] == ["", "", "請補報價單", "", "", ""]
    # 重新送出後仍保留最近一次退回的原因
    assert row["processing_note"] == "請補報價單"
    ats = [t["at"] for t in row["transitions"]]
    assert ats == sorted(ats) and ats[-1] == row["updated_at"]

    # 終止狀態：不可再撤回、編輯或送出
    assert _rejected(api, "POST", f"{REQUESTS}/{rid}/withdraw", {}) == (
        409,
        "office_transition_invalid",
    )


def test_request_withdraw_is_terminal(api: ApiClient) -> None:
    unit, _ = _base(api)
    rid = _request(api, unit)
    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    api.ok("POST", f"{REQUESTS}/{rid}/withdraw", {})
    row = _by_id(_adm(api)["requests"], rid)
    assert [t["status"] for t in row["transitions"]] == ["draft", "submitted", "withdrawn"]
    for action in ("submit", "withdraw", "prepare"):
        assert _rejected(api, "POST", f"{REQUESTS}/{rid}/{action}", {}) == (
            409,
            "office_transition_invalid",
        )


def test_leave_requires_staff_and_dates(api: ApiClient) -> None:
    unit, staff = _base(api)
    dates = {"start_at": _t("2026-11-03", "09:00"), "end_at": _t("2026-11-05", "18:00")}
    leave = {"type": "leave", "unit_id": unit, "title": "特休"}
    assert _rejected(api, "POST", REQUESTS, {**leave, **dates}) == (422, "office_leave_invalid")
    assert _rejected(api, "POST", REQUESTS, {**leave, "staff_id": staff}) == (
        422,
        "office_leave_invalid",
    )
    assert _rejected(
        api, "POST", REQUESTS, {**leave, **dates, "staff_id": staff, "amount_minor": 1}
    ) == (422, "office_leave_invalid")
    rid = api.ok("POST", REQUESTS, {**leave, **dates, "staff_id": staff})["result"]
    row = _by_id(_adm(api)["requests"], rid)
    assert (row["start_at"], row["end_at"]) == (
        "2026-11-03T01:00:00.000Z",
        "2026-11-05T10:00:00.000Z",
    )
    # 請假最長 31 天；清除日期會違反請假規則
    long = {"start_at": _t("2026-12-01", "00:00"), "end_at": _t("2027-01-01", "00:01")}
    assert _rejected(api, "PATCH", f"{REQUESTS}/{rid}", long) == (422, "office_interval_invalid")
    cleared = {"start_at": None, "end_at": None}
    assert _rejected(api, "PATCH", f"{REQUESTS}/{rid}", cleared) == (422, "office_leave_invalid")
    month = {"start_at": _t("2026-12-01", "00:00"), "end_at": _t("2026-12-31", "00:00")}
    api.ok("PATCH", f"{REQUESTS}/{rid}", month)


def test_purchase_amount_min_1(api: ApiClient) -> None:
    unit, _ = _base(api)
    for request_type in ("purchase", "expense"):
        body = {"type": request_type, "unit_id": unit, "title": "耗材"}
        assert _rejected(api, "POST", REQUESTS, body) == (422, "office_number_invalid")
        assert _rejected(api, "POST", REQUESTS, {**body, "amount_minor": 0}) == (
            422,
            "office_number_invalid",
        )
        rid = api.ok("POST", REQUESTS, {**body, "amount_minor": 1})["result"]
        assert _rejected(api, "PATCH", f"{REQUESTS}/{rid}", {"amount_minor": 0}) == (
            422,
            "office_number_invalid",
        )
    # 一般申請金額可為 0
    _request(api, unit, amount_minor=0)


def test_currency_payload_rejected(api: ApiClient) -> None:
    unit, _ = _base(api)
    body = {"type": "purchase", "unit_id": unit, "title": "耗材", "amount_minor": 100}
    assert _rejected(api, "POST", REQUESTS, {**body, "currency": "SIM"}) == (
        422,
        "protected_field",
    )
    assert _rejected(api, "POST", REQUESTS, {**body, "currency": "TWD"}) == (
        422,
        "protected_field",
    )
    rid = api.ok("POST", REQUESTS, body)["result"]
    assert _rejected(api, "PATCH", f"{REQUESTS}/{rid}", {"currency": "USD"}) == (
        422,
        "protected_field",
    )
    assert _by_id(_adm(api)["requests"], rid)["currency"] == "SIM"


def test_transition_limit_50(api: ApiClient, db_engine: Engine) -> None:
    unit, _ = _base(api)
    rid = _request(api, unit)
    # 直接補到 50 筆（submitted、returned、draft 循環，第 50 筆為 submitted），再退回就超過上限
    with db_engine.begin() as conn:
        steps = ["submitted", "returned", "draft"]
        for seq in range(2, 51):
            status = steps[(seq - 2) % 3]
            conn.execute(
                text(
                    "INSERT INTO adm_request_transition"
                    " (workspace_id, request_id, seq, status, at, note) "
                    "SELECT workspace_id, id, :seq, :status, created_at, :note"
                    " FROM adm_request WHERE id = :id"
                ),
                {
                    "seq": seq,
                    "status": status,
                    "note": "補件" if status == "returned" else "",
                    "id": rid,
                },
            )
        conn.execute(text("UPDATE adm_request SET status = 'submitted', processing_note = '補件'"))
    row = _by_id(_adm(api)["requests"], rid)
    assert len(row["transitions"]) == 50
    assert row["transitions"][-1]["status"] == "submitted"
    note = {"processing_note": "再補件"}
    assert _rejected(api, "POST", f"{REQUESTS}/{rid}/return", note) == (
        422,
        "office_transition_limit",
    )


# --- 匯入：狀態紀錄規則 ---------------------------------------------------------------


def _check_restored(db_engine: Engine, data: dict[str, Any]) -> str | None:
    workspace_id = _ws_id(db_engine)
    with Session(db_engine) as db:
        try:
            adm_snapshot.restore(db, workspace_id, {"administration": data})
            adm_invariants.check(db, workspace_id)
        except Problem as exc:
            return exc.code
        finally:
            db.rollback()
    return None


def test_restore_validates_transitions(api: ApiClient, db_engine: Engine) -> None:
    unit, staff = _base(api)
    rid = _request(api, unit, type="purchase", staff_id=staff, amount_minor=500)
    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    api.ok("POST", f"{REQUESTS}/{rid}/return", {"processing_note": "缺單據"})
    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    good = _adm(api)
    assert _check_restored(db_engine, copy.deepcopy(good)) is None

    def tampered(mutate) -> str | None:
        data = copy.deepcopy(good)
        mutate(data["requests"][0])
        return _check_restored(db_engine, data)

    def at(i: int, value: str):
        def run(row):
            row["transitions"][i]["at"] = value

        return run

    def first_not_draft(row):
        row["transitions"][0]["status"] = "submitted"

    def bad_step(row):
        row["transitions"][1]["status"] = "prepared_unreviewed"

    def note_on_submit(row):
        row["transitions"][1]["note"] = "不該有"

    def blank_return_note(row):
        row["transitions"][2]["note"] = "  "

    def status_mismatch(row):
        row["status"] = "returned"

    def note_mismatch(row):
        row["processing_note"] = "別的原因"

    def too_many(row):
        row["transitions"] = (
            row["transitions"] + [{"status": "submitted", "at": row["updated_at"], "note": ""}] * 47
        )

    def leave_amount(row):
        row["type"] = "leave"

    def other_unit_staff(row):
        row["staff_id"] = MISSING

    def currency(row):
        row["currency"] = "TWD"

    def actor(row):
        row["transitions"][0]["actor_id"] = staff

    created, updated = good["requests"][0]["created_at"], good["requests"][0]["updated_at"]
    assert tampered(first_not_draft) == "office_transition_invalid"
    assert tampered(at(0, "2026-01-01T00:00:00.000Z")) == "office_transition_invalid"
    assert tampered(at(3, "2999-01-01T00:00:00.000Z")) == "office_transition_invalid"
    # 時間倒退
    assert (
        tampered(
            lambda row: (
                row["transitions"][1].__setitem__("at", updated),
                row["transitions"][2].__setitem__("at", created),
            )
        )
        == "office_transition_invalid"
    )
    assert tampered(bad_step) == "office_transition_invalid"
    assert tampered(note_on_submit) == "office_transition_invalid"
    assert tampered(blank_return_note) == "office_text_invalid"
    assert tampered(status_mismatch) == "office_transition_invalid"
    assert tampered(note_mismatch) == "office_transition_invalid"
    assert tampered(too_many) == "office_transition_limit"
    assert tampered(lambda row: row.__setitem__("transitions", [])) == "office_transition_limit"
    assert tampered(leave_amount) == "office_leave_invalid"
    assert tampered(other_unit_staff) == "office_record_missing"
    assert tampered(currency) == "simulation_required"
    assert tampered(actor) == "office_fields_invalid"


# --- 合成示範資料 ---------------------------------------------------------------------

_PRESETS = {
    "store": ("合成示範門市", "branch", ["示範店務", "示範行政"], "合成示範收銀平板",
              "合成示範請購：店務耗材", 3200),
    "office": ("合成示範行政組", "department", ["示範行政", "示範總務"], "合成示範簡報設備",
               "合成示範請購：辦公耗材", 4500),
    "factory": ("合成示範廠務組", "department", ["示範現場協調", "示範廠務"],
                "合成示範巡檢平板", "合成示範請購：巡檢耗材", 6000),
}  # fmt: skip


@pytest.mark.parametrize("preset", list(_PRESETS))
def test_demo_counts(api: ApiClient, preset: str) -> None:
    api.setup("general")
    before = api.snapshot()
    r = api.ok("POST", DEMO, {"preset": preset, "week_start": "2026-11-02"})
    after = api.snapshot()
    adm = after["administration"]
    assert [len(adm[name]) for name in COLLECTIONS] == [1, 2, 5, 2, 1, 1, 1, 2]
    assert adm["changes"] == []
    assert after["version"] == before["version"] + 1
    # 其他資料不受影響
    for key, value in before.items():
        if key not in ("administration", "version", "history"):
            assert after[key] == value, key

    name, kind, roles, equipment, purchase, amount = _PRESETS[preset]
    unit = adm["units"][0]
    assert r["result"] == unit["id"]
    assert (unit["name"], unit["kind"], unit["parent_id"], unit["active"]) == (
        name,
        kind,
        None,
        True,
    )
    assert [(s["code"], s["alias"], s["role_label"]) for s in adm["staff"]] == [
        ("DEMO-1", "合成示範夥伴甲", roles[0]),
        ("DEMO-2", "合成示範夥伴乙", roles[1]),
    ]
    s1, s2 = adm["staff"][0]["id"], adm["staff"][1]["id"]
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert [
        (s["staff_id"], s["start_at"], s["end_at"], s["break_minutes"], s["note"], s["status"])
        for s in adm["shifts"]
    ] == [
        (
            [s1, s2][i % 2],
            f"{d}T01:00:00.000Z",
            f"{d}T09:00:00.000Z",
            60,
            "合成示範排班，供流程練習",
            "scheduled",
        )
        for i, d in enumerate(days)
    ]
    assert [
        (a["staff_id"], a["start_at"], a["end_at"], a["break_minutes"], a["note"], a["voided"])
        for a in adm["attendance"]
    ] == [
        (
            [s1, s2][i],
            f"{d}T01:05:00.000Z",
            f"{d}T08:55:00.000Z",
            60,
            "人工輸入的合成示範出勤，非真實打卡",
            False,
        )
        for i, d in enumerate(days[:2])
    ]
    req = adm["requests"][0]
    assert (req["type"], req["staff_id"], req["unit_id"], req["title"], req["amount_minor"]) == (
        "purchase",
        s1,
        unit["id"],
        purchase,
        amount,
    )
    assert req["description"] == "合成示範草稿，只練習行政資料整理，未送出、未核准、未付款。"
    assert (req["status"], len(req["transitions"])) == ("draft", 1)
    eq = adm["equipment"][0]
    assert (eq["code"], eq["name"], eq["unit_id"], eq["state"]) == (
        "DEMO-EQ-1",
        equipment,
        unit["id"],
        "available",
    )
    res = adm["reservations"][0]
    assert (res["equipment_id"], res["staff_id"], res["start_at"], res["end_at"]) == (
        eq["id"],
        s1,
        "2026-11-03T05:00:00.000Z",
        "2026-11-03T07:00:00.000Z",
    )
    assert (res["purpose"], res["status"]) == ("合成示範借用，練習改期、歸還與取消", "reserved")
    n1, n2 = adm["notices"]
    assert (n1["title"], n1["body"], n1["unit_id"], n1["pinned"], n1["due_at"]) == (
        "合成示範：行政入門提醒",
        "這批資料全部為合成示範，可練習排班更正、出勤作廢、申請退回與設備借用。",
        unit["id"],
        True,
        "2026-11-06T08:00:00.000Z",
    )
    assert (n2["title"], n2["body"], n2["unit_id"], n2["pinned"], n2["due_at"]) == (
        "合成示範：公告封存練習",
        "完成閱讀後可封存，再從封存列表還原；資料會保留。",
        None,
        False,
        None,
    )
    assert not n1["archived"] and not n2["archived"]


def test_demo_requires_empty_desk_409(api: ApiClient, make_client) -> None:
    api.setup("general")
    body = {"preset": "store", "week_start": "2026-11-02"}
    notice = api.ok("POST", NOTICES, {"title": "既有公告"})["result"]
    # 封存的資料也算資料
    api.ok("POST", f"{NOTICES}/{notice}/archive", {})
    assert _rejected(api, "POST", DEMO, body) == (409, "office_demo_not_empty")
    # 第二次建立示範資料也會被擋
    other = ApiClient(make_client())
    other.setup("general")
    other.ok("POST", DEMO, body)
    assert _rejected(other, "POST", DEMO, {**body, "preset": "office"}) == (
        409,
        "office_demo_not_empty",
    )


def test_demo_module_disabled_403(api: ApiClient) -> None:
    api.setup("general", modules=["inventory"])
    body = {"preset": "store", "week_start": "2026-11-02"}
    assert _rejected(api, "POST", DEMO, body) == (403, "module_disabled")


# --- 指標 ---------------------------------------------------------------------------


def test_admin_metrics(api: ApiClient, db_engine: Engine) -> None:
    api.setup("general")
    workspace_id = _ws_id(db_engine)
    with Session(db_engine) as db:
        assert admin_metrics(db, workspace_id) == {
            "active_units": 0,
            "active_staff": 0,
            "scheduled_shifts": 0,
            "actual_work_minutes": 0,
            "open_requests": 0,
            "prepared_unreviewed_requests": 0,
            "available_equipment": 0,
            "active_reservations": 0,
            "pinned_notices": 0,
        }
    api.ok("POST", DEMO, {"preset": "office", "week_start": "2026-11-02"})
    adm = _adm(api)
    with Session(db_engine) as db:
        assert admin_metrics(db, workspace_id) == {
            "active_units": 1,
            "active_staff": 2,
            "scheduled_shifts": 5,
            "actual_work_minutes": 2 * (470 - 60),
            "open_requests": 1,
            "prepared_unreviewed_requests": 0,
            "available_equipment": 1,
            "active_reservations": 1,
            "pinned_notices": 1,
        }
    rid = adm["requests"][0]["id"]
    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    api.ok("POST", f"{REQUESTS}/{rid}/prepare", {})
    api.ok("POST", f"{ATTENDANCE}/{adm['attendance'][0]['id']}/void", {"reason": "重複輸入"})
    api.ok("POST", f"{NOTICES}/{adm['notices'][0]['id']}/archive", {})
    other = _request(api, adm["units"][0]["id"])
    api.ok("POST", f"{REQUESTS}/{other}/submit", {})
    before = api.snapshot()
    with Session(db_engine) as db:
        metrics = admin_metrics(db, workspace_id)
    # 讀取指標不改資料
    assert api.snapshot() == before
    assert metrics == {
        "active_units": 1,
        "active_staff": 2,
        "scheduled_shifts": 5,
        "actual_work_minutes": 410,
        "open_requests": 1,
        "prepared_unreviewed_requests": 1,
        "available_equipment": 1,
        "active_reservations": 1,
        "pinned_notices": 0,
    }


# --- 錯誤碼：每種失敗情境都不改變快照 ----------------------------------------------


def _rejections(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any], int, str]]:
    unit, staff, other_staff = ids["unit"], ids["staff"], ids["other_staff"]
    inactive_unit, inactive_staff = ids["inactive_unit"], ids["inactive_staff"]
    draft, submitted, returned = ids["draft"], ids["submitted"], ids["returned"]
    withdrawn, prepared, orphan = ids["withdrawn"], ids["prepared"], ids["orphan"]
    base = {"type": "general", "unit_id": unit, "title": "申請"}
    dates = {"start_at": _t("2026-11-03", "09:00"), "end_at": _t("2026-11-03", "18:00")}
    demo = {"preset": "store", "week_start": "2026-11-02"}
    return [
        # 建立
        ("POST", REQUESTS, {**base, "currency": "SIM"}, 422, "protected_field"),
        ("POST", REQUESTS, {**base, "bank_account": "x"}, 422, "simulation_required"),
        ("POST", REQUESTS, {**base, "status": "submitted"}, 422, "office_fields_invalid"),
        ("POST", REQUESTS, {**base, "transitions": []}, 422, "office_fields_invalid"),
        ("POST", REQUESTS, {**base, "checker_id": staff}, 422, "office_fields_invalid"),
        ("POST", REQUESTS, {"type": "general", "unit_id": unit}, 422, "office_fields_invalid"),
        ("POST", REQUESTS, {**base, "type": "approval"}, 422, "office_state_invalid"),
        ("POST", REQUESTS, {**base, "title": " "}, 422, "office_text_invalid"),
        ("POST", REQUESTS, {**base, "title": "x" * 101}, 422, "office_text_invalid"),
        ("POST", REQUESTS, {**base, "description": "x" * 2001}, 422, "office_text_invalid"),
        ("POST", REQUESTS, {**base, "unit_id": MISSING}, 404, "office_record_missing"),
        ("POST", REQUESTS, {**base, "unit_id": "abc"}, 422, "office_id_invalid"),
        ("POST", REQUESTS, {**base, "unit_id": inactive_unit}, 409, "office_unit_inactive"),
        ("POST", REQUESTS, {**base, "staff_id": inactive_staff}, 409, "office_staff_inactive"),
        ("POST", REQUESTS, {**base, "staff_id": other_staff}, 422, "office_unit_mismatch"),
        ("POST", REQUESTS, {**base, "staff_id": MISSING}, 404, "office_record_missing"),
        ("POST", REQUESTS, {**base, "amount_minor": -1}, 422, "office_number_invalid"),
        ("POST", REQUESTS, {**base, "amount_minor": 1.5}, 422, "office_number_invalid"),
        ("POST", REQUESTS, {**base, "amount_minor": 10**9 + 1}, 422, "office_number_invalid"),
        ("POST", REQUESTS, {**base, "type": "purchase"}, 422, "office_number_invalid"),
        ("POST", REQUESTS, {**base, "type": "expense"}, 422, "office_number_invalid"),
        ("POST", REQUESTS, {**base, "type": "leave", **dates}, 422, "office_leave_invalid"),
        (
            "POST",
            REQUESTS,
            {**base, "type": "leave", "staff_id": staff},
            422,
            "office_leave_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, "type": "leave", "staff_id": staff, "amount_minor": 5, **dates},
            422,
            "office_leave_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, "start_at": dates["start_at"]},
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, "start_at": None, "end_at": dates["end_at"]},
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, "start_at": dates["end_at"], "end_at": dates["start_at"]},
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, **dates, "end_at": _t("2026-11-05", "09:01")},
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {
                **base,
                "type": "leave",
                "staff_id": staff,
                "start_at": _t("2026-12-01", "00:00"),
                "end_at": _t("2027-01-01", "00:01"),
            },
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            REQUESTS,
            {**base, **dates, "start_at": "2026-11-03T09:00:30+08:00"},
            422,
            "office_time_invalid",
        ),
        ("POST", REQUESTS, {**base, **dates, "end_at": "明天"}, 422, "office_time_invalid"),
        # 編輯
        ("PATCH", f"{REQUESTS}/{draft}", {}, 422, "office_fields_invalid"),
        ("PATCH", f"{REQUESTS}/{draft}", {"type": "leave"}, 422, "office_fields_invalid"),
        ("PATCH", f"{REQUESTS}/{draft}", {"staff_id": staff}, 422, "office_fields_invalid"),
        ("PATCH", f"{REQUESTS}/{draft}", {"unit_id": unit}, 422, "office_fields_invalid"),
        ("PATCH", f"{REQUESTS}/{draft}", {"status": "draft"}, 422, "office_fields_invalid"),
        ("PATCH", f"{REQUESTS}/{draft}", {"currency": "SIM"}, 422, "protected_field"),
        ("PATCH", f"{REQUESTS}/{draft}", {"title": ""}, 422, "office_text_invalid"),
        (
            "PATCH",
            f"{REQUESTS}/{draft}",
            {"end_at": dates["end_at"]},
            422,
            "office_interval_invalid",
        ),
        ("PATCH", f"{REQUESTS}/{MISSING}", {"title": "x"}, 404, "office_record_missing"),
        ("PATCH", f"{REQUESTS}/{submitted}", {"title": "x"}, 409, "office_transition_invalid"),
        ("PATCH", f"{REQUESTS}/{withdrawn}", {"title": "x"}, 409, "office_transition_invalid"),
        ("PATCH", f"{REQUESTS}/{prepared}", {"title": "x"}, 409, "office_transition_invalid"),
        # 送出
        ("POST", f"{REQUESTS}/{submitted}/submit", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{withdrawn}/submit", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{prepared}/submit", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{orphan}/submit", {}, 409, "office_staff_inactive"),
        ("POST", f"{REQUESTS}/{draft}/submit", {"note": "x"}, 422, "office_fields_invalid"),
        ("POST", f"{REQUESTS}/{MISSING}/submit", {}, 404, "office_record_missing"),
        # 退回
        ("POST", f"{REQUESTS}/{submitted}/return", {}, 422, "office_fields_invalid"),
        (
            "POST",
            f"{REQUESTS}/{submitted}/return",
            {"processing_note": " "},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            f"{REQUESTS}/{submitted}/return",
            {"processing_note": "x" * 1001},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            f"{REQUESTS}/{draft}/return",
            {"processing_note": "補件"},
            409,
            "office_transition_invalid",
        ),
        (
            "POST",
            f"{REQUESTS}/{returned}/return",
            {"processing_note": "補件"},
            409,
            "office_transition_invalid",
        ),
        # 撤回與整理
        ("POST", f"{REQUESTS}/{withdrawn}/withdraw", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{prepared}/withdraw", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{draft}/prepare", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{returned}/prepare", {}, 409, "office_transition_invalid"),
        ("POST", f"{REQUESTS}/{prepared}/prepare", {}, 409, "office_transition_invalid"),
        # 示範資料
        ("POST", DEMO, {**demo, "preset": "school"}, 422, "office_state_invalid"),
        ("POST", DEMO, {**demo, "week_start": "2026-11-03"}, 422, "office_week_invalid"),
        ("POST", DEMO, {**demo, "week_start": "2026-02-30"}, 422, "office_week_invalid"),
        ("POST", DEMO, {**demo, "week_start": "2026/11/02"}, 422, "office_week_invalid"),
        ("POST", DEMO, {"preset": "store"}, 422, "office_fields_invalid"),
        ("POST", DEMO, {**demo, "unit_id": unit}, 422, "office_fields_invalid"),
        ("POST", DEMO, demo, 409, "office_demo_not_empty"),
    ]


_KEYS = (
    "unit",
    "staff",
    "other_staff",
    "inactive_unit",
    "inactive_staff",
    "draft",
    "submitted",
    "returned",
    "withdrawn",
    "prepared",
    "orphan",
)
_CASES = _rejections({k: f"<{k}>" for k in _KEYS})


@pytest.mark.parametrize(
    "index",
    range(len(_CASES)),
    ids=[f"{c[0]}-{c[1].removeprefix(BASE)}-{c[4]}-{i}" for i, c in enumerate(_CASES)],
)
def test_rejections_leave_snapshot_unchanged(api: ApiClient, index: int) -> None:
    unit, staff = _base(api)
    inactive_unit = api.ok("POST", UNITS, {"name": "停用單位", "kind": "branch"})["result"]
    api.ok("PATCH", f"{UNITS}/{inactive_unit}", {"active": False})
    other_unit = api.ok("POST", UNITS, {"name": "倉庫", "kind": "branch"})["result"]
    other_staff = api.ok("POST", STAFF, {"code": "S-02", "alias": "乙", "unit_id": other_unit})[
        "result"
    ]
    inactive_staff = api.ok("POST", STAFF, {"code": "S-03", "alias": "丙", "unit_id": unit})[
        "result"
    ]
    # 草稿申請的員工之後停用：仍可保留草稿，但不能送出
    orphan = _request(api, unit, staff_id=inactive_staff)
    api.ok("PATCH", f"{STAFF}/{inactive_staff}", {"status": "inactive"})
    draft = _request(api, unit, staff_id=staff)
    submitted = _request(api, unit)
    api.ok("POST", f"{REQUESTS}/{submitted}/submit", {})
    returned = _request(api, unit)
    api.ok("POST", f"{REQUESTS}/{returned}/submit", {})
    api.ok("POST", f"{REQUESTS}/{returned}/return", {"processing_note": "補件"})
    withdrawn = _request(api, unit)
    api.ok("POST", f"{REQUESTS}/{withdrawn}/withdraw", {})
    prepared = _request(api, unit)
    api.ok("POST", f"{REQUESTS}/{prepared}/submit", {})
    api.ok("POST", f"{REQUESTS}/{prepared}/prepare", {})
    ids = {
        "unit": unit,
        "staff": staff,
        "other_staff": other_staff,
        "inactive_unit": inactive_unit,
        "inactive_staff": inactive_staff,
        "draft": draft,
        "submitted": submitted,
        "returned": returned,
        "withdrawn": withdrawn,
        "prepared": prepared,
        "orphan": orphan,
    }
    method, path, body, status, code = _rejections(ids)[index]
    assert _rejected(api, method, path, copy.deepcopy(body)) == (status, code)


def test_staff_deactivation_blocked_by_submitted_request(api: ApiClient) -> None:
    unit, staff = _base(api)
    rid = _request(api, unit, staff_id=staff)
    api.ok("POST", f"{REQUESTS}/{rid}/submit", {})
    assert _rejected(api, "PATCH", f"{STAFF}/{staff}", {"status": "inactive"}) == (
        409,
        "office_staff_inactive",
    )
    api.ok("POST", f"{REQUESTS}/{rid}/withdraw", {})
    api.ok("PATCH", f"{STAFF}/{staff}", {"status": "inactive"})
