"""行政快照與還原：`administration.{units,staff,...,changes}`，只在啟用行政模組時出現。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, SQLModel, select

from src.core import clock
from src.core.problem import ensure
from src.modules.administration import validators as v
from src.modules.administration.entity import (
    CHANGE_COLLECTIONS,
    CHANGE_LIMIT,
    COLLECTIONS,
    RECORD_LIMITS,
    TRANSITION_LIMIT,
    AdmChange,
    AdmRequestTransition,
    by_seq,
)
from src.platform.context import WorkspaceRow

MODULE = "administration"
KEY = "administration"
STAMP_KEYS = ("id", "created_at", "updated_at")
# 各集合資料列的欄位（不含 stamp），輸出順序即此順序
ROW_KEYS: dict[str, tuple[str, ...]] = {
    "units": ("name", "kind", "parent_id", "active"),
    "staff": ("code", "alias", "unit_id", "role_label", "status"),
    "shifts": ("staff_id", "unit_id", "start_at", "end_at", "break_minutes", "note", "status"),
    "attendance": ("staff_id", "unit_id", "start_at", "end_at", "break_minutes", "note", "voided"),
    "requests": (
        "type",
        "staff_id",
        "unit_id",
        "title",
        "description",
        "amount_minor",
        "currency",
        "start_at",
        "end_at",
        "status",
        "processing_note",
        "transitions",
    ),
    "equipment": ("code", "name", "unit_id", "state"),
    "reservations": ("equipment_id", "staff_id", "start_at", "end_at", "purpose", "status"),
    "notices": ("title", "body", "unit_id", "pinned", "due_at", "archived"),
}
# 舊資料可能缺少的旗標，匯入時視為 false
OPTIONAL_FLAGS: dict[str, tuple[str, ...]] = {"attendance": ("voided",), "notices": ("archived",)}

UNIT_KINDS = ("branch", "department")
STAFF_STATUSES = ("active", "inactive")
SHIFT_STATUSES = ("scheduled", "completed", "cancelled")
REQUEST_TYPES = ("leave", "purchase", "expense", "general")
REQUEST_STATUSES = ("draft", "submitted", "returned", "withdrawn", "prepared_unreviewed")
EQUIPMENT_STATES = ("available", "maintenance", "retired")
RESERVATION_STATUSES = ("reserved", "returned", "cancelled")


def _out(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return clock.iso(value)
    return value


def row_out(
    collection: str, row: SQLModel, transitions: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """資料列的輸出形式，也是 change 的 before／after 快照形式。"""
    out: dict[str, Any] = {}
    for key in (*STAMP_KEYS, *ROW_KEYS[collection]):
        if key == "transitions":
            out[key] = transitions if transitions is not None else []
        else:
            out[key] = _out(getattr(row, key))
    return out


def transition_out(t: AdmRequestTransition) -> dict[str, Any]:
    return {"status": t.status, "at": clock.iso(t.at), "note": t.note}


def change_out(c: AdmChange) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "kind": c.kind,
        "record_id": str(c.record_id),
        "at": clock.iso(c.at),
        "reason": c.reason,
        "before": c.before,
        "after": c.after,
    }


def _rows(db: Session, model: type[SQLModel], workspace_id: str) -> list[Any]:
    stmt = (
        select(model).where(model.workspace_id == uuid.UUID(workspace_id)).order_by(by_seq(model))
    )  # type: ignore[attr-defined]
    return list(db.exec(stmt))


def _transitions(db: Session, workspace_id: str) -> dict[uuid.UUID, list[dict[str, Any]]]:
    stmt = (
        select(AdmRequestTransition)
        .where(AdmRequestTransition.workspace_id == uuid.UUID(workspace_id))
        .order_by(AdmRequestTransition.request_id, AdmRequestTransition.seq)  # type: ignore[arg-type]
    )
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for t in db.exec(stmt):
        out.setdefault(t.request_id, []).append(transition_out(t))
    return out


def enabled(db: Session, workspace_id: str) -> bool:
    workspace = db.get(WorkspaceRow, uuid.UUID(workspace_id))
    return workspace is not None and MODULE in workspace.modules


def administration(db: Session, workspace_id: str) -> dict[str, Any]:
    transitions = _transitions(db, workspace_id)
    out: dict[str, Any] = {}
    for name, model in COLLECTIONS.items():
        out[name] = [
            row_out(name, row, transitions.get(row.id, []) if name == "requests" else None)
            for row in _rows(db, model, workspace_id)
        ]
    out["changes"] = [change_out(c) for c in _rows(db, AdmChange, workspace_id)]
    return out


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    """ModuleSpec.snapshot：只有行政模組啟用時才輸出 administration 鍵。"""
    if not enabled(db, workspace_id):
        return {}
    return {KEY: administration(db, workspace_id)}


# --- 還原 -------------------------------------------------------------------------


def _collect_ids(value: Any, ids: set[str]) -> None:
    """收集任意巢狀資料中的 `id` 字串（小寫），供跨集合的識別碰撞檢查。"""
    if isinstance(value, list):
        for child in value:
            _collect_ids(child, ids)
    elif isinstance(value, dict):
        if isinstance(value.get("id"), str):
            ids.add(value["id"].lower())
        for child in value.values():
            _collect_ids(child, ids)


def _uid(value: Any) -> uuid.UUID:
    return uuid.UUID(v.uuid_value(value))


def _opt_uid(value: Any) -> uuid.UUID | None:
    return None if value is None else _uid(value)


def _parse_row(name: str, row: Any) -> dict[str, Any]:
    """驗證單一資料列的欄位與型別，回傳資料表欄位值。跨資料列的規則交給 invariants。"""
    keys = set(STAMP_KEYS) | set(ROW_KEYS[name])
    optional = set(OPTIONAL_FLAGS.get(name, ()))
    v.strict_keys(row, keys - optional, optional)
    created = v.instant(row["created_at"])
    updated = v.instant(row["updated_at"])
    ensure(updated >= created, 422, "office_time_invalid", "更新時間不可早於建立時間")
    out: dict[str, Any] = {
        "id": _uid(row["id"]),
        "created_at": created,
        "updated_at": updated,
    }
    if name == "units":
        out |= {
            "name": v.text(row["name"]),
            "kind": v.enum_value(row["kind"], UNIT_KINDS),
            "parent_id": _opt_uid(row["parent_id"]),
            "active": v.boolean(row["active"], "單位啟用狀態不符"),
        }
    elif name == "staff":
        out |= {
            "code": v.text(row["code"], 32),
            "alias": v.text(row["alias"], 80),
            "unit_id": _uid(row["unit_id"]),
            "role_label": v.text(row["role_label"], 100, allow_empty=True),
            "status": v.enum_value(row["status"], STAFF_STATUSES),
        }
    elif name in ("shifts", "attendance"):
        start, end = v.interval(row["start_at"], row["end_at"])
        out |= {
            "staff_id": _uid(row["staff_id"]),
            "unit_id": _uid(row["unit_id"]),
            "start_at": start,
            "end_at": end,
            "break_minutes": v.break_minutes(row["break_minutes"], start, end),
            "note": v.text(row["note"], 1000, allow_empty=True),
        }
        if name == "shifts":
            out["status"] = v.enum_value(row["status"], SHIFT_STATUSES)
        else:
            out["voided"] = v.boolean(row.get("voided", False), "封存或作廢狀態須為布林值")
    elif name == "requests":
        request_type = v.enum_value(row["type"], REQUEST_TYPES)
        ensure(row["currency"] == "SIM", 422, "simulation_required", "幣別只能是 SIM")
        ensure(
            (row["start_at"] is None) == (row["end_at"] is None),
            422,
            "office_interval_invalid",
            "申請起訖時間須同時填寫",
        )
        start = end = None
        if row["start_at"] is not None:
            limit = v.LONG_MAX_MINUTES if request_type == "leave" else v.DEFAULT_MAX_MINUTES
            start, end = v.interval(row["start_at"], row["end_at"], max_minutes=limit)
        out |= {
            "type": request_type,
            "staff_id": _opt_uid(row["staff_id"]),
            "unit_id": _uid(row["unit_id"]),
            "title": v.text(row["title"]),
            "description": v.text(row["description"], 2000, allow_empty=True),
            "amount_minor": v.integer(row["amount_minor"]),
            "currency": "SIM",
            "start_at": start,
            "end_at": end,
            "status": v.enum_value(row["status"], REQUEST_STATUSES),
            "processing_note": v.text(row["processing_note"], 1000, allow_empty=True),
        }
    elif name == "equipment":
        out |= {
            "code": v.text(row["code"], 32),
            "name": v.text(row["name"]),
            "unit_id": _uid(row["unit_id"]),
            "state": v.enum_value(row["state"], EQUIPMENT_STATES),
        }
    elif name == "reservations":
        start, end = v.interval(row["start_at"], row["end_at"], max_minutes=v.LONG_MAX_MINUTES)
        out |= {
            "equipment_id": _uid(row["equipment_id"]),
            "staff_id": _uid(row["staff_id"]),
            "start_at": start,
            "end_at": end,
            "purpose": v.text(row["purpose"], 1000, allow_empty=True),
            "status": v.enum_value(row["status"], RESERVATION_STATUSES),
        }
    elif name == "notices":
        out |= {
            "title": v.text(row["title"]),
            "body": v.text(row["body"], 2000, allow_empty=True),
            "unit_id": _opt_uid(row["unit_id"]),
            "pinned": v.boolean(row["pinned"], "公告置頂狀態不符"),
            "due_at": v.optional_instant(row["due_at"]),
            "archived": v.boolean(row.get("archived", False), "封存或作廢狀態須為布林值"),
        }
    return out


def _parse_transitions(value: Any) -> list[dict[str, Any]]:
    """狀態紀錄的形狀（1–50 筆、嚴格鍵）；流程規則由 invariants 的申請檢查負責。"""
    ensure(
        isinstance(value, list) and 1 <= len(value) <= TRANSITION_LIMIT,
        422,
        "office_transition_limit",
        "申請狀態紀錄須為 1 到 50 筆",
    )
    out = []
    for entry in value:
        v.strict_keys(entry, {"status", "at", "note"}, set())
        out.append(
            {
                "status": v.enum_value(entry["status"], REQUEST_STATUSES),
                "at": v.instant(entry["at"]),
                "note": v.text(entry["note"], 1000, allow_empty=True),
            }
        )
    return out


def _parse_change(change: Any) -> dict[str, Any]:
    """change 的形狀；before／after 的鏈結規則由 Task 12 的 invariants 負責。"""
    v.strict_keys(change, {"id", "kind", "record_id", "at", "reason", "before", "after"}, set())
    ensure(
        isinstance(change["kind"], str) and change["kind"] in CHANGE_COLLECTIONS,
        422,
        "office_change_invalid",
        "更正紀錄種類不符",
    )
    ensure(
        isinstance(change["before"], dict) and isinstance(change["after"], dict),
        422,
        "office_change_invalid",
        "更正紀錄須包含前後資料",
    )
    collection = CHANGE_COLLECTIONS[change["kind"]]
    return {
        "id": uuid.UUID(v.uuid_value(change["id"])),
        "kind": change["kind"],
        "record_id": uuid.UUID(v.uuid_value(change["record_id"])),
        "at": v.instant(change["at"]),
        "reason": v.text(change["reason"], 1000),
        "before": _normalized(collection, change["before"]),
        "after": _normalized(collection, change["after"]),
    }


def _normalized(collection: str, row: Any) -> dict[str, Any]:
    """驗證 change 的 before／after，轉成與快照資料列相同的形式（UTC 時間、旗標補 false）。"""
    values = _parse_row(collection, row)
    return {key: _out(values[key]) for key in (*STAMP_KEYS, *ROW_KEYS[collection])}


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """ModuleSpec.restore：驗證並寫入 `data["administration"]`，取代工作區現有的行政資料。

    行政資料存在與否須與 workspace.modules 一致（422 office_schema_invalid）；識別碼在整份資料
    中不分大小寫不得重複（422 id_collision）。跨資料列的規則（參照、循環、代碼重複、啟用狀態）
    由命令管線之後執行的 invariants 檢查。
    """
    is_enabled = enabled(db, workspace_id)
    if KEY not in data:
        ensure(not is_enabled, 422, "office_schema_invalid", "啟用行政模組須有行政資料")
        return
    ensure(is_enabled, 422, "office_schema_invalid", "未啟用行政模組不可匯入行政資料")
    adm = data[KEY]
    v.strict_keys(adm, set(COLLECTIONS), {"changes"})

    ids: set[str] = set()
    for key, value in data.items():
        if key != KEY:
            _collect_ids(value, ids)

    def claim(row_id: uuid.UUID) -> None:
        ensure(str(row_id) not in ids, 422, "id_collision", "行政紀錄識別重複")
        ids.add(str(row_id))

    parsed: dict[str, list[dict[str, Any]]] = {}
    transitions: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for name in COLLECTIONS:
        rows = adm[name]
        ensure(
            isinstance(rows, list) and len(rows) <= RECORD_LIMITS[name],
            422,
            "office_record_limit",
            "行政紀錄超出上限",
        )
        parsed[name] = []
        for row in rows:
            values = _parse_row(name, row)
            claim(values["id"])
            if name == "requests":
                transitions[values["id"]] = _parse_transitions(row["transitions"])
            parsed[name].append(values)
    raw_changes = adm.get("changes", [])
    ensure(
        isinstance(raw_changes, list) and len(raw_changes) <= CHANGE_LIMIT,
        422,
        "office_change_limit",
        "更正與封存紀錄最多 200 筆",
    )
    changes = []
    for raw in raw_changes:
        change = _parse_change(raw)
        claim(change["id"])
        changes.append(change)

    _delete_all(db, workspace_id)
    wid = uuid.UUID(workspace_id)
    for name, model in COLLECTIONS.items():
        for values in parsed[name]:
            db.add(model(workspace_id=wid, **values))
            # 逐筆 flush，讓 seq 依原本順序配發
            db.flush()
    for request_id, entries in transitions.items():
        for seq, entry in enumerate(entries, start=1):
            db.add(AdmRequestTransition(workspace_id=wid, request_id=request_id, seq=seq, **entry))
    for change in changes:
        db.add(AdmChange(workspace_id=wid, **change))
        db.flush()
    db.flush()


def _delete_all(db: Session, workspace_id: str) -> None:
    wid = uuid.UUID(workspace_id)
    db.execute(delete(AdmChange).where(AdmChange.workspace_id == wid))  # type: ignore[arg-type]
    for model in reversed(list(COLLECTIONS.values())):
        db.execute(delete(model).where(model.workspace_id == wid))  # type: ignore[attr-defined]
