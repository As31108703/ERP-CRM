"""平台資料列與命令執行時的 context。"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ARRAY, Column, DateTime, Text
from sqlmodel import Field, Session, SQLModel

from src.config.settings import Settings
from src.core import clock


def _tz() -> Column:  # type: ignore[type-arg]
    return Column(DateTime(timezone=True), nullable=False)


def _now() -> datetime:
    # 透過模組屬性呼叫，測試以 monkeypatch 改 clock.utcnow 時一併生效
    return clock.utcnow()


class WorkspaceSessionRow(SQLModel, table=True):
    """一個瀏覽器的 session：cookie 權杖的 sha256、csrf、版本號與速率視窗。"""

    __tablename__ = "workspace_session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    token_hash: str
    csrf: str
    version: int = 0
    last_seen_at: datetime = Field(default_factory=_now, sa_column=_tz())
    rate_start: datetime = Field(default_factory=_now, sa_column=_tz())
    rate_count: int = 0
    created_at: datetime = Field(default_factory=_now, sa_column=_tz())


class WorkspaceRow(SQLModel, table=True):
    __tablename__ = "workspace"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID
    generation_id: str
    industry: str
    company_name: str
    modules: list[str] = Field(sa_column=Column(ARRAY(Text), nullable=False))
    template_version: int
    schema_version: int = 1
    created_at: datetime = Field(default_factory=_now, sa_column=_tz())


class HistoryRow(SQLModel, table=True):
    __tablename__ = "history"

    workspace_id: uuid.UUID = Field(primary_key=True)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    action: str
    result: str | None = None
    version: int
    created_at: datetime = Field(default_factory=_now, sa_column=_tz())


@dataclass
class CommandContext:
    db: Session
    session_row: WorkspaceSessionRow
    workspace: WorkspaceRow | None
    now: datetime
    settings: Settings

    @property
    def workspace_id(self) -> str:
        """目前工作區的 id 字串；沒有工作區時拋出 RuntimeError（應先以 needs_workspace 擋下）。"""
        if self.workspace is None:
            raise RuntimeError("此命令需要工作區")
        return str(self.workspace.id)
