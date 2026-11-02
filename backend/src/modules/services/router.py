"""services 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_SERVICES, register_seeder
from src.modules.services import invariants, service, snapshot
from src.platform import records, registry
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "services"

HANDLERS: dict[str, Handler] = {
    "service.create": records.command("service.create", service.create_service),
    "service.confirm": records.command("service.confirm", service.confirm_service),
    "service.deliver": records.command("service.deliver", service.deliver_service),
    "service.accept": records.command("service.accept", service.accept_service),
    "service.request_changes": records.command("service.request_changes", service.request_changes),
    "service.pay": records.command("service.pay", service.pay_service),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(invariants.check_services,),
    id_paths=("services", "services.deliveries"),
)
registry.register(SPEC)
register_seeder(MODULE, service.seed_services, order=SEED_SERVICES)

router = APIRouter(prefix="/api/v1/services")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


@router.post("")
def create_service(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "service.create"
    return pipeline.mutate(request, raw, action=action, handler=HANDLERS[action], module=MODULE)


def _service_action(
    action: str, service_id: str, request: Request, raw: bytes, pipeline: CommandPipeline
) -> MutationResponse:
    handler = records.with_path(HANDLERS[action], id=service_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


@router.post("/{service_id}/confirm")
def confirm_service(
    service_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _service_action("service.confirm", service_id, request, raw, pipeline)


@router.post("/{service_id}/deliver")
def deliver_service(
    service_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _service_action("service.deliver", service_id, request, raw, pipeline)


@router.post("/{service_id}/accept")
def accept_service(
    service_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _service_action("service.accept", service_id, request, raw, pipeline)


@router.post("/{service_id}/request-changes")
def request_changes(
    service_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _service_action("service.request_changes", service_id, request, raw, pipeline)


@router.post("/{service_id}/pay")
def pay_service(
    service_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _service_action("service.pay", service_id, request, raw, pipeline)
