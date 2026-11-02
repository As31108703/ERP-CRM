"""製造（B§3.8）：版本化且不可變的 BOM、工單備料 → 開工 → 完工（材料 FIFO 耗用與完工成本分攤）、
取消釋放預留。

- BOM 建立後不再修改；同一成品再建立 BOM 就是新版本（revision = 既有數量 + 1）。
- 工單建立時保存 BOM 的完整複本 `bom_snapshot`，之後的備料、完工與預留需求都依這份複本。
- 完工時材料成本合計 `cost` 分攤到 `quantity` 件成品：`unit = cost // qty`、`extra = cost % qty`，
  `extra > 0` 時先推入成本層 `(extra, unit + 1)`，再推入 `(qty - extra, unit)`。
- 製造只在商品之間移轉庫存價值，不動任何錢包，也不寫流水。
"""

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlmodel import Session, select

from src.core import clock
from src.core.money import check_int
from src.core.problem import ensure
from src.modules.catalog.templates import Template
from src.modules.inventory import service as inventory
from src.modules.inventory.entity import ProductRow
from src.modules.manufacturing.entity import (
    BomComponentRow,
    BomRow,
    ConsumedMaterialLotRow,
    WorkOrderRow,
)
from src.platform.context import CommandContext
from src.platform.records import crm_record_missing, scoped_get

PLANNED = "planned"
RESERVED = "reserved"
STARTED = "started"
COMPLETED = "completed"
CANCELLED = "cancelled"
STATUSES = (PLANNED, RESERVED, STARTED, COMPLETED, CANCELLED)
# 佔用材料預留量的狀態
HOLDING = (RESERVED, STARTED)
CANCELLABLE = (PLANNED, RESERVED, STARTED)
COMPONENTS_MAX = 30


# --- 查詢 -----------------------------------------------------------------------


def list_boms(db: Session, workspace_id: str) -> list[BomRow]:
    stmt = (
        select(BomRow).where(BomRow.workspace_id == uuid.UUID(workspace_id)).order_by(BomRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def components_of(
    db: Session, workspace_id: str, bom_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[BomComponentRow]]:
    """工作區內各 BOM 的材料，依 idx 排序。"""
    out: dict[uuid.UUID, list[BomComponentRow]] = {bid: [] for bid in bom_ids}
    if bom_ids:
        stmt = (
            select(BomComponentRow)
            .where(
                BomComponentRow.workspace_id == uuid.UUID(workspace_id),
                BomComponentRow.bom_id.in_(bom_ids),  # type: ignore[attr-defined]
            )
            .order_by(BomComponentRow.bom_id, BomComponentRow.idx)  # type: ignore[arg-type]
        )
        for c in db.exec(stmt):
            out[c.bom_id].append(c)
    return out


def list_work_orders(db: Session, workspace_id: str) -> list[WorkOrderRow]:
    stmt = (
        select(WorkOrderRow)
        .where(WorkOrderRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(WorkOrderRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def consumed_lots_of(
    db: Session, workspace_id: str, work_order_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ConsumedMaterialLotRow]]:
    """工作區內各工單的耗料成本層，依耗用順序。"""
    out: dict[uuid.UUID, list[ConsumedMaterialLotRow]] = {wid: [] for wid in work_order_ids}
    if work_order_ids:
        stmt = (
            select(ConsumedMaterialLotRow)
            .where(
                ConsumedMaterialLotRow.workspace_id == uuid.UUID(workspace_id),
                ConsumedMaterialLotRow.work_order_id.in_(work_order_ids),  # type: ignore[attr-defined]
            )
            .order_by(ConsumedMaterialLotRow.id)  # type: ignore[arg-type]
        )
        for lot in db.exec(stmt):
            out[lot.work_order_id].append(lot)
    return out


def bom_json(bom: BomRow, components: list[BomComponentRow]) -> dict[str, Any]:
    """BOM 的快照形式；工單的 bom_snapshot 必須與它完全相同。"""
    return {
        "id": str(bom.id),
        "product_id": str(bom.product_id),
        "components": [
            {"product_id": str(c.product_id), "quantity": c.quantity} for c in components
        ],
        "revision": bom.revision,
        "created_at": clock.iso(bom.created_at),
    }


def snapshot_components(work_order: WorkOrderRow) -> list[tuple[str, int]]:
    """工單 BOM 複本中的材料 `(product_id, 每件用量)`；格式不符的項目略過
    （一致性檢查會以 production_invalid 擋下）。"""
    components = work_order.bom_snapshot.get("components") if work_order.bom_snapshot else None
    out: list[tuple[str, int]] = []
    if isinstance(components, list):
        for c in components:
            if isinstance(c, Mapping) and isinstance(c.get("quantity"), int):
                out.append((str(c.get("product_id")), c["quantity"]))
    return out


def has_cycle(edges: Mapping[Any, Iterable[Any]]) -> bool:
    """有向圖（成品 → 材料）是否有循環；以迭代 DFS 三色標記，避免遞迴深度限制。"""
    done: set[Any] = set()
    for root in edges:
        if root in done:
            continue
        on_path = {root}
        stack = [(root, iter(edges.get(root, ())))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                on_path.discard(node)
                done.add(node)
                continue
            if child in on_path:
                return True
            if child not in done:
                on_path.add(child)
                stack.append((child, iter(edges.get(child, ()))))
    return False


def _product(ctx: CommandContext, product_id: object) -> ProductRow:
    """工作區內的商品；不存在時 404 record_missing。"""
    row = scoped_get(ctx.db, ProductRow, ctx.workspace_id, product_id)
    if row is None:
        raise crm_record_missing()
    return row


def get_bom(ctx: CommandContext, bom_id: object) -> BomRow:
    """工作區內的 BOM；不存在時 404 record_missing。"""
    row = scoped_get(ctx.db, BomRow, ctx.workspace_id, bom_id)
    if row is None:
        raise crm_record_missing()
    return row


def get_work_order(ctx: CommandContext, work_order_id: object) -> WorkOrderRow:
    """工作區內的工單；不存在時 404 record_missing。"""
    row = scoped_get(ctx.db, WorkOrderRow, ctx.workspace_id, work_order_id)
    if row is None:
        raise crm_record_missing()
    return row


def work_order_reserved_demand(db: Session, workspace_id: str) -> dict[str, int]:
    """已預留或已開工的工單佔用的材料：Σ 每件用量 × 工單數量，依商品加總。"""
    total: dict[str, int] = {}
    for wo in list_work_orders(db, workspace_id):
        if wo.status in HOLDING:
            for product_id, quantity in snapshot_components(wo):
                total[product_id] = total.get(product_id, 0) + quantity * wo.quantity
    return total


inventory.register_reserved_demand(work_order_reserved_demand)


# --- 命令 handler ---------------------------------------------------------------


def _new_bom(
    ctx: CommandContext, product_id: uuid.UUID, components: list[tuple[uuid.UUID, int]]
) -> str:
    stmt = select(BomRow).where(
        BomRow.workspace_id == uuid.UUID(ctx.workspace_id), BomRow.product_id == product_id
    )
    revision = len(list(ctx.db.exec(stmt))) + 1
    bom = BomRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        product_id=product_id,
        revision=revision,
        created_at=ctx.now,
    )
    ctx.db.add(bom)
    ctx.db.flush()
    for idx, (component_id, quantity) in enumerate(components):
        ctx.db.add(
            BomComponentRow(
                workspace_id=bom.workspace_id,
                bom_id=bom.id,
                idx=idx,
                product_id=component_id,
                quantity=quantity,
            )
        )
    ctx.db.flush()
    return str(bom.id)


def create_bom(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`bom.create {product_id, components: [{product_id, quantity}]}`：成品與材料須存在（404
    record_missing）；1..30 項材料（bom_invalid）；材料不可重複或是成品本身，且加入後各成品最新版本
    的邊不可形成循環（bom_cycle）。所有版本合併後的循環由一致性檢查再確認。"""
    product = _product(ctx, p.get("product_id"))
    raw = p.get("components")
    ensure(
        isinstance(raw, list) and 0 < len(raw) <= COMPONENTS_MAX,
        422,
        "bom_invalid",
        "請指定材料",
    )
    components: list[tuple[uuid.UUID, int]] = []
    seen: set[uuid.UUID] = set()
    for c in raw:  # type: ignore[union-attr]
        item = c if isinstance(c, dict) else {}
        material = _product(ctx, item.get("product_id"))
        quantity = check_int(item.get("quantity"), min_=1)
        ensure(
            material.id != product.id and material.id not in seen,
            422,
            "bom_cycle",
            "材料不能重複或包含成品",
        )
        seen.add(material.id)
        components.append((material.id, quantity))
    boms = list_boms(ctx.db, ctx.workspace_id)
    existing = components_of(ctx.db, ctx.workspace_id, [b.id for b in boms])
    # 依建立順序覆寫，留下每個成品最新版本的邊
    edges: dict[uuid.UUID, list[uuid.UUID]] = {
        b.product_id: [c.product_id for c in existing[b.id]] for b in boms
    }
    edges[product.id] = [material for material, _ in components]
    ensure(not has_cycle(edges), 422, "bom_cycle", "BOM不能循環")
    return _new_bom(ctx, product.id, components)


def create_work_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`workOrder.create {bom_id, quantity, learning_run_id?}`：保存 BOM 複本，狀態 planned。"""
    bom = get_bom(ctx, p.get("bom_id"))
    quantity = check_int(p.get("quantity"), min_=1)
    snapshot = bom_json(bom, components_of(ctx.db, ctx.workspace_id, [bom.id])[bom.id])
    row = WorkOrderRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        learning_run_id=p.get("learning_run_id") or None,
        bom_id=bom.id,
        bom_snapshot=snapshot,
        quantity=quantity,
        status=PLANNED,
        actual_cost_minor=None,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return str(row.id)


def _touch(ctx: CommandContext, wo: WorkOrderRow) -> str:
    wo.updated_at = ctx.now
    ctx.db.flush()
    return str(wo.id)


def _needs(wo: WorkOrderRow) -> list[tuple[str, int]]:
    """各材料的總用量 `(product_id, 每件用量 × 工單數量)`，依 BOM 順序。"""
    return [(pid, quantity * wo.quantity) for pid, quantity in snapshot_components(wo)]


def reserve_work_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`workOrder.reserve {id}`：planned 才能預留（409 production_state）；每項材料可用量
    （on_hand - reserved）須足夠（409 materials_insufficient），狀態變 reserved。"""
    wo = get_work_order(ctx, p.get("id"))
    ensure(wo.status == PLANNED, 409, "production_state", "請先建立計畫")
    for product_id, n in _needs(wo):
        inventory.reserve(ctx, product_id, n, code="materials_insufficient", message="材料不足")
    wo.status = RESERVED
    return _touch(ctx, wo)


def start_work_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`workOrder.start {id}`：reserved → started，否則 409 production_state。"""
    wo = get_work_order(ctx, p.get("id"))
    ensure(wo.status == RESERVED, 409, "production_state", "請先預留材料")
    wo.status = STARTED
    return _touch(ctx, wo)


def complete_work_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`workOrder.complete {id}`：started 才能完工（409 production_state）。各材料釋放預留並依
    FIFO 耗用（成本層不足 409 stock_invalid），耗料記入 consumed_material_lots；成品依分攤規則
    推入成本層。不動錢包。"""
    wo = get_work_order(ctx, p.get("id"))
    ensure(wo.status == STARTED, 409, "production_state", "請先開工")
    cost = 0
    for product_id, n in _needs(wo):
        inventory.release_reserved(ctx, product_id, n)
        taken = inventory.consume_fifo(
            ctx, product_id, n, corrupt_code="stock_invalid", message="材料成本層不足"
        )
        for quantity, unit_cost in taken:
            ctx.db.add(
                ConsumedMaterialLotRow(
                    workspace_id=wo.workspace_id,
                    work_order_id=wo.id,
                    product_id=uuid.UUID(product_id),
                    quantity=quantity,
                    cost_minor=unit_cost,
                )
            )
            cost += quantity * unit_cost
    cost = check_int(cost)
    finished = wo.bom_snapshot["product_id"]
    unit, extra = divmod(cost, wo.quantity)
    if extra > 0:
        inventory.push_lot(ctx, finished, extra, unit + 1)
    inventory.push_lot(ctx, finished, wo.quantity - extra, unit)
    wo.actual_cost_minor = cost
    wo.status = COMPLETED
    return _touch(ctx, wo)


def cancel_work_order(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`workOrder.cancel {id}`：planned／reserved／started 可取消（否則 409 production_state）；
    已預留的材料全數釋放。"""
    wo = get_work_order(ctx, p.get("id"))
    ensure(wo.status in CANCELLABLE, 409, "production_state", "製作單不能取消")
    if wo.status != PLANNED:
        for product_id, n in _needs(wo):
            inventory.release_reserved(ctx, product_id, n)
    wo.status = CANCELLED
    return _touch(ctx, wo)


# --- seed -----------------------------------------------------------------------


def seed_manufacturing(ctx: CommandContext, template: Template) -> None:
    """B§3.0：啟用 manufacturing 時建立 BOM 第 1 版：商品 A ← 商品 B × bom_quantity（預設 1）。"""
    assert ctx.workspace is not None
    if "manufacturing" not in ctx.workspace.modules:
        return
    finished, material = inventory.list_products(ctx.db, ctx.workspace_id)[:2]
    quantity = template.sample.bom_quantity
    _new_bom(ctx, finished.id, [(material.id, 1 if quantity is None else quantity)])
