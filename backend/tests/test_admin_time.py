"""行政時段：班次、手動出勤、設備借用、附理由更正與複製整週排班（A§1、A§2）。"""

import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from src.core import clock
from src.core.problem import Problem
from src.modules.administration import invariants as adm_invariants
from src.modules.administration import snapshot as adm_snapshot
from src.modules.administration.attendance import actual_work_minutes
from tests.helpers import ApiClient

BASE = "/api/v1/administration"
UNITS = f"{BASE}/units"
STAFF = f"{BASE}/staff"
EQUIPMENT = f"{BASE}/equipment"
SHIFTS = f"{BASE}/shifts"
COPY_WEEK = f"{SHIFTS}/copy-week"
ATTENDANCE = f"{BASE}/attendance"
RESERVATIONS = f"{BASE}/reservations"
MISSING = "00000000-0000-4000-8000-000000000000"


def _error(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def _t(day: str, hm: str) -> str:
    """台北時間字串，例如 _t("2026-11-03", "09:00")。"""
    return f"{day}T{hm}:00+08:00"


def _adm(api: ApiClient) -> dict[str, Any]:
    return api.snapshot()["administration"]


def _by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next(r for r in rows if r["id"] == row_id)


def _base(api: ApiClient) -> tuple[str, str]:
    api.setup("general")
    unit = api.ok("POST", UNITS, {"name": "門市", "kind": "branch"})["result"]
    staff = api.ok("POST", STAFF, {"code": "S-01", "alias": "示範夥伴甲", "unit_id": unit})[
        "result"
    ]
    return unit, staff


def _shift(api: ApiClient, unit: str, staff: str, day: str, start: str, end: str, **extra) -> str:
    body = {"staff_id": staff, "unit_id": unit, "start_at": _t(day, start), "end_at": _t(day, end)}
    return api.ok("POST", SHIFTS, {**body, **extra})["result"]


def _attendance(
    api: ApiClient, unit: str, staff: str, day: str, start: str, end: str, **extra
) -> str:
    body = {"staff_id": staff, "unit_id": unit, "start_at": _t(day, start), "end_at": _t(day, end)}
    return api.ok("POST", ATTENDANCE, {**body, **extra})["result"]


def _equipment(api: ApiClient, unit: str, code: str = "EQ-1") -> str:
    return api.ok("POST", EQUIPMENT, {"code": code, "name": "收銀平板", "unit_id": unit})["result"]


def _reserve(api: ApiClient, eq: str, staff: str, day: str, start: str, end: str) -> str:
    body = {
        "equipment_id": eq,
        "staff_id": staff,
        "start_at": _t(day, start),
        "end_at": _t(day, end),
    }
    return api.ok("POST", RESERVATIONS, body)["result"]


def _rejected(api: ApiClient, method: str, path: str, body: dict[str, Any]) -> tuple[int, str]:
    """送出應被拒絕的命令，並確認快照與版本完全沒變。"""
    before = api.snapshot()
    r = api.mutate(method, path, body)
    after = api.snapshot()
    assert after == before
    assert after["version"] == before["version"]
    return _error(r)


# --- 班次 ---------------------------------------------------------------------------


def test_shift_create_defaults(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00")
    row = _by_id(_adm(api)["shifts"], shift)
    assert set(row) == {
        "id",
        "created_at",
        "updated_at",
        "staff_id",
        "unit_id",
        "start_at",
        "end_at",
        "break_minutes",
        "note",
        "status",
    }
    assert row["start_at"] == "2026-11-03T01:00:00.000Z"
    assert row["end_at"] == "2026-11-03T09:00:00.000Z"
    assert (row["break_minutes"], row["note"], row["status"]) == (0, "", "scheduled")


def test_back_to_back_shifts_allowed(api: ApiClient) -> None:
    unit, staff = _base(api)
    _shift(api, unit, staff, "2026-11-03", "09:00", "13:00")
    _shift(api, unit, staff, "2026-11-03", "13:00", "17:00")
    # 另一位員工同時段不受影響；出勤與班次各自獨立
    other = api.ok("POST", STAFF, {"code": "S-02", "alias": "乙", "unit_id": unit})["result"]
    _shift(api, unit, other, "2026-11-03", "10:00", "12:00")
    _attendance(api, unit, staff, "2026-11-03", "10:00", "12:00")
    _attendance(api, unit, staff, "2026-11-03", "12:00", "14:00")
    eq = _equipment(api, unit)
    _reserve(api, eq, staff, "2026-11-04", "09:00", "10:00")
    _reserve(api, eq, other, "2026-11-04", "10:00", "11:00")
    adm = _adm(api)
    assert (len(adm["shifts"]), len(adm["attendance"]), len(adm["reservations"])) == (3, 2, 2)


def test_overlap_409(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "13:00")
    body = {
        "staff_id": staff,
        "unit_id": unit,
        "start_at": _t("2026-11-03", "12:59"),
        "end_at": _t("2026-11-03", "15:00"),
    }
    assert _rejected(api, "POST", SHIFTS, body) == (409, "office_time_conflict")
    # 包含關係也算重疊
    inner = {**body, "start_at": _t("2026-11-03", "10:00"), "end_at": _t("2026-11-03", "11:00")}
    assert _rejected(api, "POST", SHIFTS, inner) == (409, "office_time_conflict")
    # 取消後時段釋出
    api.ok("POST", f"{SHIFTS}/{shift}/cancel", {})
    api.ok("POST", SHIFTS, body)

    _attendance(api, unit, staff, "2026-11-03", "09:00", "13:00")
    assert _rejected(api, "POST", ATTENDANCE, body) == (409, "office_time_conflict")

    eq = _equipment(api, unit)
    other = api.ok("POST", STAFF, {"code": "S-02", "alias": "乙", "unit_id": unit})["result"]
    _reserve(api, eq, staff, "2026-11-04", "09:00", "11:00")
    clash = {
        "equipment_id": eq,
        "staff_id": other,
        "start_at": _t("2026-11-04", "10:00"),
        "end_at": _t("2026-11-04", "12:00"),
    }
    assert _rejected(api, "POST", RESERVATIONS, clash) == (409, "office_time_conflict")


def test_shift_cancel_and_complete(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2025-10-06", "09:00", "17:00")
    assert api.ok("POST", f"{SHIFTS}/{shift}/complete", {})["result"] == shift
    assert _by_id(_adm(api)["shifts"], shift)["status"] == "completed"
    # 只有已排定的班次可以取消或完成
    assert _rejected(api, "POST", f"{SHIFTS}/{shift}/cancel", {}) == (
        409,
        "office_transition_invalid",
    )
    assert _rejected(api, "POST", f"{SHIFTS}/{shift}/complete", {}) == (
        409,
        "office_transition_invalid",
    )
    other = _shift(api, unit, staff, "2025-10-07", "09:00", "17:00")
    api.ok("POST", f"{SHIFTS}/{other}/cancel", {})
    assert _by_id(_adm(api)["shifts"], other)["status"] == "cancelled"


def test_complete_before_end_409_office_shift_not_finished(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2099-01-05", "09:00", "17:00")
    assert _rejected(api, "POST", f"{SHIFTS}/{shift}/complete", {}) == (
        409,
        "office_shift_not_finished",
    )


def test_complete_never_creates_attendance(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2025-10-06", "09:00", "17:00", break_minutes=60)
    api.ok("POST", f"{SHIFTS}/{shift}/complete", {})
    adm = _adm(api)
    assert adm["attendance"] == []
    assert adm["changes"] == []


# --- 出勤 ---------------------------------------------------------------------------


def _work_minutes(api: ApiClient, db_engine: Engine) -> int:
    with Session(db_engine) as db:
        workspace_id = str(db.execute(text("SELECT id FROM workspace")).scalar_one())
        return actual_work_minutes(db, workspace_id)


def test_void_frees_slot_and_excluded_from_minutes(api: ApiClient, db_engine: Engine) -> None:
    unit, staff = _base(api)
    first = _attendance(api, unit, staff, "2026-11-03", "09:00", "17:00", break_minutes=60)
    _attendance(api, unit, staff, "2026-11-04", "09:00", "12:00")
    assert _work_minutes(api, db_engine) == 7 * 60 + 3 * 60
    original = _by_id(_adm(api)["attendance"], first)
    assert original["voided"] is False

    assert api.ok("POST", f"{ATTENDANCE}/{first}/void", {"reason": "輸入錯誤"})["result"] == first
    adm = _adm(api)
    voided = _by_id(adm["attendance"], first)
    assert voided["voided"] is True
    [change] = adm["changes"]
    assert (change["kind"], change["record_id"], change["reason"]) == (
        "attendance.void",
        first,
        "輸入錯誤",
    )
    assert change["before"] == original
    assert change["after"] == voided
    # 作廢的紀錄仍保留，但不計入工時，也不再佔用時段
    assert _work_minutes(api, db_engine) == 3 * 60
    _attendance(api, unit, staff, "2026-11-03", "10:00", "16:00")
    # 已作廢不可再作廢或更正
    assert _rejected(api, "POST", f"{ATTENDANCE}/{first}/void", {"reason": "再一次"}) == (
        409,
        "office_transition_invalid",
    )
    assert _rejected(api, "PATCH", f"{ATTENDANCE}/{first}", {"reason": "改", "note": "x"}) == (
        409,
        "office_transition_invalid",
    )


# --- 附理由更正 ---------------------------------------------------------------------


def test_clock_step_back_keeps_time_monotonic(
    api: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """系統時鐘倒退（WSL 實測約 1.5 秒）時，同一工作區的時間不倒退，更正仍成功。"""
    t0 = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    current = [t0]
    monkeypatch.setattr(clock, "utcnow", lambda: current[0])
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00")
    current[0] = t0 + timedelta(seconds=10)
    api.ok("PATCH", f"{SHIFTS}/{shift}", {"reason": "第一次", "note": "一"})
    current[0] = t0 + timedelta(seconds=8, milliseconds=500)
    api.ok("PATCH", f"{SHIFTS}/{shift}", {"reason": "第二次", "note": "二"})
    first, second = _adm(api)["changes"]
    assert second["at"] >= first["at"] == "2026-11-02T00:00:10.000Z"
    assert _by_id(_adm(api)["shifts"], shift)["updated_at"] == second["at"]


def test_correction_keeps_before_after(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00", note="早班")
    original = _by_id(_adm(api)["shifts"], shift)
    body = {"reason": "調整到晚一小時", "start_at": _t("2026-11-03", "10:00"), "break_minutes": 30}
    assert api.ok("PATCH", f"{SHIFTS}/{shift}", body)["result"] == shift
    adm = _adm(api)
    corrected = _by_id(adm["shifts"], shift)
    assert corrected["start_at"] == "2026-11-03T02:00:00.000Z"
    assert corrected["end_at"] == original["end_at"]
    assert (corrected["break_minutes"], corrected["note"]) == (30, "早班")
    [change] = adm["changes"]
    assert set(change) == {"id", "kind", "record_id", "at", "reason", "before", "after"}
    assert (change["kind"], change["record_id"], change["reason"]) == (
        "shift.update",
        shift,
        "調整到晚一小時",
    )
    assert change["before"] == original
    assert change["after"] == corrected
    assert change["at"] == corrected["updated_at"]

    # 第二次更正接續前一筆
    api.ok("PATCH", f"{SHIFTS}/{shift}", {"reason": "補備註", "note": "早班（已調整）"})
    adm = _adm(api)
    assert [c["kind"] for c in adm["changes"]] == ["shift.update", "shift.update"]
    assert adm["changes"][1]["before"] == corrected
    # 完成後仍可輸出（最新更正與現有資料只差狀態與更新時間）
    api.ok("POST", f"{SHIFTS}/{shift}/cancel", {})

    attendance = _attendance(api, unit, staff, "2026-11-03", "09:00", "17:00")
    api.ok(
        "PATCH",
        f"{ATTENDANCE}/{attendance}",
        {"reason": "實際晚到", "start_at": _t("2026-11-03", "09:10")},
    )
    eq = _equipment(api, unit)
    reservation = _reserve(api, eq, staff, "2026-11-04", "09:00", "10:00")
    api.ok(
        "PATCH",
        f"{RESERVATIONS}/{reservation}",
        {"reason": "延長", "end_at": _t("2026-11-04", "11:00"), "purpose": "盤點"},
    )
    adm = _adm(api)
    kinds = [c["kind"] for c in adm["changes"]]
    assert kinds == ["shift.update", "shift.update", "attendance.update", "reservation.update"]
    res_change = adm["changes"][-1]
    assert res_change["after"] == _by_id(adm["reservations"], reservation)
    assert res_change["before"]["purpose"] == ""
    # 借用歸還後，最新更正只差狀態
    api.ok("POST", f"{RESERVATIONS}/{reservation}/return", {})
    assert _by_id(_adm(api)["reservations"], reservation)["status"] == "returned"


def test_correction_noop_rejected(api: ApiClient) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00", note="早班")
    # 值與現有相同（含時區寫法不同但同一時刻）
    for body in (
        {"reason": "沒改", "note": "早班"},
        {"reason": "沒改", "start_at": "2026-11-03T01:00:00Z"},
    ):
        assert _rejected(api, "PATCH", f"{SHIFTS}/{shift}", body) == (
            422,
            "office_change_invalid",
        )
    attendance = _attendance(api, unit, staff, "2026-11-03", "09:00", "17:00")
    assert _rejected(
        api, "PATCH", f"{ATTENDANCE}/{attendance}", {"reason": "沒改", "note": ""}
    ) == (
        422,
        "office_change_invalid",
    )


def test_correction_change_limit(api: ApiClient, db_engine: Engine) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00")
    with db_engine.begin() as conn:
        workspace_id = conn.execute(text("SELECT id FROM workspace")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO adm_change (id, workspace_id, kind, record_id, at, reason, before,"
                " after) SELECT gen_random_uuid(), :w, 'shift.update', :s, now(), '測試',"
                " '{}'::jsonb, '{}'::jsonb FROM generate_series(1, 200)"
            ),
            {"w": workspace_id, "s": shift},
        )
    r = api.mutate("PATCH", f"{SHIFTS}/{shift}", {"reason": "改", "note": "x"})
    assert _error(r) == (422, "office_change_limit")


# --- 複製整週 -----------------------------------------------------------------------


def test_copy_week_basic(api: ApiClient) -> None:
    unit, staff = _base(api)
    a = _shift(api, unit, staff, "2026-11-02", "09:00", "17:00", break_minutes=60, note="週一")
    _shift(api, unit, staff, "2026-11-04", "13:00", "21:00")
    # 下一週不在來源範圍
    _shift(api, unit, staff, "2026-11-09", "00:00", "08:00")
    body = api.ok("POST", COPY_WEEK, {"from_date": "2026-11-02", "to_date": "2026-11-16"})
    shifts = _adm(api)["shifts"]
    assert len(shifts) == 5
    copies = shifts[3:]
    assert body["result"] == copies[0]["id"]
    source = _by_id(shifts, a)
    first = copies[0]
    assert first["id"] not in {s["id"] for s in shifts[:3]}
    assert first["start_at"] == "2026-11-16T01:00:00.000Z"
    assert first["end_at"] == "2026-11-16T09:00:00.000Z"
    assert (first["staff_id"], first["unit_id"], first["break_minutes"], first["note"]) == (
        source["staff_id"],
        source["unit_id"],
        60,
        "週一",
    )
    assert first["status"] == "scheduled"
    assert copies[1]["start_at"] == "2026-11-18T05:00:00.000Z"


def test_copy_week_atomic_on_conflict(api: ApiClient) -> None:
    unit, staff = _base(api)
    _shift(api, unit, staff, "2026-11-02", "09:00", "17:00")
    _shift(api, unit, staff, "2026-11-03", "09:00", "17:00")
    # 目標週已有與第二筆複製結果重疊的班次
    _shift(api, unit, staff, "2026-11-10", "16:00", "20:00")
    body = {"from_date": "2026-11-02", "to_date": "2026-11-09"}
    assert _rejected(api, "POST", COPY_WEEK, body) == (409, "office_time_conflict")
    assert len(_adm(api)["shifts"]) == 3


def test_copy_week_includes_completed(api: ApiClient) -> None:
    unit, staff = _base(api)
    done = _shift(api, unit, staff, "2025-10-06", "09:00", "17:00")
    api.ok("POST", f"{SHIFTS}/{done}/complete", {})
    gone = _shift(api, unit, staff, "2025-10-14", "09:00", "17:00")
    api.ok("POST", f"{SHIFTS}/{gone}/cancel", {})
    api.ok("POST", COPY_WEEK, {"from_date": "2025-10-06", "to_date": "2026-11-02"})
    shifts = _adm(api)["shifts"]
    assert len(shifts) == 3
    copy_row = shifts[-1]
    assert copy_row["status"] == "scheduled"
    assert copy_row["start_at"] == "2026-11-02T01:00:00.000Z"
    # 只有取消的班次時，來源週視為空
    assert _rejected(
        api, "POST", COPY_WEEK, {"from_date": "2025-10-13", "to_date": "2026-11-09"}
    ) == (422, "office_week_empty")


def test_week_boundary_taipei(api: ApiClient) -> None:
    unit, staff = _base(api)
    # 週日 23:30（台北）開始、跨到週一的班次，歸在開始的那一週
    body = {
        "staff_id": staff,
        "unit_id": unit,
        "start_at": "2026-11-08T23:30:00+08:00",
        "end_at": "2026-11-09T07:30:00+08:00",
    }
    api.ok("POST", SHIFTS, body)
    assert _rejected(
        api, "POST", COPY_WEEK, {"from_date": "2026-11-09", "to_date": "2026-11-23"}
    ) == (422, "office_week_empty")
    api.ok("POST", COPY_WEEK, {"from_date": "2026-11-02", "to_date": "2026-11-16"})
    shifts = _adm(api)["shifts"]
    assert len(shifts) == 2
    assert shifts[1]["start_at"] == "2026-11-22T15:30:00.000Z"
    assert shifts[1]["end_at"] == "2026-11-22T23:30:00.000Z"


# --- 借用 ---------------------------------------------------------------------------


def test_reservation_requires_available_equipment(api: ApiClient) -> None:
    unit, staff = _base(api)
    eq = _equipment(api, unit)
    api.ok("PATCH", f"{EQUIPMENT}/{eq}", {"state": "maintenance"})
    body = {
        "equipment_id": eq,
        "staff_id": staff,
        "start_at": _t("2026-11-04", "09:00"),
        "end_at": _t("2026-11-04", "10:00"),
    }
    assert _rejected(api, "POST", RESERVATIONS, body) == (409, "office_equipment_unavailable")
    api.ok("PATCH", f"{EQUIPMENT}/{eq}", {"state": "available"})
    # 員工不必屬於設備的單位
    other_unit = api.ok("POST", UNITS, {"name": "倉庫", "kind": "branch"})["result"]
    other = api.ok("POST", STAFF, {"code": "S-02", "alias": "乙", "unit_id": other_unit})["result"]
    reservation = api.ok("POST", RESERVATIONS, {**body, "staff_id": other})["result"]
    row = _by_id(_adm(api)["reservations"], reservation)
    assert (row["purpose"], row["status"]) == ("", "reserved")
    # 借用中的設備不能改成維修
    assert _rejected(api, "PATCH", f"{EQUIPMENT}/{eq}", {"state": "maintenance"}) == (
        409,
        "office_equipment_unavailable",
    )
    api.ok("POST", f"{RESERVATIONS}/{reservation}/return", {})
    api.ok("PATCH", f"{EQUIPMENT}/{eq}", {"state": "maintenance"})
    assert _rejected(api, "POST", f"{RESERVATIONS}/{reservation}/cancel", {}) == (
        409,
        "office_transition_invalid",
    )


def test_reservation_cancel_frees_slot(api: ApiClient) -> None:
    unit, staff = _base(api)
    eq = _equipment(api, unit)
    first = _reserve(api, eq, staff, "2026-11-04", "09:00", "12:00")
    api.ok("POST", f"{RESERVATIONS}/{first}/cancel", {})
    _reserve(api, eq, staff, "2026-11-04", "10:00", "11:00")
    # 最長 31 天
    long = {
        "equipment_id": eq,
        "staff_id": staff,
        "start_at": _t("2026-12-01", "00:00"),
        "end_at": _t("2027-01-01", "00:00"),
    }
    api.ok("POST", RESERVATIONS, long)


# --- 一致性：change 鏈（匯入） ------------------------------------------------------


def _ws_id(db_engine: Engine) -> str:
    with db_engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM workspace")).scalar_one())


def _check_restored(db_engine: Engine, data: dict[str, Any]) -> str | None:
    """寫入匯入資料後跑一致性檢查；回傳錯誤碼（通過則 None），一律回滾。"""
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


def test_restore_validates_change_chain(api: ApiClient, db_engine: Engine) -> None:
    unit, staff = _base(api)
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00")
    api.ok("PATCH", f"{SHIFTS}/{shift}", {"reason": "改時間", "end_at": _t("2026-11-03", "18:00")})
    api.ok("PATCH", f"{SHIFTS}/{shift}", {"reason": "加備註", "note": "加班"})
    attendance = _attendance(api, unit, staff, "2026-11-03", "09:00", "17:00")
    api.ok("POST", f"{ATTENDANCE}/{attendance}/void", {"reason": "重複"})
    good = _adm(api)
    assert _check_restored(db_engine, copy.deepcopy(good)) is None

    def tampered(mutate) -> str | None:
        data = copy.deepcopy(good)
        mutate(data)
        return _check_restored(db_engine, data)

    def set_(path: list[Any], value: Any):
        def run(data: dict[str, Any]) -> None:
            node: Any = data
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value

        return run

    # 更正改了不允許的欄位
    assert tampered(set_(["changes", 0, "after", "status"], "completed")) == "office_change_invalid"

    # 沒有實際變更
    def noop(data):
        data["changes"][1]["after"]["note"] = ""
        data["shifts"][0]["note"] = ""

    assert tampered(noop) == "office_change_invalid"
    # 前後不連續
    assert tampered(set_(["changes", 1, "before", "note"], "別的")) == "office_change_invalid"
    # 最新更正與現有資料不符
    assert tampered(set_(["shifts", 0, "note"], "被改過")) == "office_change_invalid"
    # 時間順序不符
    assert tampered(set_(["changes", 0, "at"], good["changes"][1]["at"])) == "office_change_invalid"
    # 指向不存在的資料
    assert tampered(set_(["changes", 2, "record_id"], str(uuid.uuid4()))) in {
        "office_record_missing",
        "office_change_invalid",
    }
    # 作廢紀錄的 after 未作廢
    assert tampered(set_(["changes", 2, "after", "voided"], False)) == "office_change_invalid"

    # 匯入資料的時段重疊
    def overlap(data):
        dup = copy.deepcopy(data["attendance"][0])
        dup["id"] = str(uuid.uuid4())
        dup["voided"] = False
        data["attendance"][0]["voided"] = False
        data["attendance"].append(dup)
        data["changes"].pop()

    assert tampered(overlap) == "office_time_conflict"


# --- 錯誤碼：每種失敗情境都不改變快照 ----------------------------------------------


def _rejections(ids: dict[str, str]) -> list[tuple[str, str, dict[str, Any], int, str]]:
    unit, staff, other_staff, inactive_staff, inactive_unit = (
        ids["unit"],
        ids["staff"],
        ids["other_staff"],
        ids["inactive_staff"],
        ids["inactive_unit"],
    )
    shift, cancelled, att, voided = ids["shift"], ids["cancelled"], ids["att"], ids["voided"]
    eq, broken, res, returned = ids["eq"], ids["broken"], ids["res"], ids["returned"]
    day = "2026-11-05"
    new = {
        "staff_id": staff,
        "unit_id": unit,
        "start_at": _t(day, "09:00"),
        "end_at": _t(day, "17:00"),
    }
    booking = {
        "equipment_id": eq,
        "staff_id": staff,
        "start_at": _t(day, "09:00"),
        "end_at": _t(day, "10:00"),
    }
    cases: list[tuple[str, str, dict[str, Any], int, str]] = []
    for path in (SHIFTS, ATTENDANCE):
        cases += [
            ("POST", path, {"staff_id": staff, "unit_id": unit}, 422, "office_fields_invalid"),
            ("POST", path, {**new, "status": "scheduled"}, 422, "office_fields_invalid"),
            ("POST", path, {**new, "voided": False}, 422, "office_fields_invalid"),
            ("POST", path, {**new, "bank_ref": "1"}, 422, "simulation_required"),
            ("POST", path, {**new, "staff_id": "x"}, 422, "office_id_invalid"),
            ("POST", path, {**new, "staff_id": MISSING}, 404, "office_record_missing"),
            ("POST", path, {**new, "unit_id": inactive_unit}, 409, "office_unit_inactive"),
            ("POST", path, {**new, "staff_id": inactive_staff}, 409, "office_staff_inactive"),
            ("POST", path, {**new, "staff_id": other_staff}, 422, "office_unit_mismatch"),
            ("POST", path, {**new, "end_at": _t(day, "09:00")}, 422, "office_interval_invalid"),
            (
                "POST",
                path,
                {**new, "end_at": _t("2026-11-07", "09:01")},
                422,
                "office_interval_invalid",
            ),
            (
                "POST",
                path,
                {**new, "start_at": f"{day}T09:00:30+08:00"},
                422,
                "office_time_invalid",
            ),
            ("POST", path, {**new, "start_at": f"{day} 09:00"}, 422, "office_time_invalid"),
            ("POST", path, {**new, "break_minutes": 480}, 422, "office_break_invalid"),
            ("POST", path, {**new, "break_minutes": -1}, 422, "office_number_invalid"),
            ("POST", path, {**new, "break_minutes": "30"}, 422, "office_number_invalid"),
            ("POST", path, {**new, "note": "x" * 1001}, 422, "office_text_invalid"),
            (
                "POST",
                path,
                {**new, "start_at": _t("2026-11-03", "12:00"), "end_at": _t("2026-11-03", "13:00")},
                409,
                "office_time_conflict",
            ),
        ]
    for path, row in ((SHIFTS, shift), (ATTENDANCE, att)):
        cases += [
            ("PATCH", f"{path}/{row}", {"note": "x"}, 422, "office_fields_invalid"),
            ("PATCH", f"{path}/{row}", {"reason": "改"}, 422, "office_fields_invalid"),
            ("PATCH", f"{path}/{row}", {"reason": " ", "note": "x"}, 422, "office_text_invalid"),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "x" * 1001, "note": "x"},
                422,
                "office_text_invalid",
            ),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "改", "staff_id": staff},
                422,
                "office_fields_invalid",
            ),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "改", "note": "早班"},
                422,
                "office_change_invalid",
            ),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "改", "end_at": _t("2026-11-03", "08:00")},
                422,
                "office_interval_invalid",
            ),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "改", "break_minutes": 480},
                422,
                "office_break_invalid",
            ),
            (
                "PATCH",
                f"{path}/{row}",
                {"reason": "改", "end_at": _t("2026-11-04", "10:00")},
                409,
                "office_time_conflict",
            ),
            (
                "PATCH",
                f"{path}/{MISSING}",
                {"reason": "改", "note": "x"},
                404,
                "office_record_missing",
            ),
        ]
    cases += [
        (
            "PATCH",
            f"{SHIFTS}/{cancelled}",
            {"reason": "改", "note": "x"},
            409,
            "office_transition_invalid",
        ),
        (
            "PATCH",
            f"{SHIFTS}/{shift}",
            {"reason": "改", "status": "completed"},
            422,
            "office_fields_invalid",
        ),
        ("POST", f"{SHIFTS}/{cancelled}/cancel", {}, 409, "office_transition_invalid"),
        ("POST", f"{SHIFTS}/{cancelled}/complete", {}, 409, "office_transition_invalid"),
        ("POST", f"{SHIFTS}/{shift}/complete", {}, 409, "office_shift_not_finished"),
        ("POST", f"{SHIFTS}/{shift}/cancel", {"reason": "x"}, 422, "office_fields_invalid"),
        ("POST", f"{SHIFTS}/{MISSING}/cancel", {}, 404, "office_record_missing"),
        # 複製整週
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026-11-03", "to_date": "2026-11-09"},
            422,
            "office_week_invalid",
        ),
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026-11-02", "to_date": "2026-11-02"},
            422,
            "office_week_invalid",
        ),
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026/11/02", "to_date": "2026-11-09"},
            422,
            "office_week_invalid",
        ),
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026-02-30", "to_date": "2026-11-09"},
            422,
            "office_week_invalid",
        ),
        ("POST", COPY_WEEK, {"from_date": "2026-11-02"}, 422, "office_fields_invalid"),
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026-11-16", "to_date": "2026-11-23"},
            422,
            "office_week_empty",
        ),
        (
            "POST",
            COPY_WEEK,
            {"from_date": "2026-11-02", "to_date": "2026-11-09"},
            409,
            "office_time_conflict",
        ),
        # 出勤作廢
        ("POST", f"{ATTENDANCE}/{att}/void", {}, 422, "office_fields_invalid"),
        ("POST", f"{ATTENDANCE}/{att}/void", {"reason": ""}, 422, "office_text_invalid"),
        (
            "POST",
            f"{ATTENDANCE}/{voided}/void",
            {"reason": "再一次"},
            409,
            "office_transition_invalid",
        ),
        (
            "PATCH",
            f"{ATTENDANCE}/{voided}",
            {"reason": "改", "note": "x"},
            409,
            "office_transition_invalid",
        ),
        # 借用
        (
            "POST",
            RESERVATIONS,
            {**booking, "equipment_id": broken},
            409,
            "office_equipment_unavailable",
        ),
        ("POST", RESERVATIONS, {**booking, "equipment_id": MISSING}, 404, "office_record_missing"),
        (
            "POST",
            RESERVATIONS,
            {**booking, "staff_id": inactive_staff},
            409,
            "office_staff_inactive",
        ),
        ("POST", RESERVATIONS, {**booking, "status": "reserved"}, 422, "office_fields_invalid"),
        ("POST", RESERVATIONS, {**booking, "purpose": "x" * 1001}, 422, "office_text_invalid"),
        (
            "POST",
            RESERVATIONS,
            {**booking, "end_at": _t("2026-12-06", "09:01")},
            422,
            "office_interval_invalid",
        ),
        (
            "POST",
            RESERVATIONS,
            {**booking, "start_at": _t("2026-11-04", "09:30"), "end_at": _t("2026-11-04", "10:30")},
            409,
            "office_time_conflict",
        ),
        ("PATCH", f"{RESERVATIONS}/{res}", {"purpose": "x"}, 422, "office_fields_invalid"),
        ("PATCH", f"{RESERVATIONS}/{res}", {"reason": "改"}, 422, "office_fields_invalid"),
        (
            "PATCH",
            f"{RESERVATIONS}/{res}",
            {"reason": "改", "staff_id": staff},
            422,
            "office_fields_invalid",
        ),
        (
            "PATCH",
            f"{RESERVATIONS}/{res}",
            {"reason": "改", "purpose": ""},
            422,
            "office_change_invalid",
        ),
        (
            "PATCH",
            f"{RESERVATIONS}/{returned}",
            {"reason": "改", "purpose": "x"},
            409,
            "office_transition_invalid",
        ),
        ("POST", f"{RESERVATIONS}/{returned}/return", {}, 409, "office_transition_invalid"),
        ("POST", f"{RESERVATIONS}/{returned}/cancel", {}, 409, "office_transition_invalid"),
    ]
    return cases


_CASES = _rejections(
    {
        k: f"<{k}>"
        for k in (
            "unit",
            "staff",
            "other_staff",
            "inactive_staff",
            "inactive_unit",
            "shift",
            "cancelled",
            "att",
            "voided",
            "eq",
            "broken",
            "res",
            "returned",
        )
    }
)


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定目前時間為 2026-11-02 08:00（台北），讓「未來的班次」不隨執行日期改變。"""
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 11, 2, 0, 0, tzinfo=UTC))


@pytest.mark.parametrize(
    "index",
    range(len(_CASES)),
    ids=[f"{c[0]}-{c[1].removeprefix(BASE)}-{c[4]}-{i}" for i, c in enumerate(_CASES)],
)
def test_rejections_leave_snapshot_unchanged(api: ApiClient, frozen_now: None, index: int) -> None:
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
    api.ok("PATCH", f"{STAFF}/{inactive_staff}", {"status": "inactive"})
    # 未來的班次（不能完成），以及 11/04 的另一筆供重疊測試
    shift = _shift(api, unit, staff, "2026-11-03", "09:00", "17:00", note="早班")
    _shift(api, unit, staff, "2026-11-04", "09:00", "17:00")
    _shift(api, unit, staff, "2026-11-10", "09:00", "17:00")
    cancelled = _shift(api, unit, staff, "2026-11-06", "09:00", "17:00")
    api.ok("POST", f"{SHIFTS}/{cancelled}/cancel", {})
    att = _attendance(api, unit, staff, "2026-11-03", "09:00", "17:00", note="早班")
    _attendance(api, unit, staff, "2026-11-04", "09:00", "17:00")
    voided = _attendance(api, unit, staff, "2026-11-06", "09:00", "17:00")
    api.ok("POST", f"{ATTENDANCE}/{voided}/void", {"reason": "重複"})
    eq = _equipment(api, unit)
    broken = _equipment(api, unit, "EQ-2")
    api.ok("PATCH", f"{EQUIPMENT}/{broken}", {"state": "maintenance"})
    res = _reserve(api, eq, staff, "2026-11-04", "09:00", "10:00")
    returned = _reserve(api, eq, staff, "2026-11-04", "11:00", "12:00")
    api.ok("POST", f"{RESERVATIONS}/{returned}/return", {})
    ids = {
        "unit": unit,
        "staff": staff,
        "other_staff": other_staff,
        "inactive_staff": inactive_staff,
        "inactive_unit": inactive_unit,
        "shift": shift,
        "cancelled": cancelled,
        "att": att,
        "voided": voided,
        "eq": eq,
        "broken": broken,
        "res": res,
        "returned": returned,
    }
    method, path, body, status, code = _rejections(ids)[index]
    assert _rejected(api, method, path, copy.deepcopy(body)) == (status, code)
