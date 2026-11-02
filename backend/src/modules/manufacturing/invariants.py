"""製造的一致性檢查（B§2 validateWorld 的筆數上限與 BOM／工單參照、validateIntegrity 的
BOMs、Work orders）。工單佔用的預留量由 `work_order_reserved_demand` 申報，
併入 sales 的預留檢查（reservation_invalid）。"""

from sqlmodel import Session

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.inventory.service import list_products
from src.modules.manufacturing.entity import BomRow, WorkOrderRow
from src.modules.manufacturing.service import (
    COMPLETED,
    COMPONENTS_MAX,
    STATUSES,
    bom_json,
    components_of,
    consumed_lots_of,
    has_cycle,
    list_boms,
    list_work_orders,
)
from src.platform.records import LEARNING_ID_RE, check_record_limit, crm_record_missing


def _production_invalid(message: str) -> Problem:
    return Problem(422, "production_invalid", message)


def check_manufacturing(db: Session, workspace_id: str) -> None:
    """BOM 與工單各最多 500 筆（record_limit）；BOM 的成品與材料、工單的 BOM、耗料的商品都要存在
    （404 record_missing）；教學識別格式（learning_id_invalid）；BOM 版本 ≥ 1、1..30 項材料、
    材料不重複也不是成品本身（bom_invalid）；所有版本合併後的圖沒有循環（bom_cycle）；
    工單 BOM 複本等於 BOM、狀態合法、完工工單的耗料成本合計等於 actual_cost_minor 且各材料
    耗用量等於每件用量 × 工單數量（production_invalid）；數值為範圍內整數（number_invalid）。"""
    check_record_limit(db, BomRow, workspace_id)
    check_record_limit(db, WorkOrderRow, workspace_id)
    boms = list_boms(db, workspace_id)
    components = components_of(db, workspace_id, [b.id for b in boms])
    orders = list_work_orders(db, workspace_id)
    lots = consumed_lots_of(db, workspace_id, [o.id for o in orders])
    product_ids = {p.id for p in list_products(db, workspace_id)}
    bom_by_id = {b.id: b for b in boms}

    for b in boms:
        if b.product_id not in product_ids:
            raise crm_record_missing()
        for c in components[b.id]:
            if c.product_id not in product_ids:
                raise crm_record_missing()
    for o in orders:
        if o.bom_id not in bom_by_id:
            raise crm_record_missing()
        ensure(
            o.learning_run_id is None or LEARNING_ID_RE.fullmatch(o.learning_run_id) is not None,
            422,
            "learning_id_invalid",
            "教學識別不符",
        )

    for b in boms:
        check_int(b.revision, min_=1)
        rows = components[b.id]
        ensure(0 < len(rows) <= COMPONENTS_MAX, 422, "bom_invalid", "BOM不符")
        seen: set[object] = set()
        for c in rows:
            check_int(c.quantity, min_=1)
            ensure(
                c.product_id != b.product_id and c.product_id not in seen,
                422,
                "bom_invalid",
                "材料重複或循環",
            )
            seen.add(c.product_id)

    edges: dict[object, set[object]] = {}
    for b in boms:
        edges.setdefault(b.product_id, set()).update(c.product_id for c in components[b.id])
    ensure(not has_cycle(edges), 422, "bom_cycle", "BOM不能循環")

    for o in orders:
        check_int(o.quantity, min_=1)
        bom = bom_by_id[o.bom_id]
        if o.bom_snapshot != bom_json(bom, components[bom.id]) or o.status not in STATUSES:
            raise _production_invalid("製作單快照不符")
        if o.status != COMPLETED:
            continue
        check_int(o.actual_cost_minor)
        total = 0
        for lot in lots[o.id]:
            if lot.product_id not in product_ids:
                raise crm_record_missing()
            check_int(lot.quantity, min_=1)
            check_int(lot.cost_minor)
            total += lot.quantity * lot.cost_minor
        if total != o.actual_cost_minor:
            raise _production_invalid("材料成本紀錄不符")
        for c in components[bom.id]:
            used = sum(lot.quantity for lot in lots[o.id] if lot.product_id == c.product_id)
            if used != c.quantity * o.quantity:
                raise _production_invalid("材料用量不符")
