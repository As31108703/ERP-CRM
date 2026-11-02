"""備份 API：匯出、匯入（上限 3 MiB）與本機啟動包下載。"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from src.modules.backup import launch_kit, service
from src.platform.context import CommandContext
from src.platform.pipeline import (
    IMPORT_BODY_LIMIT,
    CommandPipeline,
    MutationResponse,
    get_pipeline,
    raw_body,
    touch_session,
)

router = APIRouter(prefix="/api/v1/backup")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)
Touch = Depends(touch_session)


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/export")
def export(ctx: CommandContext = Touch) -> JSONResponse:
    return JSONResponse(service.export(ctx), headers=_attachment(service.BACKUP_FILENAME))


@router.post("/import")
def import_backup(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return pipeline.mutate(
        request,
        raw,
        action="workspace.import",
        handler=service.import_backup,
        needs_workspace=False,
        body_limit=IMPORT_BODY_LIMIT,
        prunes_receipts=True,
        bypass_receipt_cap=True,
    )


@router.get("/launch-kit")
def download_launch_kit(
    industry: str | None = None,
    company_name: str | None = None,
    modules: str | None = None,
    _ctx: CommandContext = Touch,
) -> Response:
    config = launch_kit.normalize(industry, company_name, modules)
    return Response(
        launch_kit.build(config),
        media_type="application/zip",
        headers=_attachment(launch_kit.LAUNCH_KIT_FILENAME),
    )
