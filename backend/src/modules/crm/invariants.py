"""CRM 一致性檢查（B§2 validateWorld 的筆數上限與參照、validateIntegrity 的失單原因與報價）。"""

import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.crm.entity import CrmRecordRow, QuoteRow
from src.modules.crm.service import (
    DRAFT,
    ISSUED,
    QUOTE_STATUSES,
    all_records,
    list_quotes,
    quote_digest,
)
from src.platform.records import LOST, RECORD_LIMIT, check_record_limit, crm_record_missing


def check_record_limits(db: Session, workspace_id: str) -> None:
    """每個通用紀錄集合與報價各最多 500 筆，否則 422 record_limit。"""
    stmt = (
        select(func.count())
        .select_from(CrmRecordRow)
        .where(CrmRecordRow.workspace_id == uuid.UUID(workspace_id))
        .group_by(CrmRecordRow.collection)  # type: ignore[arg-type]
    )
    ensure(
        all(n <= RECORD_LIMIT for n in db.execute(stmt).scalars()),
        422,
        "record_limit",
        "紀錄超出上限",
    )
    check_record_limit(db, QuoteRow, workspace_id)


def check_references(db: Session, workspace_id: str) -> None:
    """contacts、deals、cases、tasks、milestones 的 customer_id／case_id，以及報價的 case_id，
    都必須指向同工作區對應集合的紀錄，否則 404 record_missing。客戶本身的參照不檢查（照 B§2）。"""
    rows = all_records(db, workspace_id)
    customers = {r.id for r in rows if r.collection == "customers"}
    cases = {r.id for r in rows if r.collection == "cases"}
    for r in rows:
        if r.collection == "customers":
            continue
        if r.customer_id is not None and r.customer_id not in customers:
            raise crm_record_missing()
        if r.case_id is not None and r.case_id not in cases:
            raise crm_record_missing()
    for q in list_quotes(db, workspace_id):
        if q.case_id not in cases:
            raise crm_record_missing()


def check_deals(db: Session, workspace_id: str) -> None:
    """失單（status = lost）的商機必須有非空白的失單原因，否則 422 lost_reason_required。"""
    stmt = select(CrmRecordRow).where(
        CrmRecordRow.workspace_id == uuid.UUID(workspace_id),
        CrmRecordRow.collection == "deals",
        CrmRecordRow.status == LOST,
    )
    for d in db.exec(stmt):
        ensure(
            d.lost_reason is not None and d.lost_reason.strip() != "",
            422,
            "lost_reason_required",
            "請填失單原因",
        )


def _quote_invalid(message: str) -> Problem:
    return Problem(422, "quote_invalid", message)


def check_quotes(db: Session, workspace_id: str) -> None:
    """同一案件最多一張 issued 報價；金額為範圍內整數（number_invalid）；legal_confirmation 為
    false、狀態合法；非草稿報價的摘要必須與內容相符。後三項不成立時 422 quote_invalid。"""
    quotes = list_quotes(db, workspace_id)
    issued_cases = set()
    for q in quotes:
        if q.status == ISSUED:
            if q.case_id in issued_cases:
                raise _quote_invalid("同案件不能有兩份有效報價")
            issued_cases.add(q.case_id)
    for q in quotes:
        check_int(q.amount_minor)
        if q.legal_confirmation is not False or q.status not in QUOTE_STATUSES:
            raise _quote_invalid("報價不符")
        if q.status != DRAFT and q.digest != quote_digest(q):
            raise _quote_invalid("報價摘要不符")
