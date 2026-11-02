"""crm 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_CRM, register_seeder
from src.modules.crm import invariants, service, snapshot
from src.modules.crm import records as crm_records
from src.platform import records, registry
from src.platform.context import CommandContext
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "crm"

# 路徑上的集合 → action 前綴
COLLECTIONS: dict[str, str] = {
    "customers": "customer",
    "contacts": "contact",
    "deals": "deal",
    "cases": "case",
}


def _generic(action: str, collection: str) -> Handler:
    fn = crm_records.generic_create if action.endswith(".create") else crm_records.generic_update

    def handler(ctx: CommandContext, p: dict) -> str:
        return fn(ctx, collection, p)

    return records.command(action, handler)


HANDLERS: dict[str, Handler] = {
    **{
        f"{prefix}.{verb}": _generic(f"{prefix}.{verb}", collection)
        for collection, prefix in COLLECTIONS.items()
        for verb in ("create", "update")
    },
    "followup.create": records.command("followup.create", service.create_followup),
    "quote.create": records.command("quote.create", service.create_quote),
    "quote.issue": records.command("quote.issue", service.issue_quote),
    "quote.confirm": records.command("quote.confirm", service.confirm_quote),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(
        invariants.check_record_limits,
        invariants.check_references,
        invariants.check_deals,
        invariants.check_quotes,
    ),
)
registry.register(SPEC)
register_seeder(MODULE, service.seed_crm, order=SEED_CRM)

router = APIRouter(prefix="/api/v1/crm")
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


for _collection, _prefix in COLLECTIONS.items():
    _add_record_routes(_collection, _prefix)


@router.post("/deals/{deal_id}/followups")
def create_followup(
    deal_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("followup.create", request, raw, pipeline, deal_id=deal_id)


@router.post("/quotes")
def create_quote(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("quote.create", request, raw, pipeline)


@router.post("/quotes/{quote_id}/issue")
def issue_quote(
    quote_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("quote.issue", request, raw, pipeline, id=quote_id)


@router.post("/quotes/{quote_id}/confirm")
def confirm_quote(
    quote_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate("quote.confirm", request, raw, pipeline, id=quote_id)
