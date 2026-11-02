"""銷售訂單、預留與庫存價值守恆的一致性檢查（B§2 validateIntegrity 的 Orders、
Reservations、Stock value 三項）。"""

import uuid

from sqlalchemy import func
from sqlmodel import Session, select

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.inventory import service as inventory
from src.modules.inventory.service import list_products, list_purchases
from src.modules.sales.entity import SalesOrderRow, ShippedCostLotRow
from src.modules.sales.service import CANCELLED, STATUSES, cost_lots_of, lines_of, list_orders
from src.modules.wallets.service import credits_by_reference, list_wallets
from src.platform.records import LEARNING_ID_RE, LINES_MAX, check_record_limit


def _order_invalid(message: str) -> Problem:
    return Problem(422, "order_invalid", message)


def _check(cond: bool, message: str) -> None:
    if not cond:
        raise _order_invalid(message)


def _missing() -> Problem:
    return Problem(404, "record_missing", "找不到工作區紀錄")


def check_orders(db: Session, workspace_id: str) -> None:
    """參照存在（404 record_missing）、教學識別格式（learning_id_invalid），其餘 422 order_invalid：
    1..50 個品項且商品不重複、paid ≤ total、refunded ≤ paid、returned ≤ shipped ≤ quantity、
    出貨成本批次合計等於 shipped／returned、total = Σ 售價 × 數量、狀態合法、取消訂單沒有出貨
    且已全額退款、有出貨就必須已付清、paid／refunded 與流水一致、狀態與付款一致。"""
    check_record_limit(db, SalesOrderRow, workspace_id)
    orders = list_orders(db, workspace_id)
    wallet_ids = {w.id for w in list_wallets(db, workspace_id)}
    product_ids = {p.id for p in list_products(db, workspace_id)}
    lines = lines_of(db, workspace_id, [o.id for o in orders])
    lots = cost_lots_of(db, workspace_id, [line.id for rows in lines.values() for line in rows])
    paid = credits_by_reference(db, workspace_id, "order.pay")
    cancelled = credits_by_reference(db, workspace_id, "order.cancel")
    returned = credits_by_reference(db, workspace_id, "order.return")
    for o in orders:
        if o.buyer_wallet_id not in wallet_ids:
            raise _missing()
        for line in lines[o.id]:
            if line.product_id not in product_ids:
                raise _missing()
        ensure(
            o.learning_run_id is None or LEARNING_ID_RE.fullmatch(o.learning_run_id) is not None,
            422,
            "learning_id_invalid",
            "教學識別不符",
        )
    for o in orders:
        rows = lines[o.id]
        _check(0 < len(rows) <= LINES_MAX, "訂單品項不符")
        for n in (o.total_minor, o.paid_minor, o.refunded_minor):
            check_int(n)
        _check(o.paid_minor <= o.total_minor and o.refunded_minor <= o.paid_minor, "訂單金額不符")
        _check(len({line.product_id for line in rows}) == len(rows), "商品重複")
        total = 0
        for line in rows:
            check_int(line.quantity, min_=1)
            for n in (line.shipped_quantity, line.returned_quantity, line.price_minor):
                check_int(n)
            check_int(line.cost_minor)
            _check(line.returned_quantity <= line.shipped_quantity <= line.quantity, "出貨退貨不符")
            total += line.quantity * line.price_minor
            for lot in lots[line.id]:
                check_int(lot.quantity, min_=1)
                check_int(lot.cost_minor)
                check_int(lot.returned)
                _check(lot.returned <= lot.quantity, "退貨成本層不符")
            _check(
                sum(lot.quantity for lot in lots[line.id]) == line.shipped_quantity
                and sum(lot.returned for lot in lots[line.id]) == line.returned_quantity,
                "出貨成本層不符",
            )
        _check(total == o.total_minor, "訂單總額不符")
        _check(o.status in STATUSES, "訂單狀態不符")
        shipped = any(line.shipped_quantity > 0 for line in rows)
        if o.status == CANCELLED:
            _check(o.paid_minor == o.refunded_minor and not shipped, "取消訂單不符")
        if shipped:
            _check(o.paid_minor == o.total_minor, "出貨付款不符")
    for o in orders:
        _check(
            o.paid_minor == paid.get(o.id, 0)
            and o.refunded_minor == returned.get(o.id, 0) + cancelled.get(o.id, 0),
            "訂單付款與流水不符",
        )
        if o.status == "pending":
            _check(o.paid_minor == 0, "待付款狀態不符")
        if o.status == "partially_paid":
            _check(0 < o.paid_minor < o.total_minor, "部分付款狀態不符")
        if o.status == "paid":
            _check(o.paid_minor == o.total_minor, "付款狀態不符")


def check_reservations(db: Session, workspace_id: str) -> None:
    """每個商品的 reserved 等於所有已登錄預留需求的加總（未取消訂單的未出貨量，
    Task 9 起再加上工單預留），否則 422 reservation_invalid。"""
    demand = inventory.reserved_demand(db, workspace_id)
    for p in list_products(db, workspace_id):
        ensure(
            p.reserved == demand.get(str(p.id), 0),
            422,
            "reservation_invalid",
            "預留數量不符",
        )


def _unreturned_shipped_cost(db: Session, workspace_id: str) -> int:
    stmt = (
        select(
            func.coalesce(
                func.sum(
                    (ShippedCostLotRow.quantity - ShippedCostLotRow.returned)
                    * ShippedCostLotRow.cost_minor
                ),
                0,
            )
        )
        # 出貨成本批次以複合外鍵屬於同一工作區的品項，直接以 workspace_id 篩選
        .where(ShippedCostLotRow.workspace_id == uuid.UUID(workspace_id))
    )
    return int(db.execute(stmt).scalar_one())


def check_stock_value(db: Session, workspace_id: str) -> None:
    """Σ 採購總額 = Σ 商品庫存價值 + Σ 未退回的出貨成本，否則 422 stock_value_conservation。"""
    purchased = sum(x.total_minor for x in list_purchases(db, workspace_id))
    held = sum(p.stock_value_minor for p in list_products(db, workspace_id))
    ensure(
        purchased == held + _unreturned_shipped_cost(db, workspace_id),
        422,
        "stock_value_conservation",
        "庫存及出貨成本不守恆",
    )
