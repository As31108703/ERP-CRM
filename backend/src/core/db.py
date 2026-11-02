"""資料庫引擎與每個請求的 Session。"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import URL, Engine
from sqlmodel import Session, create_engine

from src.config.settings import Settings


def make_engine(settings: Settings) -> Engine:
    db = settings.database
    url = URL.create(
        "postgresql+psycopg",
        username=db.user,
        password=db.password or None,
        host=db.host,
        port=db.port,
        database=db.name,
    )
    # 錯誤訊息（會被記進日誌）不附 SQL 參數值，避免權杖、csrf 或使用者輸入外洩
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI 依賴：用 create_app 建立的引擎開一個 Session，請求結束時關閉。

    交易的提交與回滾由呼叫端（命令管線）負責。
    """
    with Session(request.app.state.engine) as session:
        yield session
