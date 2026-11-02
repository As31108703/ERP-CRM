"""行政模組資料表（A§1）。所有資料列都有 id、created_at、updated_at；seq 只存在資料庫，供排序。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _tz(nullable: bool = False) -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=nullable)


class AdmUnit(SQLModel, table=True):
    __tablename__ = "adm_unit"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    name: str
    kind: str
    parent_id: uuid.UUID | None = None
    active: bool
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmStaff(SQLModel, table=True):
    __tablename__ = "adm_staff"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    code: str
    alias: str
    unit_id: uuid.UUID
    role_label: str
    status: str
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmShift(SQLModel, table=True):
    __tablename__ = "adm_shift"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    staff_id: uuid.UUID
    unit_id: uuid.UUID
    start_at: datetime = Field(sa_column=_tz())
    end_at: datetime = Field(sa_column=_tz())
    break_minutes: int
    note: str
    status: str
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmAttendance(SQLModel, table=True):
    __tablename__ = "adm_attendance"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    staff_id: uuid.UUID
    unit_id: uuid.UUID
    start_at: datetime = Field(sa_column=_tz())
    end_at: datetime = Field(sa_column=_tz())
    break_minutes: int
    note: str
    voided: bool = False
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmRequest(SQLModel, table=True):
    __tablename__ = "adm_request"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    type: str
    staff_id: uuid.UUID | None = None
    unit_id: uuid.UUID
    title: str
    description: str
    amount_minor: int
    currency: str = "SIM"
    start_at: datetime | None = Field(default=None, sa_column=_tz(nullable=True))
    end_at: datetime | None = Field(default=None, sa_column=_tz(nullable=True))
    status: str
    processing_note: str
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmRequestTransition(SQLModel, table=True):
    __tablename__ = "adm_request_transition"

    workspace_id: uuid.UUID = Field(primary_key=True)
    request_id: uuid.UUID = Field(primary_key=True)
    seq: int = Field(primary_key=True)
    status: str
    at: datetime = Field(sa_column=_tz())
    note: str


class AdmEquipment(SQLModel, table=True):
    __tablename__ = "adm_equipment"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    code: str
    name: str
    unit_id: uuid.UUID
    state: str
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmReservation(SQLModel, table=True):
    __tablename__ = "adm_reservation"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    equipment_id: uuid.UUID
    staff_id: uuid.UUID
    start_at: datetime = Field(sa_column=_tz())
    end_at: datetime = Field(sa_column=_tz())
    purpose: str
    status: str
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmNotice(SQLModel, table=True):
    __tablename__ = "adm_notice"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    title: str
    body: str
    unit_id: uuid.UUID | None = None
    pinned: bool
    due_at: datetime | None = Field(default=None, sa_column=_tz(nullable=True))
    archived: bool = False
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())


class AdmChange(SQLModel, table=True):
    """更正與封存紀錄；before／after 是 `snapshot.row_out` 輸出的整列快照。"""

    __tablename__ = "adm_change"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(primary_key=True)
    kind: str
    record_id: uuid.UUID
    at: datetime = Field(sa_column=_tz())
    reason: str
    before: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    after: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))


# 快照與備份的集合鍵 → 資料表（changes 另外處理）
COLLECTIONS: dict[str, type[SQLModel]] = {
    "units": AdmUnit,
    "staff": AdmStaff,
    "shifts": AdmShift,
    "attendance": AdmAttendance,
    "requests": AdmRequest,
    "equipment": AdmEquipment,
    "reservations": AdmReservation,
    "notices": AdmNotice,
}

# A§0 每類資料的筆數上限；作廢、取消、封存的資料也計入
RECORD_LIMITS: dict[str, int] = {
    "units": 50,
    "staff": 100,
    "shifts": 200,
    "attendance": 200,
    "requests": 100,
    "equipment": 100,
    "reservations": 200,
    "notices": 100,
}
CHANGE_LIMIT = 200
TRANSITION_LIMIT = 50

# change 的 kind → 目標集合
CHANGE_COLLECTIONS: dict[str, str] = {
    "shift.update": "shifts",
    "attendance.update": "attendance",
    "attendance.void": "attendance",
    "reservation.update": "reservations",
    "notice.archive": "notices",
    "notice.restore": "notices",
}


def by_seq(model: type[SQLModel]) -> Any:
    """依寫入順序排序的 ORDER BY 子句（seq 只存在資料庫）。"""
    return text(f"{model.__tablename__}.seq")  # type: ignore[attr-defined]
