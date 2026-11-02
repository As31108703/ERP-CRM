"""商品與庫存（B§3.5）：商品建立／更新、採購入庫、FIFO 成本層與預留。

其他模組透過 `push_lot`、`consume_fifo`、`reserve`、`release_reserved` 異動庫存（數量一律須為
≥1 的整數，否則 422 number_invalid，避免負數變成反向異動），並以
`register_reserved_demand` 申報自己佔用的預留量，供預留一致性檢查加總（Task 6 起）。
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, select

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.catalog.templates import Template
from src.modules.inventory.entity import ProductLotRow, ProductRow, PurchaseRow
from src.modules.wallets import service as wallets
from src.modules.wallets.service import LedgerView, ledger_invalid, register_ledger_rule
from src.platform.context import CommandContext
from src.platform.records import PRODUCT_NAME_MAX, check_safe, record_missing, scoped_get

COMPONENT_SKU = "MAT-001"
COMPONENT_PRICE = 1000
COMPONENT_COST = 500


# --- 查詢 -----------------------------------------------------------------------


def _ws(ctx: CommandContext) -> uuid.UUID:
    return uuid.UUID(ctx.workspace_id)


def list_products(db: Session, workspace_id: str) -> list[ProductRow]:
    stmt = (
        select(ProductRow)
        .where(ProductRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(ProductRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def list_purchases(db: Session, workspace_id: str) -> list[PurchaseRow]:
    stmt = (
        select(PurchaseRow)
        .where(PurchaseRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(PurchaseRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def lots_of(
    db: Session, workspace_id: str, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ProductLotRow]]:
    """工作區內各商品的成本層，依 FIFO 順序（id 由小到大）。"""
    out: dict[uuid.UUID, list[ProductLotRow]] = {pid: [] for pid in product_ids}
    if product_ids:
        stmt = (
            select(ProductLotRow)
            .where(
                ProductLotRow.workspace_id == uuid.UUID(workspace_id),
                ProductLotRow.product_id.in_(product_ids),  # type: ignore[attr-defined]
            )
            .order_by(ProductLotRow.id)  # type: ignore[arg-type]
        )
        for lot in db.exec(stmt):
            out[lot.product_id].append(lot)
    return out


def get_product(ctx: CommandContext, product_id: object) -> ProductRow:
    """工作區內的商品；不存在時 404 simulation_record_missing。"""
    row = scoped_get(ctx.db, ProductRow, ctx.workspace_id, product_id)
    if row is None:
        raise record_missing()
    return row


# --- 庫存異動（供其他模組使用） ----------------------------------------------------


def push_lot(ctx: CommandContext, product_id: object, quantity: int, cost_minor: int) -> None:
    """在 FIFO 佇列尾端加入成本層，並增加 on_hand 與 stock_value。"""
    quantity = check_int(quantity, min_=1)
    cost_minor = check_int(cost_minor)
    product = get_product(ctx, product_id)
    product.on_hand = check_safe(product.on_hand + quantity)
    product.stock_value_minor = check_safe(
        product.stock_value_minor + check_safe(quantity * cost_minor)
    )
    product.updated_at = ctx.now
    ctx.db.add(
        ProductLotRow(
            workspace_id=product.workspace_id,
            product_id=product.id,
            quantity=quantity,
            cost_minor=cost_minor,
        )
    )
    ctx.db.flush()


def consume_fifo(
    ctx: CommandContext,
    product_id: object,
    quantity: int,
    *,
    corrupt_code: str,
    message: str = "庫存成本層不足",
) -> list[tuple[int, int]]:
    """依 FIFO 取出 quantity 件，回傳 `(數量, 單位成本)` 清單並扣減 on_hand 與 stock_value。

    成本層不足時 409 `corrupt_code`（由呼叫端決定錯誤碼）；不處理預留量。
    """
    quantity = check_int(quantity, min_=1)
    product = get_product(ctx, product_id)
    lots = lots_of(ctx.db, ctx.workspace_id, [product.id])[product.id]
    ensure(sum(lot.quantity for lot in lots) >= quantity, 409, corrupt_code, message)
    taken: list[tuple[int, int]] = []
    remaining = quantity
    for lot in lots:
        if remaining == 0:
            break
        take = min(remaining, lot.quantity)
        taken.append((take, lot.cost_minor))
        product.stock_value_minor -= take * lot.cost_minor
        lot.quantity -= take
        remaining -= take
        if lot.quantity == 0:
            ctx.db.delete(lot)
    product.on_hand -= quantity
    product.updated_at = ctx.now
    ctx.db.flush()
    return taken


def reserve(
    ctx: CommandContext, product_id: object, quantity: int, *, code: str, message: str
) -> None:
    """預留 quantity 件；可用量（on_hand - reserved）不足時 409 `code`。"""
    quantity = check_int(quantity, min_=1)
    product = get_product(ctx, product_id)
    ensure(product.on_hand - product.reserved >= quantity, 409, code, message)
    product.reserved += quantity
    product.updated_at = ctx.now
    ctx.db.flush()


def release_reserved(ctx: CommandContext, product_id: object, quantity: int) -> None:
    """釋放預留量；釋放超過已預留時由一致性檢查擋下。"""
    quantity = check_int(quantity, min_=1)
    product = get_product(ctx, product_id)
    product.reserved -= quantity
    product.updated_at = ctx.now
    ctx.db.flush()


# (db, workspace_id) -> {product_id 字串: 佔用的預留量}
ReservedDemand = Callable[[Session, str], dict[str, int]]
_RESERVED_DEMANDS: list[ReservedDemand] = []


def register_reserved_demand(fn: ReservedDemand) -> None:
    """銷售（Task 6）與製造（Task 9）申報各自的預留需求；同一函式只登錄一次。"""
    if fn not in _RESERVED_DEMANDS:
        _RESERVED_DEMANDS.append(fn)


def reserved_demand(db: Session, workspace_id: str) -> dict[str, int]:
    """所有已登錄需求的加總，供預留一致性檢查與 `product.reserved` 比對。"""
    total: dict[str, int] = {}
    for fn in _RESERVED_DEMANDS:
        for product_id, quantity in fn(db, workspace_id).items():
            total[product_id] = total.get(product_id, 0) + quantity
    return total


# --- 命令 handler ---------------------------------------------------------------


def _new_product(
    ctx: CommandContext, *, sku: str, name: str, price_minor: int, cost_minor: int
) -> ProductRow:
    row = ProductRow(
        workspace_id=_ws(ctx),
        sku=sku,
        name=name,
        price_minor=price_minor,
        cost_minor=cost_minor,
        active=True,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return row


def create_product(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`product.create`：一律啟用、庫存為 0；payload 的 id 與 active 不採用。"""
    row = _new_product(
        ctx,
        sku=p["sku"],
        name=p["name"],
        price_minor=check_int(p.get("price_minor")),
        cost_minor=check_int(p.get("cost_minor")),
    )
    return str(row.id)


def _product_invalid() -> Problem:
    return Problem(422, "product_invalid", "商品欄位不符")


def update_product(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`product.update`：合併 name、sku、price_minor、cost_minor、active。

    停用只影響新訂單；改成本只影響之後的入庫。
    """
    product = get_product(ctx, p.get("id"))
    if "name" in p:
        name = p["name"]
        if not (isinstance(name, str) and 0 < len(name) <= PRODUCT_NAME_MAX):
            raise _product_invalid()
        product.name = name
    if "sku" in p:
        if not isinstance(p["sku"], str):
            raise _product_invalid()
        product.sku = p["sku"]
    if "active" in p:
        if not isinstance(p["active"], bool):
            raise _product_invalid()
        product.active = p["active"]
    if "price_minor" in p:
        product.price_minor = check_int(p["price_minor"])
    if "cost_minor" in p:
        product.cost_minor = check_int(p["cost_minor"])
    product.updated_at = ctx.now
    ctx.db.flush()
    return str(product.id)


def receive(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`inventory.receive {product_id, quantity}`：以商品目前成本進貨，回傳採購 id。

    商家 → 供應商付款（金額可為 0）、加入成本層、建立採購紀錄。
    """
    product = get_product(ctx, p.get("product_id"))
    quantity = check_int(p.get("quantity"), min_=1)
    cost = check_safe(product.cost_minor * quantity)
    purchase_id = uuid.uuid4()
    business = wallets.wallet_of_kind(ctx, "business")
    supplier = wallets.wallet_of_kind(ctx, "supplier")
    wallets.move(
        ctx, "inventory.receive", str(business.id), str(supplier.id), cost, str(purchase_id)
    )
    push_lot(ctx, product.id, quantity, product.cost_minor)
    ctx.db.add(
        PurchaseRow(
            id=purchase_id,
            workspace_id=_ws(ctx),
            product_id=product.id,
            name=product.name,
            quantity=quantity,
            cost_minor=product.cost_minor,
            total_minor=cost,
            created_at=ctx.now,
            updated_at=ctx.now,
        )
    )
    ctx.db.flush()
    return str(purchase_id)


def seed_products(ctx: CommandContext, template: Template) -> None:
    """B§3.0：商品 A（範本示範商品）與商品 B（材料 MAT-001），庫存皆為 0；不論模組都建立。"""
    sample = template.sample
    _new_product(
        ctx,
        sku=sample.sku,
        name=sample.product,
        price_minor=sample.price_minor,
        cost_minor=sample.cost_minor,
    )
    _new_product(
        ctx,
        sku=COMPONENT_SKU,
        name=sample.component,
        price_minor=COMPONENT_PRICE,
        cost_minor=COMPONENT_COST,
    )


# --- 流水種類 -------------------------------------------------------------------


def _receive_rule(
    db: Session, workspace_id: str, ledger: LedgerView
) -> tuple[uuid.UUID, uuid.UUID]:
    """inventory.receive：商家 → 供應商，金額等於所指採購的總額。"""
    purchase = scoped_get(db, PurchaseRow, workspace_id, ledger.reference_id)
    if purchase is None:
        raise Problem(404, "record_missing", "找不到工作區紀錄")
    if ledger.credit != purchase.total_minor:
        raise ledger_invalid("進貨流水不符")
    return ledger.system["business"].id, ledger.system["supplier"].id


register_ledger_rule("inventory.receive", _receive_rule)
