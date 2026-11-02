"""流程教學的 HTTP 路由。

讀取與偏好寫入（start、restart、view）不增加工作區版本；執行一步走命令管線，
action 與 module 取自該步的命令，因此 history 與收據都記錄實際的業務命令。
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from src.modules.learning import service
from src.platform.context import CommandContext
from src.platform.pipeline import (
    CommandPipeline,
    MutationResponse,
    get_pipeline,
    raw_body,
    touch_session,
)

router = APIRouter(prefix="/api/v1/learning")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)
Touch = Depends(touch_session)

# 路線或步驟無法辨識時的 action；handler 會在管線的標頭檢查之後回 404／422
UNKNOWN_ACTION = "learning.execute"


@router.get("")
def listing(ctx: CommandContext = Touch) -> dict[str, Any]:
    return service.listing(ctx)


@router.get("/{path}")
def detail(path: str, ctx: CommandContext = Touch) -> dict[str, Any]:
    return service.detail(ctx, path)


@router.post("/{path}/start")
def start(
    path: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> dict[str, Any]:
    return pipeline.preference(request, raw, handler=lambda ctx, b: service.start(ctx, path, b))


@router.post("/{path}/restart")
def restart(
    path: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> dict[str, Any]:
    return pipeline.preference(request, raw, handler=lambda ctx, b: service.restart(ctx, path, b))


@router.patch("/{path}/view")
def view(
    path: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> dict[str, Any]:
    return pipeline.preference(
        request, raw, handler=lambda ctx, b: service.update_view(ctx, path, b)
    )


def _peek(raw: bytes) -> Any:
    """先讀出 step_id 以決定 action；格式錯誤交給管線回正式的錯誤碼。"""
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


@router.post("/{path}/execute")
def execute(
    path: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    step = service.requested_step(path, _peek(raw))
    action = step.action if step is not None else UNKNOWN_ACTION
    module = service.module_of(step.action) if step is not None else None
    return pipeline.mutate(
        request, raw, action=action, handler=service.execute_handler(path), module=module
    )
