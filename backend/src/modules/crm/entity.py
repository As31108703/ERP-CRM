"""CRM 通用紀錄、商機跟進與報價的資料列。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _tz_null() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=True)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class CrmRecordRow(SQLModel, table=True):
    """customers、contacts、deals、cases、tasks、milestones 共用的通用紀錄（B§3.2）。"""

    __tablename__ = "crm_record"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workspace_id: uuid.UUID
    collection: str
    name: str | None = None
    title: str | None = None
    customer_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    status: str | None = None
    notes: str | None = None
    lost_reason: str | None = None
    due_at: datetime | None = Field(default=None, sa_column=_tz_null())
    email: str | None = None
    phone: str | None = None
    amount_minor: int | None = Field(default=None, sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class DealFollowupRow(SQLModel, table=True):
    __tablename__ = "deal_followup"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    deal_id: uuid.UUID
    note: str
    created_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class QuoteRow(SQLModel, table=True):
    __tablename__ = "quote"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workspace_id: uuid.UUID
    case_id: uuid.UUID
    amount_minor: int = Field(sa_type=BigInteger)
    expires_at: datetime = Field(sa_column=_tz())
    status: str
    legal_confirmation: bool = False
    digest: str | None = None
    issued_at: datetime | None = Field(default=None, sa_column=_tz_null())
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())
