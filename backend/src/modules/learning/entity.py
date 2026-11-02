"""流程教學的資料列：每輪練習一列 session，每完成一步一列 checkpoint。"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


class LearningSessionRow(SQLModel, table=True):
    """一條路線的一輪練習；同一路線以最新建立（seq 最大）的一列為目前這一輪。"""

    __tablename__ = "learning_session"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    path: str
    run_id: str
    active: bool = False
    paused: bool = False
    scope: str = "lesson"
    compact: bool = False
    quiz_choice: int | None = Field(default=None, sa_type=SmallInteger)
    selected_step: str | None = None
    created_at: datetime = Field(sa_column=_tz())
    updated_at: datetime = Field(sa_column=_tz())
    seq: int | None = Field(
        default=None, sa_column=Column(BigInteger, server_default=FetchedValue(), nullable=False)
    )


class LearningCheckpointRow(SQLModel, table=True):
    """完成一步時的操作紀錄；version 與 history 相同，before／after 為本輪讀值。"""

    __tablename__ = "learning_checkpoint"

    workspace_id: uuid.UUID = Field(primary_key=True)
    session_id: uuid.UUID = Field(primary_key=True)
    step_id: str = Field(primary_key=True)
    action: str
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    result: str
    version: int = Field(sa_type=BigInteger)
    before: list[dict[str, str | None]] = Field(sa_column=Column(JSONB, nullable=False))
    after: list[dict[str, str | None]] = Field(sa_column=Column(JSONB, nullable=False))
