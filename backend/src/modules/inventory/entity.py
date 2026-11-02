"""商品、成本層與採購的資料列。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class ProductRow(SQLModel, table=True):
    __tablename__ = "product"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workspace_id: uuid.UUID
    sku: str
    name: str
    price_minor: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)
    active: bool = True
    on_hand: int = Field(default=0, sa_type=BigInteger)
    reserved: int = Field(default=0, sa_type=BigInteger)
    stock_value_minor: int = Field(default=0, sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class ProductLotRow(SQLModel, table=True):
    """FIFO 成本層：同一商品的批次以 id 由小到大消耗。"""

    __tablename__ = "product_lot"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    product_id: uuid.UUID
    quantity: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)


class PurchaseRow(SQLModel, table=True):
    __tablename__ = "purchase"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workspace_id: uuid.UUID
    product_id: uuid.UUID
    name: str
    quantity: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)
    total_minor: int = Field(sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())
