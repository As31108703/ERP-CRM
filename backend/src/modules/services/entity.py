"""服務與服務交付的資料列。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class ServiceRow(SQLModel, table=True):
    """title 與 source_case_title 是建立當時的案件標題快照。"""

    __tablename__ = "service"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID
    title: str
    source_case_title: str
    price_source: str
    amount_minor: int = Field(sa_type=BigInteger)
    status: str
    paid_minor: int = Field(default=0, sa_type=BigInteger)
    latest_delivery_id: uuid.UUID | None = None
    legal_confirmation: bool = False
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class ServiceDeliveryRow(SQLModel, table=True):
    """一次交付版本；seq 由小到大是交付順序。"""

    __tablename__ = "service_delivery"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    service_id: uuid.UUID
    revision: int = Field(sa_type=BigInteger)
    artifact_ref: str
    digest: str
    seq: int | None = Field(default=None, sa_column=_seq())
