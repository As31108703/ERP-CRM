"""銷售訂單、訂單品項與出貨成本批次的資料列。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, SmallInteger
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class SalesOrderRow(SQLModel, table=True):
    __tablename__ = "sales_order"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    learning_run_id: str | None = None
    buyer_wallet_id: uuid.UUID
    status: str
    total_minor: int = Field(sa_type=BigInteger)
    paid_minor: int = Field(default=0, sa_type=BigInteger)
    refunded_minor: int = Field(default=0, sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class OrderLineRow(SQLModel, table=True):
    """name、price_minor、cost_minor 是下單當時的商品快照。"""

    __tablename__ = "order_line"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID
    idx: int = Field(sa_type=SmallInteger)
    product_id: uuid.UUID
    name: str
    price_minor: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)
    quantity: int = Field(sa_type=BigInteger)
    shipped_quantity: int = Field(default=0, sa_type=BigInteger)
    returned_quantity: int = Field(default=0, sa_type=BigInteger)


class ShippedCostLotRow(SQLModel, table=True):
    """出貨時依 FIFO 取出的成本批次；id 由小到大是出貨順序，returned 為已退回件數。"""

    __tablename__ = "shipped_cost_lot"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    workspace_id: uuid.UUID
    line_id: uuid.UUID
    quantity: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)
    returned: int = Field(default=0, sa_type=BigInteger)
