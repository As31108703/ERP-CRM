"""projects 模組的 HTTP 路由、命令表與模組登錄。

筆數上限（record_limit）與 customer_id／case_id 參照（record_missing）由 crm 的一致性檢查
涵蓋所有通用紀錄集合，包含 tasks、milestones，因此這裡不另外登錄 invariants。
"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_PROJECTS, register_seeder
from src.modules.projects import service, snapshot
from src.platform import records, registry
from src.platform.context import CommandContext
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = service.MODULE


def _generic(action: str, collection: str) -> Handler:
    fn = service.create_record if action.endswith(".create") else service.update_record

    def handler(ctx: CommandContext, p: dict) -> str:
        return fn(ctx, collection, p)

    return records.command(action, handler)


HANDLERS: dict[str, Handler] = {
    f"{prefix}.{verb}": _generic(f"{prefix}.{verb}", collection)
    for collection, prefix in service.COLLECTIONS.items()
    for verb in ("create", "update")
}

SPEC = registry.ModuleSpec(name=MODULE, snapshot=snapshot.snapshot, restore=snapshot.restore)
registry.register(SPEC)
register_seeder(MODULE, service.seed_projects, order=SEED_PROJECTS)

router = APIRouter(prefix="/api/v1/projects")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


def _mutate(
    action: str, request: Request, raw: bytes, pipeline: CommandPipeline, **params: str
) -> MutationResponse:
    handler = records.with_path(HANDLERS[action], **params) if params else HANDLERS[action]
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


def _add_record_routes(collection: str, prefix: str) -> None:
    def create(
        request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return _mutate(f"{prefix}.create", request, raw, pipeline)

    def update(
        record_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
    ) -> MutationResponse:
        return _mutate(f"{prefix}.update", request, raw, pipeline, id=record_id)

    router.add_api_route(f"/{collection}", create, methods=["POST"], name=f"create_{prefix}")
    router.add_api_route(
        f"/{collection}/{{record_id}}", update, methods=["PATCH"], name=f"update_{prefix}"
    )


for _collection, _prefix in service.COLLECTIONS.items():
    _add_record_routes(_collection, _prefix)
