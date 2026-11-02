"""工作區 API：檢視（含自動建立）、建立、清除與收據查詢。"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from src.core.problem import Problem
from src.middleware.session import session_token
from src.modules.workspace import service
from src.platform import invariants, receipts
from src.platform.context import CommandContext
from src.platform.pipeline import (
    CommandPipeline,
    MutationResponse,
    get_pipeline,
    load_workspace,
    lock_session,
    raw_body,
    touch_session,
)

router = APIRouter(prefix="/api/v1/workspace")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)
Touch = Depends(touch_session)


def _auto_setup(request: Request, ctx: CommandContext) -> None:
    """在鎖住 session 列的交易內再確認一次，避免並行的第一次檢視重複建立。"""
    try:
        ctx.session_row = lock_session(ctx.db, session_token(request), ctx.now)
        ctx.workspace = load_workspace(ctx.db, ctx.session_row.id)
        if service.should_auto_setup(ctx):
            service.auto_setup(ctx)
            invariants.check_all(ctx)
        ctx.db.commit()
    except BaseException:
        ctx.db.rollback()
        raise


@router.get("/view")
def view(request: Request, ctx: CommandContext = Touch) -> dict[str, Any]:
    if service.should_auto_setup(ctx):
        _auto_setup(request, ctx)
    return service.view(ctx)


@router.get("/receipts/{key}")
def receipt(key: str, ctx: CommandContext = Touch) -> dict[str, Any]:
    row = receipts.find(ctx.db, ctx.session_row.id, key)
    if row is None:
        raise Problem(404, "receipt_missing", "找不到收據")
    return {"receipt": receipts.to_out(row)}


@router.post("/setup")
def setup(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return pipeline.mutate(
        request,
        raw,
        action="workspace.setup",
        handler=service.setup,
        needs_workspace=False,
        prunes_receipts=True,
        bypass_receipt_cap=True,
    )


@router.post("/clear")
def clear(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return pipeline.mutate(
        request,
        raw,
        action="workspace.clear",
        handler=service.clear,
        needs_workspace=False,
        prunes_receipts=True,
        bypass_receipt_cap=True,
    )
