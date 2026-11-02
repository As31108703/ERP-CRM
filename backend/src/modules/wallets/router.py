"""wallets 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_WALLETS, register_seeder
from src.modules.wallets import invariants, service, snapshot
from src.platform import records, registry
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "wallets"

HANDLERS: dict[str, Handler] = {
    "wallet.create": records.command("wallet.create", service.create_wallet),
    "wallet.fund": records.command("wallet.fund", service.fund_wallet),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(invariants.check_wallets,),
)
registry.register(SPEC)
register_seeder(MODULE, service.seed_wallets, order=SEED_WALLETS)

router = APIRouter(prefix="/api/v1/wallets")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


@router.post("")
def create_wallet(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "wallet.create"
    return pipeline.mutate(request, raw, action=action, handler=HANDLERS[action], module=MODULE)


@router.post("/{wallet_id}/fund")
def fund_wallet(
    wallet_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "wallet.fund"
    handler = records.with_path(HANDLERS[action], wallet_id=wallet_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)
