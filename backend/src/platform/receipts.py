"""冪等收據：Idempotency-Key 綁定 `{path, body, expected}` 的摘要，重送時回傳原結果。"""

import uuid
from datetime import datetime
from typing import Literal, TypedDict

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, delete, func, insert, select
from sqlmodel import Field, Session, SQLModel

from src.core import clock

RECEIPT_CAP = 500
PRUNE_KEEP = 100


class ReceiptRow(SQLModel, table=True):
    __tablename__ = "receipt"

    session_id: uuid.UUID = Field(primary_key=True)
    key: str = Field(primary_key=True)
    hash: str
    expected_version: int
    version: int
    action: str
    result: str | None = None
    created_at: datetime = Field(
        default_factory=lambda: clock.utcnow(),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # 由資料庫的 bigserial 產生，保留寫入順序；寫入時不帶這個欄位（見 record）
    seq: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, server_default=FetchedValue(), nullable=False),
    )


class ReceiptOut(TypedDict):
    id: str
    hash: str
    expected_version: int
    version: int
    action: str
    result: str | None
    created_at: str
    simulation: Literal[True]


def to_out(row: ReceiptRow) -> ReceiptOut:
    return {
        "id": row.key,
        "hash": row.hash,
        "expected_version": row.expected_version,
        "version": row.version,
        "action": row.action,
        "result": row.result,
        "created_at": clock.iso(row.created_at),
        "simulation": True,
    }


def find(db: Session, session_id: uuid.UUID, key: str) -> ReceiptRow | None:
    return db.get(ReceiptRow, (session_id, key))


def record(db: Session, row: ReceiptRow) -> None:
    """寫入收據；seq 交給資料庫產生。"""
    values = row.model_dump(exclude={"seq"})
    db.execute(insert(ReceiptRow.__table__).values(**values))


def count(db: Session, session_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ReceiptRow).where(ReceiptRow.session_id == session_id)
    return db.execute(stmt).scalar_one()


def prune(db: Session, session_id: uuid.UUID, keep: int = PRUNE_KEEP) -> None:
    """只保留最近 `keep` 筆收據（依寫入順序）。"""
    seq = ReceiptRow.__table__.c.seq
    recent = select(seq).where(ReceiptRow.session_id == session_id).order_by(seq.desc()).limit(keep)
    db.execute(
        delete(ReceiptRow)
        .where(ReceiptRow.session_id == session_id)
        .where(seq.not_in(recent))
        .execution_options(synchronize_session=False)
    )
