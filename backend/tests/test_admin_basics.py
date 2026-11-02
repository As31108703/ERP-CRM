"""行政基礎：啟用、組織、假員工、設備、公告與封存／還原紀錄（A§0–A§2）。"""

import copy
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.core.problem import Problem
from src.modules.administration import snapshot as adm_snapshot
from src.modules.administration import validators as v
from tests.helpers import ApiClient

BASE = "/api/v1/administration"
ENABLE = f"{BASE}/enable"
UNITS = f"{BASE}/units"
STAFF = f"{BASE}/staff"
EQUIPMENT = f"{BASE}/equipment"
NOTICES = f"{BASE}/notices"
ADM_KEYS = {
    "units",
    "staff",
    "shifts",
    "attendance",
    "requests",
    "equipment",
    "reservations",
    "notices",
    "changes",
}


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _setup_admin(api: ApiClient) -> None:
    # general 範本預設含行政模組
    api.setup("general")


def _unit(api: ApiClient, name: str = "門市", kind: str = "branch", **extra: Any) -> str:
    return api.ok("POST", UNITS, {"name": name, "kind": kind, **extra})["result"]


def _staff(api: ApiClient, unit_id: str, code: str = "S-01", **extra: Any) -> str:
    body = {"code": code, "alias": "示範夥伴甲", "unit_id": unit_id, **extra}
    return api.ok("POST", STAFF, body)["result"]


def _equipment(api: ApiClient, unit_id: str, code: str = "EQ-1") -> str:
    return api.ok("POST", EQUIPMENT, {"code": code, "name": "收銀平板", "unit_id": unit_id})[
        "result"
    ]


def _notice(api: ApiClient, **extra: Any) -> str:
    return api.ok("POST", NOTICES, {"title": "入門提醒", **extra})["result"]


def _adm(api: ApiClient) -> dict[str, Any]:
    return api.snapshot()["administration"]


def _by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(r for r in rows if r["id"] == row_id)


# --- 啟用 ---------------------------------------------------------------------------


def test_enable_existing_workspace_keeps_data(api: ApiClient) -> None:
    api.setup("general", modules=["inventory"])
    before = api.snapshot()
    assert "administration" not in before
    # 未啟用時行政命令被模組閘擋下
    assert _error(api.mutate("POST", UNITS, {"name": "門市", "kind": "branch"})) == (
        403,
        "module_disabled",
    )

    body = api.ok("POST", ENABLE, {})
    assert body["result"] == before["generation_id"]
    after = api.snapshot()
    assert after["modules"] == ["inventory", "administration"]
    assert after["administration"] == {k: [] for k in ADM_KEYS}
    assert after["version"] == before["version"] + 1
    assert after["history"][-1]["action"] == "office.enable"
    for key, value in before.items():
        if key not in ("modules", "version", "history"):
            assert after[key] == value, key
    # 啟用後即可建立行政資料
    _unit(api)


def test_enable_twice_409_office_already_enabled(api: ApiClient) -> None:
    api.setup("general", modules=["inventory"])
    api.ok("POST", ENABLE, {})
    before = api.snapshot()
    assert _error(api.mutate("POST", ENABLE, {})) == (409, "office_already_enabled")
    assert api.snapshot() == before
    # 範本預設已啟用的工作區也一樣
    api.ok("POST", "/api/v1/workspace/clear", {})
    _setup_admin(api)
    assert _error(api.mutate("POST", ENABLE, {})) == (409, "office_already_enabled")


def test_enable_requires_workspace_and_empty_payload(api: ApiClient) -> None:
    assert _error(api.mutate("POST", ENABLE, {})) == (409, "workspace_missing")
    api.setup("general", modules=["inventory"])
    assert _error(api.mutate("POST", ENABLE, {"force": True})) == (422, "office_fields_invalid")


# --- 組織 ---------------------------------------------------------------------------


def test_unit_create_and_update(api: ApiClient) -> None:
    _setup_admin(api)
    branch = _unit(api)
    dept = _unit(api, "行政組", "department", parent_id=branch)
    api.ok("PATCH", f"{UNITS}/{dept}", {"name": "總務組"})
    units = _adm(api)["units"]
    assert [u["id"] for u in units] == [branch, dept]
    row = _by_id(units, dept)
    assert set(row) == {"id", "created_at", "updated_at", "name", "kind", "parent_id", "active"}
    assert row["name"] == "總務組"
    assert row["kind"] == "department"
    assert row["parent_id"] == branch
    assert row["active"] is True
    assert _by_id(units, branch)["parent_id"] is None
    # 停用子單位後可以停用上層；重新啟用子單位前須先啟用上層
    api.ok("PATCH", f"{UNITS}/{dept}", {"active": False})
    api.ok("PATCH", f"{UNITS}/{branch}", {"active": False})
    assert _error(api.mutate("PATCH", f"{UNITS}/{dept}", {"active": True})) == (
        422,
        "office_unit_inactive",
    )


def test_unit_cycle_rejected(api: ApiClient, db_engine: Engine) -> None:
    _setup_admin(api)
    a = _unit(api, "甲")
    b = _unit(api, "乙", parent_id=a)
    # 指令無法改上層，循環只可能來自匯入：直接寫資料庫後，下一個命令的一致性檢查會擋下
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE adm_unit SET parent_id = :b WHERE id = :a"), {"a": a, "b": b})
    assert _error(api.mutate("POST", UNITS, {"name": "丙", "kind": "branch"})) == (
        422,
        "office_unit_cycle",
    )
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE adm_unit SET parent_id = id WHERE id = :a"), {"a": a})
    assert _error(api.mutate("POST", UNITS, {"name": "丙", "kind": "branch"})) == (
        422,
        "office_unit_cycle",
    )
    # 更新時也不能改上層
    assert _error(api.mutate("PATCH", f"{UNITS}/{b}", {"parent_id": b})) == (
        422,
        "office_fields_invalid",
    )


def test_deactivate_unit_blocked_by_active_staff(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    staff = _staff(api, unit)
    before = api.snapshot()
    assert _error(api.mutate("PATCH", f"{UNITS}/{unit}", {"active": False})) == (
        409,
        "office_unit_inactive",
    )
    assert api.snapshot() == before
    # 員工停用後即可停用單位；之後啟用員工會被擋
    api.ok("PATCH", f"{STAFF}/{staff}", {"status": "inactive"})
    api.ok("PATCH", f"{UNITS}/{unit}", {"active": False})
    assert _error(api.mutate("PATCH", f"{STAFF}/{staff}", {"status": "active"})) == (
        409,
        "office_unit_inactive",
    )


def test_deactivate_unit_blocked_by_child_and_equipment(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    child = _unit(api, "子單位", "department", parent_id=unit)
    assert _error(api.mutate("PATCH", f"{UNITS}/{unit}", {"active": False})) == (
        422,
        "office_unit_inactive",
    )
    api.ok("PATCH", f"{UNITS}/{child}", {"active": False})
    eq = _equipment(api, unit)
    assert _error(api.mutate("PATCH", f"{UNITS}/{unit}", {"active": False})) == (
        409,
        "office_unit_inactive",
    )
    # 設備停用（retired）後就不再阻擋
    api.ok("PATCH", f"{EQUIPMENT}/{eq}", {"state": "retired"})
    api.ok("PATCH", f"{UNITS}/{unit}", {"active": False})
    assert _error(api.mutate("PATCH", f"{EQUIPMENT}/{eq}", {"state": "available"})) == (
        409,
        "office_unit_inactive",
    )


# --- 假員工與設備 -------------------------------------------------------------------


def test_staff_create_and_update(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    staff = _staff(api, unit)
    row = _by_id(_adm(api)["staff"], staff)
    assert set(row) == {
        "id",
        "created_at",
        "updated_at",
        "code",
        "alias",
        "unit_id",
        "role_label",
        "status",
    }
    assert (row["code"], row["role_label"], row["status"]) == ("S-01", "", "active")
    api.ok("PATCH", f"{STAFF}/{staff}", {"alias": "示範夥伴乙", "role_label": "示範行政"})
    row = _by_id(_adm(api)["staff"], staff)
    assert (row["alias"], row["role_label"]) == ("示範夥伴乙", "示範行政")


def test_staff_code_duplicate_case_insensitive(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    _staff(api, unit, "Demo-1")
    before = api.snapshot()
    r = api.mutate("POST", STAFF, {"code": " demo-1 ", "alias": "乙", "unit_id": unit})
    assert _error(r) == (422, "office_code_duplicate")
    assert api.snapshot() == before
    # 設備代碼各自獨立：與員工代碼相同沒關係，但設備之間不可重複
    _equipment(api, unit, "DEMO-1")
    r = api.mutate("POST", EQUIPMENT, {"code": "demo-1", "name": "平板", "unit_id": unit})
    assert _error(r) == (422, "office_code_duplicate")


def test_equipment_create_and_update(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    eq = _equipment(api, unit)
    row = _by_id(_adm(api)["equipment"], eq)
    assert set(row) == {"id", "created_at", "updated_at", "code", "name", "unit_id", "state"}
    assert row["state"] == "available"
    api.ok("PATCH", f"{EQUIPMENT}/{eq}", {"state": "maintenance", "name": "收銀平板二號"})
    row = _by_id(_adm(api)["equipment"], eq)
    assert (row["state"], row["name"]) == ("maintenance", "收銀平板二號")


# --- 公告 ---------------------------------------------------------------------------


def test_notice_create_update_defaults(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    notice = _notice(api)
    row = _by_id(_adm(api)["notices"], notice)
    assert set(row) == {
        "id",
        "created_at",
        "updated_at",
        "title",
        "body",
        "unit_id",
        "pinned",
        "due_at",
        "archived",
    }
    assert (row["body"], row["unit_id"], row["pinned"], row["due_at"], row["archived"]) == (
        "",
        None,
        False,
        None,
        False,
    )
    api.ok(
        "PATCH",
        f"{NOTICES}/{notice}",
        {"unit_id": unit, "pinned": True, "due_at": "2026-11-05T16:00:30+08:00"},
    )
    row = _by_id(_adm(api)["notices"], notice)
    assert (row["unit_id"], row["pinned"], row["due_at"]) == (
        unit,
        True,
        "2026-11-05T08:00:30.000Z",
    )
    api.ok("PATCH", f"{NOTICES}/{notice}", {"unit_id": None, "due_at": None})
    row = _by_id(_adm(api)["notices"], notice)
    assert (row["unit_id"], row["due_at"]) == (None, None)
    # 一般更新不建立 change 紀錄
    assert _adm(api)["changes"] == []


def test_notice_archive_restore_creates_changes(api: ApiClient) -> None:
    _setup_admin(api)
    notice = _notice(api, body="內文")
    original = _by_id(_adm(api)["notices"], notice)

    assert api.ok("POST", f"{NOTICES}/{notice}/archive", {})["result"] == notice
    adm = _adm(api)
    archived = _by_id(adm["notices"], notice)
    assert archived["archived"] is True
    [change] = adm["changes"]
    assert set(change) == {"id", "kind", "record_id", "at", "reason", "before", "after"}
    assert change["kind"] == "notice.archive"
    assert change["record_id"] == notice
    assert change["reason"] == "封存公告"
    assert change["before"] == original
    assert change["after"] == archived
    assert change["at"] == archived["updated_at"]
    # 封存後仍可一般編輯
    api.ok("PATCH", f"{NOTICES}/{notice}", {"title": "已封存的提醒"})
    # 重複封存 409
    assert _error(api.mutate("POST", f"{NOTICES}/{notice}/archive", {})) == (
        409,
        "office_transition_invalid",
    )

    api.ok("POST", f"{NOTICES}/{notice}/restore", {})
    adm = _adm(api)
    restored = _by_id(adm["notices"], notice)
    assert restored["archived"] is False
    assert [c["kind"] for c in adm["changes"]] == ["notice.archive", "notice.restore"]
    second = adm["changes"][1]
    assert second["reason"] == "還原公告"
    assert second["before"]["title"] == "已封存的提醒"
    assert second["before"]["archived"] is True
    assert second["after"] == restored
    assert _error(api.mutate("POST", f"{NOTICES}/{notice}/restore", {})) == (
        409,
        "office_transition_invalid",
    )
    # 理由由伺服器寫入，不接受使用者提供
    assert _error(api.mutate("POST", f"{NOTICES}/{notice}/archive", {"reason": "自訂"})) == (
        422,
        "office_fields_invalid",
    )


def test_notice_archive_change_limit(api: ApiClient, db_engine: Engine) -> None:
    _setup_admin(api)
    notice = _notice(api)
    with db_engine.begin() as conn:
        workspace_id = conn.execute(text("SELECT id FROM workspace")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO adm_change (id, workspace_id, kind, record_id, at, reason, before,"
                " after) SELECT gen_random_uuid(), :w, 'notice.archive', :n, now(), '測試',"
                " '{}'::jsonb, '{}'::jsonb FROM generate_series(1, 200)"
            ),
            {"w": workspace_id, "n": notice},
        )
    assert _error(api.mutate("POST", f"{NOTICES}/{notice}/archive", {})) == (
        422,
        "office_change_limit",
    )


# --- 欄位驗證 -----------------------------------------------------------------------


def test_extra_field_office_fields_invalid(api: ApiClient) -> None:
    _setup_admin(api)
    unit = _unit(api)
    before = api.snapshot()
    body = {"code": "S-09", "alias": "乙", "unit_id": unit, "checker_id": str(uuid.uuid4())}
    assert _error(api.mutate("POST", STAFF, body)) == (422, "office_fields_invalid")
    assert api.snapshot() == before


def test_record_limit_units(api: ApiClient, db_engine: Engine) -> None:
    _setup_admin(api)
    with db_engine.begin() as conn:
        workspace_id = conn.execute(text("SELECT id FROM workspace")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO adm_unit (id, workspace_id, name, kind, parent_id, active,"
                " created_at, updated_at) SELECT gen_random_uuid(), :w, '單位' || g, 'branch',"
                " NULL, true, now(), now() FROM generate_series(1, 50) g"
            ),
            {"w": workspace_id},
        )
    assert _error(api.mutate("POST", UNITS, {"name": "超出", "kind": "branch"})) == (
        422,
        "office_record_limit",
    )


def test_other_workspace_unit_missing(api: ApiClient, make_client) -> None:
    _setup_admin(api)
    unit = _unit(api)
    other = ApiClient(make_client())
    _setup_admin(other)
    r = other.mutate("POST", STAFF, {"code": "S-01", "alias": "乙", "unit_id": unit})
    assert _error(r) == (404, "office_record_missing")


MISSING = "00000000-0000-4000-8000-000000000000"


def _rejections(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any], int, str]]:
    unit, staff, eq, notice, inactive = (
        ids["unit"],
        ids["staff"],
        ids["equipment"],
        ids["notice"],
        ids["inactive_unit"],
    )
    return [
        # 共通前置檢查
        (
            "POST",
            UNITS,
            {"name": "甲", "kind": "branch", "bank_account": "1"},
            422,
            "simulation_required",
        ),
        ("POST", UNITS, {"name": "甲", "kind": "branch", "on_hand": 1}, 422, "protected_field"),
        # 啟用
        ("POST", ENABLE, {}, 409, "office_already_enabled"),
        # 組織
        ("POST", UNITS, {"name": "甲"}, 422, "office_fields_invalid"),
        (
            "POST",
            UNITS,
            {"name": "甲", "kind": "branch", "active": False},
            422,
            "office_fields_invalid",
        ),
        ("POST", UNITS, {"name": "", "kind": "branch"}, 422, "office_text_invalid"),
        ("POST", UNITS, {"name": "   ", "kind": "branch"}, 422, "office_text_invalid"),
        ("POST", UNITS, {"name": "x" * 101, "kind": "branch"}, 422, "office_text_invalid"),
        ("POST", UNITS, {"name": "a\x07b", "kind": "branch"}, 422, "office_text_invalid"),
        ("POST", UNITS, {"name": 5, "kind": "branch"}, 422, "office_text_invalid"),
        ("POST", UNITS, {"name": "甲", "kind": "team"}, 422, "office_state_invalid"),
        (
            "POST",
            UNITS,
            {"name": "甲", "kind": "branch", "parent_id": "abc"},
            422,
            "office_id_invalid",
        ),
        (
            "POST",
            UNITS,
            {"name": "甲", "kind": "branch", "parent_id": MISSING},
            404,
            "office_record_missing",
        ),
        (
            "POST",
            UNITS,
            {"name": "甲", "kind": "branch", "parent_id": inactive},
            409,
            "office_unit_inactive",
        ),
        ("PATCH", f"{UNITS}/{unit}", {}, 422, "office_fields_invalid"),
        ("PATCH", f"{UNITS}/{unit}", {"kind": "department"}, 422, "office_fields_invalid"),
        ("PATCH", f"{UNITS}/{unit}", {"active": "no"}, 422, "office_fields_invalid"),
        ("PATCH", f"{UNITS}/{unit}", {"active": False}, 409, "office_unit_inactive"),
        ("PATCH", f"{UNITS}/not-a-uuid", {"name": "乙"}, 422, "office_id_invalid"),
        ("PATCH", f"{UNITS}/{MISSING}", {"name": "乙"}, 404, "office_record_missing"),
        # 假員工
        ("POST", STAFF, {"code": "S-02", "alias": "乙"}, 422, "office_fields_invalid"),
        (
            "POST",
            STAFF,
            {"code": "S-02", "alias": "乙", "unit_id": unit, "status": "active"},
            422,
            "office_fields_invalid",
        ),
        (
            "POST",
            STAFF,
            {"code": "x" * 33, "alias": "乙", "unit_id": unit},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            STAFF,
            {"code": "S-02", "alias": "x" * 81, "unit_id": unit},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            STAFF,
            {"code": "S-02", "alias": "乙", "unit_id": unit, "role_label": 1},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            STAFF,
            {"code": "S-02", "alias": "乙", "unit_id": inactive},
            409,
            "office_unit_inactive",
        ),
        (
            "POST",
            STAFF,
            {"code": "s-01", "alias": "乙", "unit_id": unit},
            422,
            "office_code_duplicate",
        ),
        ("PATCH", f"{STAFF}/{staff}", {"code": "S-03"}, 422, "office_fields_invalid"),
        ("PATCH", f"{STAFF}/{staff}", {"unit_id": inactive}, 422, "office_fields_invalid"),
        ("PATCH", f"{STAFF}/{staff}", {"status": "fired"}, 422, "office_state_invalid"),
        ("PATCH", f"{STAFF}/{staff}", {"checker_id": MISSING}, 422, "office_fields_invalid"),
        # 設備
        (
            "POST",
            EQUIPMENT,
            {"code": "EQ-2", "name": "乙", "unit_id": unit, "state": "available"},
            422,
            "office_fields_invalid",
        ),
        (
            "POST",
            EQUIPMENT,
            {"code": "EQ-2", "name": "x" * 101, "unit_id": unit},
            422,
            "office_text_invalid",
        ),
        (
            "POST",
            EQUIPMENT,
            {"code": "EQ-2", "name": "乙", "unit_id": inactive},
            409,
            "office_unit_inactive",
        ),
        (
            "POST",
            EQUIPMENT,
            {"code": "eq-1", "name": "乙", "unit_id": unit},
            422,
            "office_code_duplicate",
        ),
        ("PATCH", f"{EQUIPMENT}/{eq}", {"state": "broken"}, 422, "office_state_invalid"),
        ("PATCH", f"{EQUIPMENT}/{eq}", {"unit_id": unit}, 422, "office_fields_invalid"),
        ("PATCH", f"{EQUIPMENT}/{eq}", {}, 422, "office_fields_invalid"),
        # 公告
        ("POST", NOTICES, {"body": "內文"}, 422, "office_fields_invalid"),
        ("POST", NOTICES, {"title": "甲", "body": "x" * 2001}, 422, "office_text_invalid"),
        ("POST", NOTICES, {"title": "甲", "pinned": "yes"}, 422, "office_fields_invalid"),
        ("POST", NOTICES, {"title": "甲", "pinned": 1}, 422, "office_fields_invalid"),
        (
            "POST",
            NOTICES,
            {"title": "甲", "due_at": "2026-02-30T10:00:00+08:00"},
            422,
            "office_time_invalid",
        ),
        (
            "POST",
            NOTICES,
            {"title": "甲", "due_at": "2026-11-05 10:00"},
            422,
            "office_time_invalid",
        ),
        ("POST", NOTICES, {"title": "甲", "unit_id": inactive}, 409, "office_unit_inactive"),
        ("POST", NOTICES, {"title": "甲", "unit_id": MISSING}, 404, "office_record_missing"),
        ("PATCH", f"{NOTICES}/{notice}", {"unit_id": inactive}, 409, "office_unit_inactive"),
        ("PATCH", f"{NOTICES}/{notice}", {"archived": True}, 422, "office_fields_invalid"),
        ("PATCH", f"{NOTICES}/{notice}", {}, 422, "office_fields_invalid"),
        ("POST", f"{NOTICES}/{notice}/restore", {}, 409, "office_transition_invalid"),
        ("POST", f"{NOTICES}/{notice}/archive", {"reason": "自訂"}, 422, "office_fields_invalid"),
        ("POST", f"{NOTICES}/{MISSING}/archive", {}, 404, "office_record_missing"),
    ]


_CASES = _rejections(
    {k: f"<{k}>" for k in ("unit", "staff", "equipment", "notice", "inactive_unit")}
)


@pytest.mark.parametrize(
    "index",
    range(len(_CASES)),
    ids=[f"{c[1].rsplit('/', 1)[-1]}-{c[4]}-{i}" for i, c in enumerate(_CASES)],
)
def test_rejections_leave_snapshot_unchanged(api: ApiClient, index: int) -> None:
    _setup_admin(api)
    unit = _unit(api)
    inactive = _unit(api, "停用單位")
    api.ok("PATCH", f"{UNITS}/{inactive}", {"active": False})
    staff = _staff(api, unit)
    eq = _equipment(api, unit)
    notice = _notice(api)
    ids = {
        "unit": unit,
        "staff": staff,
        "equipment": eq,
        "notice": notice,
        "inactive_unit": inactive,
    }
    method, path, body, status, code = _rejections(ids)[index]
    before = api.snapshot()
    r = api.mutate(method, path, copy.deepcopy(body))
    assert _error(r) == (status, code), r.text
    after = api.snapshot()
    assert after == before
    assert after["version"] == before["version"]


# --- 驗證器 -------------------------------------------------------------------------


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(Problem) as exc:
        fn(*args, **kwargs)
    return exc.value.code


def test_validators_unit() -> None:
    v.strict_keys({"a": 1}, {"a"}, {"b"})
    assert _code(v.strict_keys, {"a": 1, "c": 2}, {"a"}, set()) == "office_fields_invalid"
    assert _code(v.strict_keys, {}, {"a"}, set()) == "office_fields_invalid"
    assert _code(v.strict_keys, [], set(), set()) == "office_fields_invalid"
    assert _code(v.strict_keys, {"__proto__": 1}, set(), {"__proto__"}) == "office_fields_invalid"
    assert v.text("  甲 ") == "  甲 "
    assert v.text("", allow_empty=True) == ""
    assert _code(v.text, "x" * 33, max=32) == "office_text_invalid"
    assert v.enum_value("a", ("a", "b")) == "a"
    assert _code(v.enum_value, "c", ("a", "b")) == "office_state_invalid"
    assert v.integer(5) == 5
    assert v.integer(5.0) == 5
    for bad in (True, -1, 1_000_000_001, 1.5, "1", None):
        assert _code(v.integer, bad) == "office_number_invalid"
    assert _code(v.integer, 0, min=1) == "office_number_invalid"
    start, end = v.interval(
        "2026-11-02T09:00:00+08:00", "2026-11-02T17:00:00+08:00", max_minutes=2880
    )
    assert (end - start).total_seconds() == 8 * 3600
    assert (
        _code(v.interval, "2026-11-02T09:00:00Z", "2026-11-02T09:00:00Z", max_minutes=2880)
        == "office_interval_invalid"
    )
    assert (
        _code(v.interval, "2026-11-02T00:00:00Z", "2026-11-04T00:01:00Z", max_minutes=2880)
        == "office_interval_invalid"
    )
    assert (
        _code(v.interval, "2026-11-02T09:00:30Z", "2026-11-02T10:00:00Z", max_minutes=2880)
        == "office_time_invalid"
    )
    assert v.break_minutes(59, start, end) == 59
    assert _code(v.break_minutes, 480, start, end) == "office_break_invalid"
    assert _code(v.break_minutes, -1, start, end) == "office_number_invalid"
    assert _code(v.break_minutes, 2881, start, end) == "office_number_invalid"
    assert _code(v.uuid_value, "ABC") == "office_id_invalid"
    assert v.uuid_value("0F0E0D0C-0B0A-4000-8000-000000000001") == (
        "0f0e0d0c-0b0a-4000-8000-000000000001"
    )


# --- 快照與還原 ---------------------------------------------------------------------


def _ws_id(db_engine: Engine) -> str:
    with db_engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM workspace")).scalar_one())


def _wipe_admin(db_engine: Engine) -> None:
    with db_engine.begin() as conn:
        for table in (
            "adm_change",
            "adm_reservation",
            "adm_request_transition",
            "adm_request",
            "adm_attendance",
            "adm_shift",
            "adm_notice",
            "adm_equipment",
            "adm_staff",
            "adm_unit",
        ):
            conn.execute(text(f"DELETE FROM {table}"))


def _restore(db_engine: Engine, data: dict[str, Any]) -> None:
    workspace_id = _ws_id(db_engine)
    with Session(db_engine) as db:
        adm_snapshot.restore(db, workspace_id, data)
        db.commit()


def _full_admin(unit: str, staff: str, eq: str) -> dict[str, Any]:
    t = "2026-11-02T01:00:00.000Z"
    n = lambda: str(uuid.uuid4())  # noqa: E731
    stamp = lambda: {"id": n(), "created_at": t, "updated_at": t}  # noqa: E731
    request = {
        **stamp(),
        "type": "leave",
        "staff_id": staff,
        "unit_id": unit,
        "title": "請假",
        "description": "",
        "amount_minor": 0,
        "currency": "SIM",
        "start_at": "2026-11-03T01:00:00.000Z",
        "end_at": "2026-11-03T09:00:00.000Z",
        "status": "draft",
        "processing_note": "",
        "transitions": [{"status": "draft", "at": t, "note": ""}],
    }
    return {
        "units": [
            {
                "id": unit,
                "created_at": t,
                "updated_at": t,
                "name": "門市",
                "kind": "branch",
                "parent_id": None,
                "active": True,
            },
        ],
        "staff": [
            {
                "id": staff,
                "created_at": t,
                "updated_at": t,
                "code": "S-01",
                "alias": "甲",
                "unit_id": unit,
                "role_label": "",
                "status": "active",
            },
        ],
        "shifts": [
            {
                **stamp(),
                "staff_id": staff,
                "unit_id": unit,
                "start_at": "2026-11-02T01:00:00.000Z",
                "end_at": "2026-11-02T09:00:00.000Z",
                "break_minutes": 60,
                "note": "",
                "status": "scheduled",
            },
        ],
        "attendance": [
            {
                **stamp(),
                "staff_id": staff,
                "unit_id": unit,
                "start_at": "2026-11-02T01:05:00.000Z",
                "end_at": "2026-11-02T08:55:00.000Z",
                "break_minutes": 60,
                "note": "手動輸入",
                "voided": False,
            },
        ],
        "requests": [request],
        "equipment": [
            {
                "id": eq,
                "created_at": t,
                "updated_at": t,
                "code": "EQ-1",
                "name": "平板",
                "unit_id": unit,
                "state": "available",
            },
        ],
        "reservations": [
            {
                **stamp(),
                "equipment_id": eq,
                "staff_id": staff,
                "start_at": "2026-11-03T05:00:00.000Z",
                "end_at": "2026-11-03T07:00:00.000Z",
                "purpose": "",
                "status": "reserved",
            },
        ],
        "notices": [
            {
                **stamp(),
                "title": "提醒",
                "body": "",
                "unit_id": unit,
                "pinned": True,
                "due_at": "2026-11-05T08:00:30.000Z",
                "archived": False,
            },
        ],
        "changes": [],
    }


def test_snapshot_restore_roundtrip(api: ApiClient, db_engine: Engine) -> None:
    _setup_admin(api)
    unit = _unit(api)
    child = _unit(api, "行政組", "department", parent_id=unit)
    _staff(api, child)
    _equipment(api, unit)
    notice = _notice(api, unit_id=unit, due_at="2026-11-05T16:00:00+08:00")
    api.ok("POST", f"{NOTICES}/{notice}/archive", {})
    before = api.snapshot()

    _wipe_admin(db_engine)
    assert _adm(api) == {k: [] for k in ADM_KEYS}
    _restore(db_engine, {"administration": copy.deepcopy(before["administration"])})
    assert api.snapshot() == before

    # 其他集合的資料列也能還原並原樣輸出
    _wipe_admin(db_engine)
    data = _full_admin(str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()))
    _restore(db_engine, {"administration": copy.deepcopy(data)})
    assert _adm(api) == data


def test_restore_rejects_schema(api: ApiClient, db_engine: Engine) -> None:
    """識別碼重複由備份匯入統一檢查（見 test_backup 的 id_collision 測試）。"""
    _setup_admin(api)
    workspace_id = _ws_id(db_engine)
    unit = str(uuid.uuid4())
    data = _full_admin(unit, str(uuid.uuid4()), str(uuid.uuid4()))
    extra = copy.deepcopy(data)
    extra["units"][0]["checker_id"] = unit
    with Session(db_engine) as db:
        assert _code(adm_snapshot.restore, db, workspace_id, {"administration": extra}) == (
            "office_fields_invalid"
        )
        db.rollback()
    # 啟用行政模組卻沒有行政資料
    with Session(db_engine) as db:
        assert _code(adm_snapshot.restore, db, workspace_id, {}) == "office_schema_invalid"
        db.rollback()
