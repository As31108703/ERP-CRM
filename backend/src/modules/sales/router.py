"""sales 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.sales import invariants, service, snapshot
from src.platform import records, registry
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "sales"

HANDLERS: dict[str, Handler] = {
    "order.create": records.command("order.create", service.create_order),
    "order.pay": records.command("order.pay", service.pay_order),
    "order.ship": records.command("order.ship", service.ship_order),
    "order.return": records.command("order.return", service.return_order),
    "order.cancel": records.command("order.cancel", service.cancel_order),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(
        invariants.check_orders,
        invariants.check_reservations,
        invariants.check_stock_value,
    ),
)
registry.register(SPEC)

router = APIRouter(prefix="/api/v1/sales")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


@router.post("/orders")
def create_order(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "order.create"
    return pipeline.mutate(request, raw, action=action, handler=HANDLERS[action], module=MODULE)


def _order_action(
    action: str, order_id: str, request: Request, raw: bytes, pipeline: CommandPipeline
) -> MutationResponse:
    handler = records.with_path(HANDLERS[action], id=order_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


@router.post("/orders/{order_id}/pay")
def pay_order(
    order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _order_action("order.pay", order_id, request, raw, pipeline)


@router.post("/orders/{order_id}/ship")
def ship_order(
    order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _order_action("order.ship", order_id, request, raw, pipeline)


@router.post("/orders/{order_id}/return")
def return_order(
    order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _order_action("order.return", order_id, request, raw, pipeline)


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _order_action("order.cancel", order_id, request, raw, pipeline)
