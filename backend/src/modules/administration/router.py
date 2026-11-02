"""行政 API：`/api/v1/administration/...`，命令名稱沿用 `office.*`（Phase 5 共通規則）。"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request

from src.modules.administration import invariants, snapshot
from src.modules.administration.attendance import (
    create_attendance,
    update_attendance,
    void_attendance,
)
from src.modules.administration.enable import enable
from src.modules.administration.equipment import create_equipment, update_equipment
from src.modules.administration.notices import (
    archive_notice,
    create_notice,
    restore_notice,
    update_notice,
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
from src.platform.pipeline import CommandPipeline, Handler, MutationResponse, get_pipeline, raw_body
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
