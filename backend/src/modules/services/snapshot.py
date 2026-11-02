"""services 模組的快照與還原：集合 `services`（含 `deliveries[]`）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.services.entity import ServiceDeliveryRow, ServiceRow
from src.modules.services.service import deliveries_of, list_services


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    rows = list_services(db, workspace_id)
    deliveries = deliveries_of(db, [s.id for s in rows])
    services = [
        {
            "id": str(s.id),
            "case_id": str(s.case_id),
            "title": s.title,
            "source_snapshot": {
                "case": {"id": str(s.case_id), "title": s.source_case_title},
                "price_source": s.price_source,
            },
            "amount_minor": s.amount_minor,
            "currency": "SIM",
            "status": s.status,
            "paid_minor": s.paid_minor,
            "deliveries": [
                {
                    "id": str(d.id),
                    "revision": d.revision,
                    "artifact_ref": d.artifact_ref,
                    "digest": d.digest,
                }
                for d in deliveries[s.id]
            ],
            "latest_delivery_id": (
                str(s.latest_delivery_id) if s.latest_delivery_id is not None else None
            ),
            "legal_confirmation": False,
            "created_at": clock.iso(s.created_at),
            "updated_at": clock.iso(s.updated_at),
        }
        for s in rows
    ]
    return {"services": services}


def _time(value: Any, default: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else default


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """依陣列順序插入（保留 seq 與交付順序）；須在 crm 與 wallets 之後執行，
    資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for s in data.get("services", []):
        created = _time(s.get("created_at"), now)
        service_id = uuid.UUID(s["id"])
        source = s["source_snapshot"]
        latest = s.get("latest_delivery_id")
        db.add(
            ServiceRow(
                id=service_id,
                workspace_id=ws,
                case_id=uuid.UUID(s["case_id"]),
                title=s["title"],
                source_case_title=source["case"]["title"],
                price_source=source["price_source"],
                amount_minor=s["amount_minor"],
                status=s["status"],
                paid_minor=s["paid_minor"],
                latest_delivery_id=uuid.UUID(latest) if latest else None,
                legal_confirmation=False,
                created_at=created,
                updated_at=_time(s.get("updated_at"), created),
            )
        )
        db.flush()
        for d in s.get("deliveries", []):
            db.add(
                ServiceDeliveryRow(
                    id=uuid.UUID(d["id"]),
                    service_id=service_id,
                    revision=d["revision"],
                    artifact_ref=d["artifact_ref"],
                    digest=d["digest"],
                )
            )
            db.flush()
