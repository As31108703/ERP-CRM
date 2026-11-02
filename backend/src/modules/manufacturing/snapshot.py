"""manufacturing 模組的快照與還原：集合 `boms`（含 `components[]`）與 `work_orders`
（含 `bom_snapshot`、`consumed_material_lots[]`）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.manufacturing.entity import (
    BomComponentRow,
    BomRow,
    ConsumedMaterialLotRow,
    WorkOrderRow,
)
from src.modules.manufacturing.service import (
    bom_json,
    components_of,
    consumed_lots_of,
    list_boms,
    list_work_orders,
)


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    boms = list_boms(db, workspace_id)
    components = components_of(db, [b.id for b in boms])
    orders = list_work_orders(db, workspace_id)
    lots = consumed_lots_of(db, [o.id for o in orders])
    work_orders = [
        {
            "id": str(o.id),
            "learning_run_id": o.learning_run_id,
            "bom_id": str(o.bom_id),
            "bom_snapshot": o.bom_snapshot,
            "quantity": o.quantity,
            "status": o.status,
            "actual_cost_minor": o.actual_cost_minor,
            "consumed_material_lots": [
                {
                    "product_id": str(lot.product_id),
                    "quantity": lot.quantity,
                    "cost_minor": lot.cost_minor,
                }
                for lot in lots[o.id]
            ],
            "created_at": clock.iso(o.created_at),
            "updated_at": clock.iso(o.updated_at),
        }
        for o in orders
    ]
    return {
        "boms": [bom_json(b, components[b.id]) for b in boms],
        "work_orders": work_orders,
    }


def _time(value: Any, default: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else default


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """依陣列順序插入（保留 seq、材料順序與耗料順序）；須在 inventory 之後執行，
    資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for b in data.get("boms", []):
        bom_id = uuid.UUID(b["id"])
        db.add(
            BomRow(
                id=bom_id,
                workspace_id=ws,
                product_id=uuid.UUID(b["product_id"]),
                revision=b["revision"],
                created_at=_time(b.get("created_at"), now),
            )
        )
        db.flush()
        for idx, c in enumerate(b["components"]):
            db.add(
                BomComponentRow(
                    bom_id=bom_id,
                    idx=idx,
                    product_id=uuid.UUID(c["product_id"]),
                    quantity=c["quantity"],
                )
            )
        db.flush()
    for o in data.get("work_orders", []):
        created = _time(o.get("created_at"), now)
        order_id = uuid.UUID(o["id"])
        db.add(
            WorkOrderRow(
                id=order_id,
                workspace_id=ws,
                learning_run_id=o.get("learning_run_id"),
                bom_id=uuid.UUID(o["bom_id"]),
                bom_snapshot=o["bom_snapshot"],
                quantity=o["quantity"],
                status=o["status"],
                actual_cost_minor=o.get("actual_cost_minor"),
                created_at=created,
                updated_at=_time(o.get("updated_at"), created),
            )
        )
        db.flush()
        for lot in o.get("consumed_material_lots", []):
            db.add(
                ConsumedMaterialLotRow(
                    work_order_id=order_id,
                    product_id=uuid.UUID(lot["product_id"]),
                    quantity=lot["quantity"],
                    cost_minor=lot["cost_minor"],
                )
            )
            db.flush()
