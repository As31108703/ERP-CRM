"""CRM（B§3.0、B§3.3、B§3.4）：示範資料、商機跟進與報價。

通用紀錄的建立／更新在 `modules/crm/records.generic_create／generic_update`（B§3.2），
本模組與 projects（Task 10）共用。其他模組以 `find_record(ctx, "cases", id)` 取得案件。
"""

import uuid
from typing import Any

from sqlmodel import Session, select

from src.core import clock
from src.core.canonical import digest
from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.catalog.templates import Template
from src.modules.crm.entity import CrmRecordRow, DealFollowupRow, QuoteRow
from src.modules.crm.records import find_record
from src.platform.context import CommandContext
from src.platform.records import (
    crm_record_missing,
    js_length,
    parse_loose_instant,
    scoped_get,
)

DRAFT = "draft"
ISSUED = "issued"
SUPERSEDED = "superseded"
CONFIRMED = "simulated_confirmed"
QUOTE_STATUSES = (DRAFT, ISSUED, SUPERSEDED, CONFIRMED)
NOTE_MAX = 2000
DEMO_DEAL_NOTES = "這是可清除的產業示範商機"


# --- 查詢 -----------------------------------------------------------------------


def list_records(db: Session, workspace_id: str, collection: str) -> list[CrmRecordRow]:
    stmt = (
        select(CrmRecordRow)
        .where(
            CrmRecordRow.workspace_id == uuid.UUID(workspace_id),
            CrmRecordRow.collection == collection,
        )
        .order_by(CrmRecordRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def all_records(db: Session, workspace_id: str) -> list[CrmRecordRow]:
    stmt = (
        select(CrmRecordRow)
        .where(CrmRecordRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(CrmRecordRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def followups_of(
    db: Session, workspace_id: str, deal_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DealFollowupRow]]:
    """工作區內各商機的跟進，依新增順序。"""
    out: dict[uuid.UUID, list[DealFollowupRow]] = {did: [] for did in deal_ids}
    if deal_ids:
        stmt = (
            select(DealFollowupRow)
            .where(
                DealFollowupRow.workspace_id == uuid.UUID(workspace_id),
                DealFollowupRow.deal_id.in_(deal_ids),  # type: ignore[attr-defined]
            )
            .order_by(DealFollowupRow.seq)  # type: ignore[arg-type]
        )
        for f in db.exec(stmt):
            out[f.deal_id].append(f)
    return out


def list_quotes(db: Session, workspace_id: str) -> list[QuoteRow]:
    stmt = (
        select(QuoteRow)
        .where(QuoteRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(QuoteRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def quote_digest(q: QuoteRow) -> str:
    """報價摘要：`{id, case_id, amount_minor, expires_at}`，expires_at 為 API 輸出的 ISO 字串。"""
    return digest(
        {
            "id": str(q.id),
            "case_id": str(q.case_id),
            "amount_minor": q.amount_minor,
            "expires_at": clock.iso(q.expires_at),
        }
    )


def _get_quote(ctx: CommandContext, quote_id: object) -> QuoteRow:
    row = scoped_get(ctx.db, QuoteRow, ctx.workspace_id, quote_id)
    if row is None:
        raise crm_record_missing()
    return row


# --- 跟進 -----------------------------------------------------------------------


def create_followup(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`followup.create {deal_id, note}`：note 為最多 2000 字的字串（可為空字串），回傳商機 id。"""
    deal = find_record(ctx, "deals", p.get("deal_id"))
    note = p.get("note")
    if not isinstance(note, str) or js_length(note) > NOTE_MAX:
        raise Problem(422, "note_invalid", "請填追蹤內容")
    ctx.db.add(
        DealFollowupRow(
            workspace_id=deal.workspace_id, deal_id=deal.id, note=note, created_at=ctx.now
        )
    )
    ctx.db.flush()
    return str(deal.id)


# --- 報價 -----------------------------------------------------------------------


def create_quote(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`quote.create {case_id, amount_minor ≥1, expires_at}`：建立草稿報價。"""
    case = find_record(ctx, "cases", p.get("case_id"))
    amount = check_int(p.get("amount_minor"), min_=1)
    expires_at = parse_loose_instant(p.get("expires_at"))
    if expires_at is None:
        raise Problem(422, "expiry_invalid", "請填有效期限")
    row = QuoteRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        case_id=case.id,
        amount_minor=amount,
        expires_at=expires_at,
        status=DRAFT,
        legal_confirmation=False,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return str(row.id)


def issue_quote(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`quote.issue {id}`：只有草稿能發出；寫入摘要，同案件其他 issued 報價改為 superseded。"""
    q = _get_quote(ctx, p.get("id"))
    ensure(q.status == DRAFT, 409, "quote_immutable", "已發出報價不可修改")
    q.status = ISSUED
    q.issued_at = ctx.now
    q.digest = quote_digest(q)
    q.updated_at = ctx.now
    for other in list_quotes(ctx.db, ctx.workspace_id):
        if other.id != q.id and other.case_id == q.case_id and other.status == ISSUED:
            other.status = SUPERSEDED
            other.updated_at = ctx.now
    ctx.db.flush()
    return str(q.id)


def confirm_quote(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`quote.confirm {id, digest}`：須為 issued、摘要相符且尚未到期，否則 409 quote_outdated。"""
    q = _get_quote(ctx, p.get("id"))
    ensure(
        q.status == ISSUED and p.get("digest") == q.digest and q.expires_at > ctx.now,
        409,
        "quote_outdated",
        "報價已過期或不是最新版本",
    )
    q.status = CONFIRMED
    q.updated_at = ctx.now
    ctx.db.flush()
    return str(q.id)


# --- seed -----------------------------------------------------------------------


def _seed_record(ctx: CommandContext, collection: str, **fields: Any) -> CrmRecordRow:
    row = CrmRecordRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        collection=collection,
        created_at=ctx.now,
        updated_at=ctx.now,
        **fields,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return row


def seed_crm(ctx: CommandContext, template: Template) -> None:
    """B§3.0：示範客戶一律建立；啟用 crm 時再建立案件（open）與商機（new）。"""
    workspace = ctx.require_workspace()
    sample = template.sample
    customer = _seed_record(ctx, "customers", name=sample.customer)
    if "crm" not in workspace.modules:
        return
    _seed_record(ctx, "cases", title=sample.service, customer_id=customer.id, status="open")
    _seed_record(
        ctx,
        "deals",
        name=sample.service,
        customer_id=customer.id,
        status="new",
        notes=DEMO_DEAL_NOTES,
    )
