"""行政 API：`/api/v1/administration/...`，命令名稱沿用 `office.*`（Phase 5 共通規則）。"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from src.modules.administration import csv_export, invariants, snapshot, views
from src.modules.administration.attendance import (
    create_attendance,
    update_attendance,
    void_attendance,
)
from src.modules.administration.demo import create_demo
from src.modules.administration.enable import enable
from src.modules.administration.equipment import create_equipment, update_equipment
from src.modules.administration.notices import (
    archive_notice,
    create_notice,
    restore_notice,
    update_notice,
)
from src.modules.administration.requests import (
    create_request,
    prepare_request,
    return_request,
    submit_request,
    update_request,
    withdraw_request,
)
from src.modules.administration.reservations import (
    cancel_reservation,
    create_reservation,
    return_reservation,
    update_reservation,
)
from src.modules.administration.shifts import (
    cancel_shift,
    complete_shift,
    copy_week,
    create_shift,
    update_shift,
)
from src.modules.administration.staff import create_staff, update_staff
from src.modules.administration.units import create_unit, update_unit
from src.platform.context import CommandContext
from src.platform.pipeline import (
    CommandPipeline,
    Handler,
    MutationResponse,
    get_pipeline,
    raw_body,
    touch_session,
)
from src.platform.registry import ModuleSpec, register

MODULE = snapshot.MODULE

register(
    ModuleSpec(
        name=MODULE,
        snapshot=snapshot.snapshot,
        restore=snapshot.restore,
        invariants=(invariants.check,),
    )
)

HANDLERS: dict[str, Callable[[CommandContext, dict[str, Any]], str | None]] = {
    "office.enable": enable,
    "office.unit.create": create_unit,
    "office.unit.update": update_unit,
    "office.staff.create": create_staff,
    "office.staff.update": update_staff,
    "office.shift.create": create_shift,
    "office.shift.update": update_shift,
    "office.shift.cancel": cancel_shift,
    "office.shift.complete": complete_shift,
    "office.shift.copy_week": copy_week,
    "office.attendance.create": create_attendance,
    "office.attendance.update": update_attendance,
    "office.attendance.void": void_attendance,
    "office.reservation.create": create_reservation,
    "office.reservation.update": update_reservation,
    "office.reservation.return": return_reservation,
    "office.reservation.cancel": cancel_reservation,
    "office.request.create": create_request,
    "office.request.update": update_request,
    "office.request.submit": submit_request,
    "office.request.return": return_request,
    "office.request.withdraw": withdraw_request,
    "office.request.prepare": prepare_request,
    "office.demo.create": create_demo,
    "office.equipment.create": create_equipment,
    "office.equipment.update": update_equipment,
    "office.notice.create": create_notice,
    "office.notice.update": update_notice,
    "office.notice.archive": archive_notice,
    "office.notice.restore": restore_notice,
}

router = APIRouter(prefix="/api/v1/administration")
Pipeline = Depends(get_pipeline)
Raw = Depends(raw_body)
Touch = Depends(touch_session)


def _with_id(handler: Handler, row_id: str) -> Handler:
    """把 path 參數 id 併進 payload；body 若也帶 id，以路徑為準。"""

    def run(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
        return handler(ctx, {**payload, "id": row_id})

    return run


def _mutate(
    pipeline: CommandPipeline,
    request: Request,
    raw: bytes,
    action: str,
    row_id: str | None = None,
) -> MutationResponse:
    handler = HANDLERS[action]
    if row_id is not None:
        handler = _with_id(handler, row_id)
    return pipeline.mutate(request, raw, action=action, handler=handler, module=MODULE)


@router.post("/enable")
def enable_route(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    # 唯一繞過模組閘的行政命令：未啟用時才能執行
    return pipeline.mutate(request, raw, action="office.enable", handler=HANDLERS["office.enable"])


@router.post("/units")
def unit_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.unit.create")


@router.patch("/units/{row_id}")
def unit_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.unit.update", row_id)


@router.post("/staff")
def staff_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.staff.create")


@router.patch("/staff/{row_id}")
def staff_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.staff.update", row_id)


@router.post("/shifts")
def shift_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.shift.create")


@router.post("/shifts/copy-week")
def shift_copy_week(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.shift.copy_week")


@router.patch("/shifts/{row_id}")
def shift_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.shift.update", row_id)


@router.post("/shifts/{row_id}/cancel")
def shift_cancel(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.shift.cancel", row_id)


@router.post("/shifts/{row_id}/complete")
def shift_complete(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.shift.complete", row_id)


@router.post("/attendance")
def attendance_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.attendance.create")


@router.patch("/attendance/{row_id}")
def attendance_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.attendance.update", row_id)


@router.post("/attendance/{row_id}/void")
def attendance_void(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.attendance.void", row_id)


@router.post("/reservations")
def reservation_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.reservation.create")


@router.patch("/reservations/{row_id}")
def reservation_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.reservation.update", row_id)


@router.post("/reservations/{row_id}/return")
def reservation_return(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.reservation.return", row_id)


@router.post("/reservations/{row_id}/cancel")
def reservation_cancel(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.reservation.cancel", row_id)


@router.post("/demo")
def demo_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.demo.create")


@router.post("/requests")
def request_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.create")


@router.patch("/requests/{row_id}")
def request_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.update", row_id)


@router.post("/requests/{row_id}/submit")
def request_submit(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.submit", row_id)


@router.post("/requests/{row_id}/return")
def request_return(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.return", row_id)


@router.post("/requests/{row_id}/withdraw")
def request_withdraw(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.withdraw", row_id)


@router.post("/requests/{row_id}/prepare")
def request_prepare(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.request.prepare", row_id)


@router.post("/equipment")
def equipment_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.equipment.create")


@router.patch("/equipment/{row_id}")
def equipment_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.equipment.update", row_id)


@router.post("/notices")
def notice_create(
    request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.notice.create")


@router.patch("/notices/{row_id}")
def notice_update(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.notice.update", row_id)


@router.post("/notices/{row_id}/archive")
def notice_archive(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.notice.archive", row_id)


@router.post("/notices/{row_id}/restore")
def notice_restore(
    row_id: str, request: Request, raw: bytes = Raw, pipeline: CommandPipeline = Pipeline
) -> MutationResponse:
    return _mutate(pipeline, request, raw, "office.notice.restore", row_id)


# --- 唯讀檢視（A§4–A§6）：經 touch_session 計入速率限制，不改版本與資料 -----------------


@router.get("/overview")
def overview(request: Request, ctx: CommandContext = Touch) -> dict[str, Any]:
    """待辦概覽磚與入門路線；`now`（ISO，測試用）預設伺服器時間，`week` 預設 now 所在週。"""
    desk = views.load(ctx)
    query = request.query_params
    now = views.parse_now(query, ctx.now)
    return views.overview(desk, now, views.parse_week(query, now), views.parse_unit(query))


@router.get("/rows")
def rows(request: Request, ctx: CommandContext = Touch) -> dict[str, Any]:
    """目前分頁的篩選結果與篩選統計；與 CSV 匯出共用 `views.filter_rows`。"""
    desk = views.load(ctx)
    return views.rows_view(desk, views.parse_params(request.query_params, ctx.now))


@router.get("/attendance-diff")
def attendance_diff(request: Request, ctx: CommandContext = Touch) -> list[dict[str, Any]]:
    desk = views.load(ctx)
    query = request.query_params
    week = views.parse_week(query, views.parse_now(query, ctx.now))
    return views.attendance_diff(desk, week, views.parse_unit(query))


@router.get("/export.csv")
def export_csv(request: Request, ctx: CommandContext = Touch) -> Response:
    desk = views.load(ctx)
    params = views.parse_params(request.query_params, ctx.now)
    assert ctx.workspace is not None
    name, content = csv_export.export(
        desk, params, company_name=ctx.workspace.company_name, version=ctx.session_row.version
    )
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
