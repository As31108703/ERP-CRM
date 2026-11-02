"""BOM、BOM 材料、工單與工單耗料成本層的資料列。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class BomRow(SQLModel, table=True):
    """不可變的 BOM 版本；同一成品的 revision 依建立順序遞增。"""

    __tablename__ = "bom"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    product_id: uuid.UUID
    revision: int = Field(sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class BomComponentRow(SQLModel, table=True):
    """BOM 的一項材料；idx 是材料在 BOM 中的順序。"""

    __tablename__ = "bom_component"

    workspace_id: uuid.UUID = Field(primary_key=True)
    bom_id: uuid.UUID = Field(primary_key=True)
    idx: int = Field(primary_key=True, sa_type=SmallInteger)
    product_id: uuid.UUID
    quantity: int = Field(sa_type=BigInteger)


class WorkOrderRow(SQLModel, table=True):
    """bom_snapshot 是建立當時 BOM 的完整複本（與快照中的 BOM 相同）。"""

    __tablename__ = "work_order"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    learning_run_id: str | None = None
    bom_id: uuid.UUID
    bom_snapshot: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    quantity: int = Field(sa_type=BigInteger)
    status: str
    actual_cost_minor: int | None = Field(default=None, sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class ConsumedMaterialLotRow(SQLModel, table=True):
    """完工時依 FIFO 耗用的材料成本層；id 由小到大是耗用順序。"""

    __tablename__ = "consumed_material_lot"

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    workspace_id: uuid.UUID
    work_order_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int = Field(sa_type=BigInteger)
    cost_minor: int = Field(sa_type=BigInteger)
