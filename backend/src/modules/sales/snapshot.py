"""sales 模組的快照與還原：集合 `orders`（含 `lines[].shipped_cost_lots[]`）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.sales.entity import OrderLineRow, SalesOrderRow, ShippedCostLotRow
from src.modules.sales.service import cost_lots_of, lines_of, list_orders


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    rows = list_orders(db, workspace_id)
    lines = lines_of(db, [o.id for o in rows])
    lots = cost_lots_of(db, [line.id for group in lines.values() for line in group])
    orders = [
        {
            "id": str(o.id),
            "learning_run_id": o.learning_run_id,
            "buyer_wallet_id": str(o.buyer_wallet_id),
            "status": o.status,
            "total_minor": o.total_minor,
            "paid_minor": o.paid_minor,
            "refunded_minor": o.refunded_minor,
            "lines": [
                {
                    "id": str(line.id),
                    "product_id": str(line.product_id),
                    "name": line.name,
                    "price_minor": line.price_minor,
                    "cost_minor": line.cost_minor,
                    "quantity": line.quantity,
                    "shipped_quantity": line.shipped_quantity,
                    "returned_quantity": line.returned_quantity,
                    "shipped_cost_lots": [
                        {
                            "quantity": lot.quantity,
                            "cost_minor": lot.cost_minor,
                            "returned": lot.returned,
                        }
                        for lot in lots[line.id]
                    ],
                }
                for line in lines[o.id]
            ],
            "created_at": clock.iso(o.created_at),
            "updated_at": clock.iso(o.updated_at),
        }
        for o in rows
    ]
    return {"orders": orders}


def _time(value: Any, default: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else default


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """依陣列順序插入（保留 seq、品項與出貨成本批次順序）；須在 wallets 與 inventory 之後執行，
    資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for o in data.get("orders", []):
        created = _time(o.get("created_at"), now)
        order_id = uuid.UUID(o["id"])
        db.add(
            SalesOrderRow(
                id=order_id,
                workspace_id=ws,
                learning_run_id=o.get("learning_run_id"),
                buyer_wallet_id=uuid.UUID(o["buyer_wallet_id"]),
                status=o["status"],
                total_minor=o["total_minor"],
                paid_minor=o["paid_minor"],
                refunded_minor=o["refunded_minor"],
                created_at=created,
                updated_at=_time(o.get("updated_at"), created),
            )
        )
        db.flush()
        for idx, line in enumerate(o["lines"]):
            line_id = uuid.UUID(line["id"])
            db.add(
                OrderLineRow(
                    id=line_id,
                    order_id=order_id,
                    idx=idx,
                    product_id=uuid.UUID(line["product_id"]),
                    name=line["name"],
                    price_minor=line["price_minor"],
                    cost_minor=line["cost_minor"],
                    quantity=line["quantity"],
                    shipped_quantity=line["shipped_quantity"],
                    returned_quantity=line["returned_quantity"],
                )
            )
            db.flush()
            for lot in line.get("shipped_cost_lots", []):
                db.add(
                    ShippedCostLotRow(
                        line_id=line_id,
                        quantity=lot["quantity"],
                        cost_minor=lot["cost_minor"],
                        returned=lot["returned"],
                    )
                )
                db.flush()
