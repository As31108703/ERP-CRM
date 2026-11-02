"""inventory 模組的 HTTP 路由、命令表與模組登錄。"""

from fastapi import APIRouter, Depends, Request

from src.modules.catalog.seed import SEED_PRODUCTS, register_seeder
from src.modules.inventory import invariants, service, snapshot
from src.platform import records, registry
from src.platform.pipeline import CommandPipeline, MutationResponse, get_pipeline, raw_body
from src.platform.records import Handler

MODULE = "inventory"

HANDLERS: dict[str, Handler] = {
    "product.create": records.command("product.create", service.create_product),
    "product.update": records.command("product.update", service.update_product),
    "inventory.receive": records.command("inventory.receive", service.receive),
}

SPEC = registry.ModuleSpec(
    name=MODULE,
    snapshot=snapshot.snapshot,
    restore=snapshot.restore,
    invariants=(invariants.check_products, invariants.check_purchases),
    id_paths=("products", "purchases"),
)
registry.register(SPEC)
register_seeder(MODULE, service.seed_products, order=SEED_PRODUCTS)

router = APIRouter(prefix="/api/v1/inventory")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)


@router.post("/products")
def create_product(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "product.create"
    return pipeline.mutate(request, raw, action=action, handler=HANDLERS[action], module=MODULE)


@router.patch("/products/{product_id}")
def update_product(
    product_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "product.update"
    handler = records.with_path(HANDLERS[action], id=product_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


@router.post("/products/{product_id}/receive")
def receive(
    product_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    action = "inventory.receive"
    handler = records.with_path(HANDLERS[action], product_id=product_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)
