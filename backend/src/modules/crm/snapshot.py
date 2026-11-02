"""crm 模組的快照與還原：集合 `customers, contacts, deals（含 followups）, cases, tasks,
milestones`（通用紀錄同一張表）與 `quotes`。tasks、milestones 的路由由 projects（Task 10）提供。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.crm.entity import CrmRecordRow, DealFollowupRow, QuoteRow
from src.modules.crm.service import all_records, followups_of, list_quotes
from src.platform.records import RECORD_COLLECTIONS


def _iso(value: datetime | None) -> str | None:
    return clock.iso(value) if value is not None else None


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def record_out(r: CrmRecordRow) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "title": r.title,
        "customer_id": _id(r.customer_id),
        "case_id": _id(r.case_id),
        "status": r.status,
        "notes": r.notes,
        "lost_reason": r.lost_reason,
        "due_at": _iso(r.due_at),
        "email": r.email,
        "phone": r.phone,
        "amount_minor": r.amount_minor,
        "created_at": clock.iso(r.created_at),
        "updated_at": clock.iso(r.updated_at),
    }


def quote_out(q: QuoteRow) -> dict[str, Any]:
    return {
        "id": str(q.id),
        "case_id": str(q.case_id),
        "amount_minor": q.amount_minor,
        "expires_at": clock.iso(q.expires_at),
        "status": q.status,
        "digest": q.digest,
        "issued_at": _iso(q.issued_at),
        "created_at": clock.iso(q.created_at),
        "updated_at": clock.iso(q.updated_at),
        "legal_confirmation": False,
    }


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {c: [] for c in RECORD_COLLECTIONS}
    rows = all_records(db, workspace_id)
    followups = followups_of(db, [r.id for r in rows if r.collection == "deals"])
    for r in rows:
        item = record_out(r)
        if r.collection == "deals":
            item["followups"] = [
                {"id": str(f.id), "note": f.note, "created_at": clock.iso(f.created_at)}
                for f in followups[r.id]
            ]
        out[r.collection].append(item)
    out["quotes"] = [quote_out(q) for q in list_quotes(db, workspace_id)]
    return out


def _time(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(value) if isinstance(value, str) and value else None


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """各集合依陣列順序插入（保留 seq 與跟進順序）；資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for collection in RECORD_COLLECTIONS:
        for r in data.get(collection, []):
            created = _time(r.get("created_at")) or now
            record_id = uuid.UUID(r["id"])
            db.add(
                CrmRecordRow(
                    id=record_id,
                    workspace_id=ws,
                    collection=collection,
                    name=r.get("name"),
                    title=r.get("title"),
                    customer_id=_uuid(r.get("customer_id")),
                    case_id=_uuid(r.get("case_id")),
                    status=r.get("status"),
                    notes=r.get("notes"),
                    lost_reason=r.get("lost_reason"),
                    due_at=_time(r.get("due_at")),
                    email=r.get("email"),
                    phone=r.get("phone"),
                    amount_minor=r.get("amount_minor"),
                    created_at=created,
                    updated_at=_time(r.get("updated_at")) or created,
                )
            )
            db.flush()
            for f in r.get("followups", []) if collection == "deals" else []:
                db.add(
                    DealFollowupRow(
                        id=uuid.UUID(f["id"]),
                        deal_id=record_id,
                        note=f["note"],
                        created_at=_time(f.get("created_at")) or created,
                    )
                )
                db.flush()
    for q in data.get("quotes", []):
        created = _time(q.get("created_at")) or now
        db.add(
            QuoteRow(
                id=uuid.UUID(q["id"]),
                workspace_id=ws,
                case_id=uuid.UUID(q["case_id"]),
                amount_minor=q["amount_minor"],
                expires_at=datetime.fromisoformat(q["expires_at"]),
                status=q["status"],
                legal_confirmation=False,
                digest=q.get("digest"),
                issued_at=_time(q.get("issued_at")),
                created_at=created,
                updated_at=_time(q.get("updated_at")) or created,
            )
        )
        db.flush()
