"""銷售訂單（B§3.6）：建立即預留、分次付款、分批出貨（FIFO 成本批次）、部分退貨與取消。

庫存一律透過 inventory 的 `reserve`、`release_reserved`、`consume_fifo`、`push_lot` 異動；
資金透過 wallets 的 `move`，流水 kind 為 `order.pay`（買家 → 商家）與 `order.cancel`、
`order.return`（商家 → 買家），reference_id 指向訂單。未取消訂單的未出貨量以
`order_reserved_demand` 申報給預留一致性檢查。
"""

import uuid
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.inventory import service as inventory
from src.modules.sales.entity import OrderLineRow, SalesOrderRow, ShippedCostLotRow
from src.modules.wallets import service as wallets
from src.modules.wallets.service import LedgerView, register_ledger_rule
from src.platform.context import CommandContext
from src.platform.records import check_safe, parse_id, record_missing

STATUSES = (
    "pending",
    "partially_paid",
    "paid",
    "partially_shipped",
    "shipped",
    "partially_returned",
    "returned",
    "cancelled",
)
CANCELLED = "cancelled"
_OUT_OF_STOCK = "模擬庫存不足。"
_CORRUPT = "simulation_inventory_corrupt"


# --- 查詢 -----------------------------------------------------------------------


def _ws(ctx: CommandContext) -> uuid.UUID:
    return uuid.UUID(ctx.workspace_id)


def list_orders(db: Session, workspace_id: str) -> list[SalesOrderRow]:
    stmt = (
        select(SalesOrderRow)
        .where(SalesOrderRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(SalesOrderRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def lines_of(db: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[OrderLineRow]]:
    """各訂單的品項，依 idx 排序。"""
    out: dict[uuid.UUID, list[OrderLineRow]] = {oid: [] for oid in order_ids}
    if order_ids:
        stmt = (
            select(OrderLineRow)
            .where(OrderLineRow.order_id.in_(order_ids))  # type: ignore[attr-defined]
            .order_by(OrderLineRow.order_id, OrderLineRow.idx)  # type: ignore[arg-type]
        )
        for line in db.exec(stmt):
            out[line.order_id].append(line)
    return out


def cost_lots_of(
    db: Session, line_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ShippedCostLotRow]]:
    """各品項的出貨成本批次，依出貨順序（id 由小到大）。"""
    out: dict[uuid.UUID, list[ShippedCostLotRow]] = {lid: [] for lid in line_ids}
    if line_ids:
        stmt = (
            select(ShippedCostLotRow)
            .where(ShippedCostLotRow.line_id.in_(line_ids))  # type: ignore[attr-defined]
            .order_by(ShippedCostLotRow.id)  # type: ignore[arg-type]
        )
        for lot in db.exec(stmt):
            out[lot.line_id].append(lot)
    return out


def get_order(ctx: CommandContext, order_id: object) -> SalesOrderRow:
    """工作區內的訂單；不存在時 404 simulation_record_missing。"""
    parsed = parse_id(order_id)
    row = ctx.db.get(SalesOrderRow, parsed) if parsed is not None else None
    if row is None or row.workspace_id != _ws(ctx):
        raise record_missing()
    return row


def order_reserved_demand(db: Session, workspace_id: str) -> dict[str, int]:
    """未取消訂單的未出貨量（quantity - shipped_quantity），依商品加總。"""
    stmt = (
        select(
            OrderLineRow.product_id,
            func.sum(OrderLineRow.quantity - OrderLineRow.shipped_quantity),
        )
        .join(SalesOrderRow, SalesOrderRow.id == OrderLineRow.order_id)  # type: ignore[arg-type]
        .where(
            SalesOrderRow.workspace_id == uuid.UUID(workspace_id),
            SalesOrderRow.status != CANCELLED,
        )
        .group_by(OrderLineRow.product_id)
    )
    return {str(product_id): int(total) for product_id, total in db.execute(stmt)}


inventory.register_reserved_demand(order_reserved_demand)


# --- 共用 -----------------------------------------------------------------------


def _lines_payload(p: dict[str, Any]) -> list[dict[str, Any]]:
    """precheck 已驗證 `lines` 存在時的筆數與數量；這裡要求一定要有。"""
    lines = p.get("lines")
    ensure(isinstance(lines, list) and len(lines) > 0, 422, "lines_invalid", "品項不符")
    return lines  # type: ignore[return-value]


def _open_order(ctx: CommandContext, p: dict[str, Any]) -> SalesOrderRow:
    order = get_order(ctx, p.get("id"))
    ensure(order.status != CANCELLED, 409, "simulation_order_cancelled", "訂單已取消。")
    return order


def _selections(lines: list[OrderLineRow], p: dict[str, Any]) -> list[tuple[OrderLineRow, int]]:
    """`lines: [{line_id, quantity}]` 對應到訂單品項；重複 422、找不到 404。"""
    by_id = {line.id: line for line in lines}
    seen: set[uuid.UUID] = set()
    out: list[tuple[OrderLineRow, int]] = []
    for item in _lines_payload(p):
        line_id = parse_id(item.get("line_id"))
        ensure(
            line_id is None or line_id not in seen,
            422,
            "simulation_duplicate_line",
            "同一品項不能重複指定。",
        )
        line = by_id.get(line_id) if line_id is not None else None
        if line is None:
            raise record_missing()
        seen.add(line.id)
        out.append((line, item["quantity"]))
    return out


def _any_shipped(lines: list[OrderLineRow]) -> bool:
    return any(line.shipped_quantity > 0 for line in lines)


def _buyer_and_business(ctx: CommandContext, order: SalesOrderRow) -> tuple[str, str]:
    business = wallets.wallet_of_kind(ctx, "business")
    return str(order.buyer_wallet_id), str(business.id)


# --- 命令 handler ---------------------------------------------------------------


def create_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`order.create {buyer_wallet_id, lines: [{product_id, quantity}], learning_run_id?}`。

    逐筆檢查重複、停用與可用量（on_hand - reserved），並預留數量；品項保存下單當時的
    名稱、售價與成本。
    """
    buyer = wallets.get_wallet(ctx, p.get("buyer_wallet_id"))
    ensure(buyer.kind == "buyer", 422, "simulation_buyer_required", "請選擇模擬買家錢包。")
    order = SalesOrderRow(
        workspace_id=_ws(ctx),
        learning_run_id=p.get("learning_run_id"),
        buyer_wallet_id=buyer.id,
        status="pending",
        total_minor=0,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    seen: set[uuid.UUID] = set()
    rows: list[OrderLineRow] = []
    total = 0
    for idx, item in enumerate(_lines_payload(p)):
        product_id = parse_id(item.get("product_id"))
        ensure(
            product_id is None or product_id not in seen,
            422,
            "simulation_duplicate_line",
            "商品不可重複。",
        )
        product = inventory.get_product(ctx, product_id)
        seen.add(product.id)
        ensure(product.active, 409, "simulation_product_inactive", "商品已停用。")
        quantity = item["quantity"]
        inventory.reserve(
            ctx, product.id, quantity, code="simulation_out_of_stock", message=_OUT_OF_STOCK
        )
        total = check_safe(total + check_safe(product.price_minor * quantity))
        rows.append(
            OrderLineRow(
                order_id=order.id,
                idx=idx,
                product_id=product.id,
                name=product.name,
                price_minor=product.price_minor,
                cost_minor=product.cost_minor,
                quantity=quantity,
            )
        )
    order.total_minor = total
    ctx.db.add(order)
    ctx.db.flush()
    for row in rows:
        ctx.db.add(row)
    ctx.db.flush()
    return str(order.id)


def pay_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`order.pay {id, amount_minor}`：出貨前分次付款，不得超過訂單總額。"""
    order = _open_order(ctx, p)
    lines = lines_of(ctx.db, [order.id])[order.id]
    ensure(not _any_shipped(lines), 409, "simulation_order_shipped", "出貨後不能再付款。")
    amount = check_int(p.get("amount_minor"), min_=1)
    ensure(
        order.paid_minor + amount <= order.total_minor,
        409,
        "simulation_overpayment",
        "不能超過模擬訂單金額。",
    )
    buyer, business = _buyer_and_business(ctx, order)
    wallets.move(ctx, "order.pay", buyer, business, amount, str(order.id))
    order.paid_minor += amount
    order.status = "paid" if order.paid_minor == order.total_minor else "partially_paid"
    order.updated_at = ctx.now
    ctx.db.flush()
    return str(order.id)


def cancel_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`order.cancel {id}`：未出貨才能取消；退回全部已付金額（0 也寫流水）並釋放預留。"""
    order = _open_order(ctx, p)
    lines = lines_of(ctx.db, [order.id])[order.id]
    ensure(not _any_shipped(lines), 409, "simulation_order_shipped", "出貨後請使用退貨。")
    buyer, business = _buyer_and_business(ctx, order)
    wallets.move(ctx, "order.cancel", business, buyer, order.paid_minor, str(order.id))
    order.refunded_minor = order.paid_minor
    for line in lines:
        inventory.release_reserved(ctx, line.product_id, line.quantity)
    order.status = CANCELLED
    order.updated_at = ctx.now
    ctx.db.flush()
    return str(order.id)


def ship_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`order.ship {id, lines: [{line_id, quantity}]}`：付清後分批出貨。

    每件依 FIFO 從商品成本層取出，記成品項的出貨成本批次，並同時扣減 on_hand 與 reserved。
    """
    order = _open_order(ctx, p)
    ensure(
        order.paid_minor == order.total_minor,
        409,
        "simulation_payment_required",
        "全額模擬付款後才能出貨。",
    )
    lines = lines_of(ctx.db, [order.id])[order.id]
    for line, n in _selections(lines, p):
        ensure(
            line.shipped_quantity + n <= line.quantity,
            409,
            "simulation_overship",
            "不能超量出貨。",
        )
        product = inventory.get_product(ctx, line.product_id)
        ensure(
            product.on_hand >= n and product.reserved >= n,
            409,
            "simulation_out_of_stock",
            _OUT_OF_STOCK,
        )
        inventory.release_reserved(ctx, product.id, n)
        taken = inventory.consume_fifo(
            ctx, product.id, n, corrupt_code=_CORRUPT, message="模擬庫存成本層不足。"
        )
        for quantity, cost_minor in taken:
            ctx.db.add(ShippedCostLotRow(line_id=line.id, quantity=quantity, cost_minor=cost_minor))
            ctx.db.flush()
        line.shipped_quantity += n
    order.status = (
        "shipped"
        if all(line.shipped_quantity == line.quantity for line in lines)
        else "partially_shipped"
    )
    order.updated_at = ctx.now
    ctx.db.flush()
    return str(order.id)


def return_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`order.return {id, lines: [{line_id, quantity}]}`：部分退貨，退款為售價 × 件數。

    依出貨順序走訪出貨成本批次，退回的件數以新的成本層接在商品 FIFO 佇列尾端。
    """
    order = _open_order(ctx, p)
    lines = lines_of(ctx.db, [order.id])[order.id]
    selected = _selections(lines, p)
    refund = 0
    for line, n in selected:
        ensure(
            line.returned_quantity + n <= line.shipped_quantity,
            409,
            "simulation_overreturn",
            "不能退超過已出貨數量。",
        )
        refund = check_safe(refund + check_safe(line.price_minor * n))
    ensure(
        order.refunded_minor + refund <= order.paid_minor,
        409,
        "simulation_overrefund",
        "不能超額退款。",
    )
    buyer, business = _buyer_and_business(ctx, order)
    wallets.move(ctx, "order.return", business, buyer, refund, str(order.id))
    cost_lots = cost_lots_of(ctx.db, [line.id for line, _ in selected])
    for line, n in selected:
        remaining = n
        for lot in cost_lots[line.id]:
            take = min(remaining, lot.quantity - lot.returned)
            if take > 0:
                inventory.push_lot(ctx, line.product_id, take, lot.cost_minor)
                lot.returned += take
                remaining -= take
            if remaining == 0:
                break
        ensure(remaining == 0, 409, _CORRUPT, "模擬退貨成本層不足。")
        line.returned_quantity += n
    order.refunded_minor += refund
    order.status = (
        "returned"
        if all(line.returned_quantity == line.quantity for line in lines)
        else "partially_returned"
    )
    order.updated_at = ctx.now
    ctx.db.flush()
    return str(order.id)


# --- 流水種類 -------------------------------------------------------------------


def _order_rule(db: Session, workspace_id: str, ledger: LedgerView) -> tuple[uuid.UUID, uuid.UUID]:
    """order.pay：買家 → 商家；order.cancel、order.return：商家 → 買家（訂單的買家錢包）。"""
    order = db.get(SalesOrderRow, ledger.reference_id)
    if order is None or str(order.workspace_id) != workspace_id:
        raise Problem(404, "record_missing", "找不到工作區紀錄")
    business = ledger.system["business"].id
    if ledger.kind == "order.pay":
        return order.buyer_wallet_id, business
    return business, order.buyer_wallet_id


for _kind in ("order.pay", "order.cancel", "order.return"):
    register_ledger_rule(_kind, _order_rule)
