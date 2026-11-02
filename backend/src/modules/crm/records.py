"""CRM 通用紀錄（customers、contacts、deals、cases、tasks、milestones）的建立、更新與查找
（B§3.2）。crm 與 projects 的命令共用；services 等模組以 `find_record(ctx, "cases", id)` 取得案件。

欄位、長度與集合等常數放在 `platform/records`，供快照與一致性檢查共用。
"""

import json
import uuid
from typing import Any

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.crm.entity import CrmRecordRow
from src.platform.context import CommandContext
from src.platform.records import (
    LOST,
    RECORD_COLLECTIONS,
    RECORD_FIELDS,
    RECORD_REF_FIELDS,
    RECORD_TEXT_FIELDS,
    TEXT_LIMIT,
    crm_record_missing,
    js_length,
    parse_id,
    parse_loose_instant,
    scoped_get,
)


def _fields_invalid() -> Problem:
    return Problem(422, "fields_invalid", "欄位不符")


def find_record(ctx: CommandContext, collection: str, record_id: object) -> CrmRecordRow:
    """工作區內指定集合的紀錄；不存在（或屬於其他集合）時 404 record_missing。"""
    row = scoped_get(ctx.db, CrmRecordRow, ctx.workspace_id, record_id)
    if row is None or row.collection != collection:
        raise crm_record_missing()
    return row


def _check_record_payload(p: dict[str, Any]) -> None:
    ensure(all(k in RECORD_FIELDS for k in p), 422, "fields_invalid", "欄位不符")
    text = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    ensure(js_length(text) <= TEXT_LIMIT, 422, "text_limit", "文字過長")
    if p.get("status") == LOST:
        reason = p.get("lost_reason")
        ensure(
            isinstance(reason, str) and reason.strip() != "",
            422,
            "lost_reason_required",
            "請填失單原因",
        )


def _apply(row: CrmRecordRow, p: dict[str, Any]) -> None:
    """把 payload 合併進紀錄；id 不採用。參照是否存在由一致性檢查負責（404 record_missing）。"""
    for key in RECORD_TEXT_FIELDS:
        if key in p:
            value = p[key]
            if value is not None and not isinstance(value, str):
                raise _fields_invalid()
            setattr(row, key, value)
    for key in RECORD_REF_FIELDS:
        if key in p:
            value = p[key]
            if value is None or value == "":
                setattr(row, key, None)
                continue
            if not isinstance(value, str):
                raise _fields_invalid()
            parsed = parse_id(value)
            if parsed is None:
                # 不是 UUID 的參照不可能指向任何紀錄
                raise crm_record_missing()
            setattr(row, key, parsed)
    if "due_at" in p:
        due = p["due_at"]
        if due is None:
            row.due_at = None
        else:
            parsed_due = parse_loose_instant(due)
            if parsed_due is None:
                raise _fields_invalid()
            row.due_at = parsed_due
    if "amount_minor" in p:
        # precheck 已檢查並正規化（5.0 → 5）；這裡再檢查一次，直接呼叫時也不會存入非整數
        row.amount_minor = check_int(p["amount_minor"], min_=1)


def _check_collection(collection: str) -> None:
    if collection not in RECORD_COLLECTIONS:
        raise ValueError(f"未知的通用紀錄集合：{collection}")


def generic_create(ctx: CommandContext, collection: str, payload: dict[str, Any]) -> str:
    """`<x>.create`：檢查欄位、長度與失單原因後新增紀錄；payload 的 id 不採用，回傳新 id。"""
    _check_collection(collection)
    _check_record_payload(payload)
    row = CrmRecordRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        collection=collection,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    _apply(row, payload)
    ctx.db.add(row)
    ctx.db.flush()
    return str(row.id)


def generic_update(ctx: CommandContext, collection: str, payload: dict[str, Any]) -> str:
    """`<x>.update {id, ...}`：找不到 404 record_missing；合併欄位並更新 updated_at。"""
    _check_collection(collection)
    _check_record_payload(payload)
    row = find_record(ctx, collection, payload.get("id"))
    _apply(row, payload)
    row.updated_at = ctx.now
    ctx.db.flush()
    return str(row.id)
