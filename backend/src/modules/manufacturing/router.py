"""manufacturing 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_MANUFACTURING, register_seeder
from src.modules.manufacturing import invariants, service, snapshot
from src.platform import records, registry
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "manufacturing"

HANDLERS: dict[str, Handler] = {
    "bom.create": records.command("bom.create", service.create_bom),
    "workOrder.create": records.command("workOrder.create", service.create_work_order),
    "workOrder.reserve": records.command("workOrder.reserve", service.reserve_work_order),
    "workOrder.start": records.command("workOrder.start", service.start_work_order),
    "workOrder.complete": records.command("workOrder.complete", service.complete_work_order),
    "workOrder.cancel": records.command("workOrder.cancel", service.cancel_work_order),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(invariants.check_manufacturing,),
)
registry.register(SPEC)
register_seeder(MODULE, service.seed_manufacturing, order=SEED_MANUFACTURING)

router = APIRouter(prefix="/api/v1/manufacturing")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


def _mutate(
    action: str, request: Request, raw: bytes, pipeline: CommandPipeline
) -> MutationResponse:
    return pipeline.mutate(request, raw, action=action, handler=HANDLERS[action], module=MODULE)


@router.post("/boms")
def create_bom(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("bom.create", request, raw, pipeline)


@router.post("/work-orders")
def create_work_order(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("workOrder.create", request, raw, pipeline)


def _work_order_action(
    action: str, work_order_id: str, request: Request, raw: bytes, pipeline: CommandPipeline
) -> MutationResponse:
    handler = records.with_path(HANDLERS[action], id=work_order_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


@router.post("/work-orders/{work_order_id}/reserve")
def reserve_work_order(
    work_order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _work_order_action("workOrder.reserve", work_order_id, request, raw, pipeline)


@router.post("/work-orders/{work_order_id}/start")
def start_work_order(
    work_order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _work_order_action("workOrder.start", work_order_id, request, raw, pipeline)


@router.post("/work-orders/{work_order_id}/complete")
def complete_work_order(
    work_order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _work_order_action("workOrder.complete", work_order_id, request, raw, pipeline)


@router.post("/work-orders/{work_order_id}/cancel")
def cancel_work_order(
    work_order_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _work_order_action("workOrder.cancel", work_order_id, request, raw, pipeline)
