"""`office.demo.create`：在空白的行政工作台建立一組合成示範資料（A§3）。

所有資料都透過一般的行政 handler 在同一個交易裡建立，最後由命令管線統一跑一次 invariants；
任何一步失敗，整批連同版本號一起回滾。只動行政資料，其他集合與 generation 不變。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core import clock
from src.core.problem import ensure
from src.modules.administration import invariants
from src.modules.administration import validators as v
from src.modules.administration.attendance import create_attendance
from src.modules.administration.equipment import create_equipment
from src.modules.administration.notices import create_notice
from src.modules.administration.requests import create_request
from src.modules.administration.reservations import create_reservation
from src.modules.administration.schema import parse
from src.modules.administration.shifts import create_shift
from src.modules.administration.staff import create_staff
from src.modules.administration.units import create_unit
from src.platform.context import CommandContext


@dataclass(frozen=True)
class Preset:
    unit: str
    kind: str
    roles: tuple[str, str]
    equipment: str
    purchase: str
    amount_minor: int


PRESETS: dict[str, Preset] = {
    "store": Preset(
        "合成示範門市",
        "branch",
        ("示範店務", "示範行政"),
        "合成示範收銀平板",
        "合成示範請購：店務耗材",
        3200,
    ),
    "office": Preset(
        "合成示範行政組",
        "department",
        ("示範行政", "示範總務"),
        "合成示範簡報設備",
        "合成示範請購：辦公耗材",
        4500,
    ),
    "factory": Preset(
        "合成示範廠務組",
        "department",
        ("示範現場協調", "示範廠務"),
        "合成示範巡檢平板",
        "合成示範請購：巡檢耗材",
        6000,
    ),
}

STAFF = (("DEMO-1", "合成示範夥伴甲"), ("DEMO-2", "合成示範夥伴乙"))
SHIFT_NOTE = "合成示範排班，供流程練習"
ATTENDANCE_NOTE = "人工輸入的合成示範出勤，非真實打卡"
REQUEST_DESCRIPTION = "合成示範草稿，只練習行政資料整理，未送出、未核准、未付款。"
EQUIPMENT_CODE = "DEMO-EQ-1"
RESERVATION_PURPOSE = "合成示範借用，練習改期、歸還與取消"
NOTICE_GUIDE = (
    "合成示範：行政入門提醒",
    "這批資料全部為合成示範，可練習排班更正、出勤作廢、申請退回與設備借用。",
)
NOTICE_ARCHIVE = ("合成示範：公告封存練習", "完成閱讀後可封存，再從封存列表還原；資料會保留。")


def _desk_empty(ctx: CommandContext) -> bool:
    """八類資料與 changes 都沒有任何紀錄；作廢、取消、封存的資料也算。"""
    return not any(invariants.counts(ctx.db, ctx.workspace.id).values())  # type: ignore[union-attr]


def create_demo(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """建立示範資料並回傳單位 id。W 為 week_start 台北 00:00，第 d 天由 W 起算。"""
    p = parse("office.demo.create", payload)
    preset = PRESETS[v.enum_value(p["preset"], PRESETS)]
    week = clock.taipei_monday(p["week_start"]).astimezone(UTC)
    ensure(_desk_empty(ctx), 409, "office_demo_not_empty", "行政資料已有紀錄，不能覆寫成示範資料")

    def at(day: int, hour: int, minute: int = 0) -> str:
        moment: datetime = week + timedelta(days=day, hours=hour, minutes=minute)
        return clock.iso(moment)

    def run(handler: Any, body: dict[str, Any]) -> str:
        result = handler(ctx, body)
        if result is None:  # 建立類 handler 一律回傳新紀錄 id
            raise RuntimeError("示範資料建立失敗：handler 沒有回傳 id")
        return str(result)

    unit = run(create_unit, {"name": preset.unit, "kind": preset.kind})
    staff = [
        run(
            create_staff,
            {"code": code, "alias": alias, "unit_id": unit, "role_label": role},
        )
        for (code, alias), role in zip(STAFF, preset.roles, strict=True)
    ]
    for day in range(5):
        run(
            create_shift,
            {
                "staff_id": staff[day % 2],
                "unit_id": unit,
                "start_at": at(day, 9),
                "end_at": at(day, 17),
                "break_minutes": 60,
                "note": SHIFT_NOTE,
            },
        )
    for day in range(2):
        run(
            create_attendance,
            {
                "staff_id": staff[day % 2],
                "unit_id": unit,
                "start_at": at(day, 9, 5),
                "end_at": at(day, 16, 55),
                "break_minutes": 60,
                "note": ATTENDANCE_NOTE,
            },
        )
    run(
        create_request,
        {
            "type": "purchase",
            "staff_id": staff[0],
            "unit_id": unit,
            "title": preset.purchase,
            "description": REQUEST_DESCRIPTION,
            "amount_minor": preset.amount_minor,
        },
    )
    equipment = run(
        create_equipment, {"code": EQUIPMENT_CODE, "name": preset.equipment, "unit_id": unit}
    )
    run(
        create_reservation,
        {
            "equipment_id": equipment,
            "staff_id": staff[0],
            "start_at": at(1, 13),
            "end_at": at(1, 15),
            "purpose": RESERVATION_PURPOSE,
        },
    )
    run(
        create_notice,
        {
            "title": NOTICE_GUIDE[0],
            "body": NOTICE_GUIDE[1],
            "unit_id": unit,
            "pinned": True,
            "due_at": at(4, 16),
        },
    )
    run(create_notice, {"title": NOTICE_ARCHIVE[0], "body": NOTICE_ARCHIVE[1]})
    return unit
