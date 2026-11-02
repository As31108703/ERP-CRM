"""session 與工作區的保留排程，兩種模式都會啟動：

- 兩種模式：從未寫入（版本 0、沒有工作區）且 24 小時沒存取的 session 刪除。
  沒帶 cookie 的 `/api/v1` 請求每次都會建立一列，不清會一直累積；
- 公開展示模式另外把 72 小時無存取的 session 連同工作區、收據與業務資料整筆刪除。
"""

from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from sqlalchemy import Connection, Engine, delete, exists, text
from sqlmodel import Session

from src.core import clock
from src.platform.context import WorkspaceRow, WorkspaceSessionRow

RETENTION_HOURS = 72
# 從未寫入的 session 只是一組 csrf，保留一天足夠讓使用者回來繼續操作
ABANDONED_HOURS = 24
PURGE_INTERVAL = timedelta(minutes=10)
# 多個實例同時啟動排程時，只讓拿到這把鎖的實例執行
ADVISORY_LOCK_ID = 7310
JOB_ID = "retention_purge"


def purge_expired(db: Session | Connection, now: datetime) -> int:
    """刪除 `last_seen_at < now - 72h` 的 session（工作區等資料以外鍵串聯刪除），回傳筆數。

    呼叫端負責提交。
    """
    cutoff = now - timedelta(hours=RETENTION_HOURS)
    result = db.execute(
        delete(WorkspaceSessionRow)
        .where(WorkspaceSessionRow.last_seen_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def purge_abandoned(db: Session | Connection, now: datetime) -> int:
    """刪除版本 0、沒有工作區且 `last_seen_at < now - 24h` 的 session，回傳筆數。呼叫端負責提交。

    請求鎖住 session 列時刪除會等待；請求若建立了工作區，版本已大於 0，重新比對後不會刪除。
    """
    cutoff = now - timedelta(hours=ABANDONED_HOURS)
    has_workspace = exists().where(WorkspaceRow.session_id == WorkspaceSessionRow.id)
    result = db.execute(
        delete(WorkspaceSessionRow)
        .where(
            WorkspaceSessionRow.version == 0,
            WorkspaceSessionRow.last_seen_at < cutoff,
            ~has_workspace,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def _purge(db: Connection, now: datetime, public_demo: bool) -> tuple[int, int]:
    abandoned = purge_abandoned(db, now)
    expired = purge_expired(db, now) if public_demo else 0
    return abandoned, expired


def run_purge(engine: Engine, now: datetime | None = None, *, public_demo: bool) -> int:
    """排程工作：取得 advisory lock 後清除從未寫入的 session，公開展示模式另清除過期 session；
    回傳刪除的 session 總數。鎖被其他實例持有時跳過並回 0。"""
    with engine.connect() as conn:
        locked = conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": ADVISORY_LOCK_ID})
        if not locked.scalar_one():
            conn.rollback()
            return 0
        conn.commit()
        try:
            abandoned, expired = _purge(conn, now or clock.utcnow(), public_demo)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": ADVISORY_LOCK_ID})
            conn.commit()
    if abandoned:
        logger.info("已清除 {} 個未使用的 session", abandoned)
    if expired:
        logger.info("已清除 {} 個逾期工作區", expired)
    return abandoned + expired


def _job(engine: Engine, *, public_demo: bool) -> None:
    try:
        run_purge(engine, public_demo=public_demo)
    except Exception:
        # 排程執行緒的例外不能讓排程停止，下一輪再試
        logger.exception("清除逾期 session 失敗")


def start_scheduler(engine: Engine, *, public_demo: bool) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _job,
        "interval",
        args=[engine],
        kwargs={"public_demo": public_demo},
        id=JOB_ID,
        minutes=int(PURGE_INTERVAL.total_seconds() // 60),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
