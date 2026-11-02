"""行政申請：建立、編輯與狀態轉移（A§1、A§2 Request state machine）。

狀態流程：
- draft → submitted、withdrawn
- submitted → returned、withdrawn、prepared_unreviewed
- returned → draft（經由編輯）、submitted、withdrawn
- withdrawn、prepared_unreviewed 為終止狀態

每次轉移都在 adm_request_transition 追加一筆 `{status, at, note}`；只有退回帶原因，並同步寫進
processing_note（重新送出後仍保留最近一次退回的原因）。prepared_unreviewed 只是整理完成、
尚未覆核，不代表核准，也不動任何金額。

依種類的規則（請假須有員工與起訖且金額為 0、請購與費用金額至少 1）、狀態紀錄的流程與
50 筆上限，都由命令之後的 invariants 檢查，與匯入共用同一套規則。
"""

import uuid
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from src.core import clock
from src.core.ids import new_id
from src.core.problem import ensure
from src.modules.administration import validators as v
from src.modules.administration.entity import AdmRequest, AdmRequestTransition
from src.modules.administration.lookup import active_staff, active_unit, row_by_id
from src.modules.administration.schema import parse
from src.modules.administration.snapshot import REQUEST_TYPES
from src.platform.context import CommandContext

# 可編輯、可送出、可撤回的來源狀態
EDITABLE = ("draft", "returned")
WITHDRAWABLE = ("draft", "submitted", "returned")


def _dates(request_type: str, start: Any, end: Any) -> tuple[Any, Any]:
    """起訖須同時為 null 或同時填寫；請假最長 31 天，其他種類最長 48 小時，對齊整分鐘。"""
    ensure(
        (start is None) == (end is None),
        422,
        "office_interval_invalid",
        "申請起訖時間須同時填寫",
    )
    if start is None:
        return None, None
    limit = v.LONG_MAX_MINUTES if request_type == "leave" else v.DEFAULT_MAX_MINUTES
    return v.interval(start, end, max_minutes=limit)


def _opt_iso(value: Any) -> str | None:
    return None if value is None else clock.iso(value)


def _append(ctx: CommandContext, row: AdmRequest, status: str, note: str = "") -> None:
    """改變狀態並追加一筆狀態紀錄；退回時同步更新 processing_note。"""
    last = ctx.db.exec(
        select(func.max(AdmRequestTransition.seq)).where(AdmRequestTransition.request_id == row.id)
    ).one()
    ctx.db.add(
        AdmRequestTransition(
            request_id=row.id, seq=(last or 0) + 1, status=status, at=ctx.now, note=note
        )
    )
    row.status = status
    if status == "returned":
        row.processing_note = note


def create_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.request.create", payload)
    unit = active_unit(ctx, p["unit_id"])
    staff_id = p.get("staff_id")
    staff = active_staff(ctx, staff_id, unit.id) if staff_id is not None else None
    request_type = v.enum_value(p["type"], REQUEST_TYPES)
    start, end = _dates(request_type, p.get("start_at"), p.get("end_at"))
    row = AdmRequest(
        id=uuid.UUID(new_id()),
        workspace_id=uuid.UUID(ctx.workspace_id),
        type=request_type,
        staff_id=staff.id if staff is not None else None,
        unit_id=unit.id,
        title=v.text(p["title"]),
        description=v.text(p.get("description", ""), 2000, allow_empty=True),
        amount_minor=v.integer(p.get("amount_minor", 0)),
        currency="SIM",
        start_at=start,
        end_at=end,
        status="draft",
        processing_note="",
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    # 先寫入申請，狀態紀錄的外鍵才有對象
    ctx.db.flush()
    ctx.db.add(AdmRequestTransition(request_id=row.id, seq=1, status="draft", at=ctx.now, note=""))
    return str(row.id)


def _locked(ctx: CommandContext, row_id: Any, allowed: tuple[str, ...], message: str) -> AdmRequest:
    row = row_by_id(ctx, AdmRequest, row_id, lock=True)
    ensure(row.status in allowed, 409, "office_transition_invalid", message)
    return row


def _touch(ctx: CommandContext, row: AdmRequest) -> str:
    row.updated_at = ctx.now
    ctx.db.add(row)
    return str(row.id)


def update_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """草稿或退回的申請可編輯；退回的申請編輯後回到草稿。種類、單位與員工不可變更。"""
    p = parse("office.request.update", payload)
    v.editable(p)
    row = _locked(ctx, p["id"], EDITABLE, "只有草稿或退回的申請可編輯")
    if "title" in p:
        row.title = v.text(p["title"])
    if "description" in p:
        row.description = v.text(p["description"], 2000, allow_empty=True)
    if "amount_minor" in p:
        row.amount_minor = v.integer(p["amount_minor"])
    if "start_at" in p or "end_at" in p:
        row.start_at, row.end_at = _dates(
            row.type,
            p["start_at"] if "start_at" in p else _opt_iso(row.start_at),
            p["end_at"] if "end_at" in p else _opt_iso(row.end_at),
        )
    if row.status == "returned":
        _append(ctx, row, "draft")
    return _touch(ctx, row)


def submit_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """送出時單位與員工（若有）須仍為啟用中。"""
    p = parse("office.request.submit", payload)
    row = _locked(ctx, p["id"], EDITABLE, "只有草稿或退回的申請可送出")
    active_unit(ctx, str(row.unit_id))
    if row.staff_id is not None:
        active_staff(ctx, str(row.staff_id), row.unit_id)
    _append(ctx, row, "submitted")
    return _touch(ctx, row)


def return_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """退回須附處理原因，原因同時寫進狀態紀錄與 processing_note。"""
    p = parse("office.request.return", payload)
    row = _locked(ctx, p["id"], ("submitted",), "只有已送出的申請可退回")
    _append(ctx, row, "returned", v.text(p["processing_note"], 1000))
    return _touch(ctx, row)


def withdraw_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    p = parse("office.request.withdraw", payload)
    row = _locked(ctx, p["id"], WITHDRAWABLE, "這份申請目前不可撤回")
    _append(ctx, row, "withdrawn")
    return _touch(ctx, row)


def prepare_request(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """整理完成、待覆核；不是核准，也不動任何金額。"""
    p = parse("office.request.prepare", payload)
    row = _locked(ctx, p["id"], ("submitted",), "只有已送出的申請可整理成待覆核資料")
    _append(ctx, row, "prepared_unreviewed")
    return _touch(ctx, row)
