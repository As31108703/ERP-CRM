"""inventory 模組的快照與還原：集合 `products`（含 `lots`）與 `purchases`。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.inventory.entity import ProductLotRow, ProductRow, PurchaseRow
from src.modules.inventory.service import list_products, list_purchases, lots_of


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    rows = list_products(db, workspace_id)
    lots = lots_of(db, workspace_id, [p.id for p in rows])
    products = [
        {
            "id": str(p.id),
            "sku": p.sku,
            "name": p.name,
            "price_minor": p.price_minor,
            "cost_minor": p.cost_minor,
            "active": p.active,
            "on_hand": p.on_hand,
            "reserved": p.reserved,
            "stock_value_minor": p.stock_value_minor,
            "lots": [
                {"quantity": lot.quantity, "cost_minor": lot.cost_minor} for lot in lots[p.id]
            ],
            "created_at": clock.iso(p.created_at),
            "updated_at": clock.iso(p.updated_at),
        }
        for p in rows
    ]
    purchases = [
        {
            "id": str(x.id),
            "product_id": str(x.product_id),
            "name": x.name,
            "quantity": x.quantity,
            "cost_minor": x.cost_minor,
            "total_minor": x.total_minor,
            "created_at": clock.iso(x.created_at),
            "updated_at": clock.iso(x.updated_at),
        }
        for x in list_purchases(db, workspace_id)
    ]
    return {"products": products, "purchases": purchases}


def _time(value: Any, default: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else default


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """依陣列順序插入（保留 seq 與 FIFO 順序）；資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for p in data.get("products", []):
        created = _time(p.get("created_at"), now)
        product_id = uuid.UUID(p["id"])
        db.add(
            ProductRow(
                id=product_id,
                workspace_id=ws,
                sku=p["sku"],
                name=p["name"],
                price_minor=p["price_minor"],
                cost_minor=p["cost_minor"],
                active=p["active"],
                on_hand=p["on_hand"],
                reserved=p["reserved"],
                stock_value_minor=p["stock_value_minor"],
                created_at=created,
                updated_at=_time(p.get("updated_at"), created),
            )
        )
        db.flush()
        for lot in p.get("lots", []):
            db.add(
                ProductLotRow(
                    workspace_id=ws,
                    product_id=product_id,
                    quantity=lot["quantity"],
                    cost_minor=lot["cost_minor"],
                )
            )
            db.flush()
    for x in data.get("purchases", []):
        created = _time(x.get("created_at"), now)
        db.add(
            PurchaseRow(
                id=uuid.UUID(x["id"]),
                workspace_id=ws,
                product_id=uuid.UUID(x["product_id"]),
                name=x["name"],
                quantity=x["quantity"],
                cost_minor=x["cost_minor"],
                total_minor=x["total_minor"],
                created_at=created,
                updated_at=_time(x.get("updated_at"), created),
            )
        )
        db.flush()
