"""錢包、帳本與分錄的資料列。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, SmallInteger
from sqlmodel import Field, SQLModel

SYSTEM_KINDS = ("business", "supplier", "faucet")
WALLET_KINDS = (*SYSTEM_KINDS, "buyer")


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _seq() -> Column:  # type: ignore[type-arg]
    # bigserial：寫入時不帶值（None 會被省略），由資料庫產生，保留建立順序
    return Column(BigInteger, server_default=FetchedValue(), nullable=False)


class WalletRow(SQLModel, table=True):
    __tablename__ = "wallet"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str
    name: str
    balance_minor: int = Field(default=0, sa_type=BigInteger)
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class LedgerRow(SQLModel, table=True):
    __tablename__ = "ledger"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str
    reference_id: uuid.UUID
    created_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(default=None, sa_column=_seq())


class LedgerEntryRow(SQLModel, table=True):
    __tablename__ = "ledger_entry"

    workspace_id: uuid.UUID = Field(primary_key=True)
    ledger_id: uuid.UUID = Field(primary_key=True)
    idx: int = Field(primary_key=True, sa_type=SmallInteger)
    wallet_id: uuid.UUID
    amount_minor: int = Field(sa_type=BigInteger)
