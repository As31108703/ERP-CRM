"""商品、成本層與採購的一致性檢查（B§2 validateWorld 子集）。"""

from sqlmodel import Session

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.inventory.entity import ProductRow, PurchaseRow
from src.modules.inventory.service import list_products, list_purchases, lots_of
from src.modules.wallets.service import credits_by_reference
from src.platform.records import PRODUCT_NAME_MAX, check_record_limit


def check_products(db: Session, workspace_id: str) -> None:
    """數值為 0..1e9 整數（number_invalid）；成本層合計等於 on_hand 與 stock_value、
    reserved ≤ on_hand（stock_invalid）；名稱 1..100 字（product_invalid）。"""
    check_record_limit(db, ProductRow, workspace_id)
    products = list_products(db, workspace_id)
    lots = lots_of(db, [p.id for p in products])
    for p in products:
        for n in (p.on_hand, p.reserved, p.stock_value_minor, p.price_minor, p.cost_minor):
            check_int(n)
        ensure(p.reserved <= p.on_hand, 422, "stock_invalid", "庫存不符")
        for lot in lots[p.id]:
            check_int(lot.quantity, min_=1)
            check_int(lot.cost_minor)
        ensure(
            sum(lot.quantity for lot in lots[p.id]) == p.on_hand
            and sum(lot.quantity * lot.cost_minor for lot in lots[p.id]) == p.stock_value_minor,
            422,
            "stock_invalid",
            "成本層不符",
        )
    for p in products:
        ensure(0 < len(p.name) <= PRODUCT_NAME_MAX, 422, "product_invalid", "商品欄位不符")


def check_purchases(db: Session, workspace_id: str) -> None:
    """每筆採購：商品存在、total = quantity * cost、total 等於 inventory.receive 流水金額。"""
    check_record_limit(db, PurchaseRow, workspace_id)
    product_ids = {p.id for p in list_products(db, workspace_id)}
    paid = credits_by_reference(db, workspace_id, "inventory.receive")
    for purchase in list_purchases(db, workspace_id):
        if purchase.product_id not in product_ids:
            raise Problem(404, "record_missing", "找不到工作區紀錄")
        ensure(
            purchase.total_minor == purchase.quantity * purchase.cost_minor
            and purchase.total_minor == paid.get(purchase.id, 0),
            422,
            "purchase_invalid",
            "採購付款與流水不符",
        )
