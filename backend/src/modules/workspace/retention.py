"""公開展示模式的保留：72 小時無存取的 session 連同工作區、收據與業務資料整筆刪除。"""

from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger
from sqlalchemy import Connection, Engine, delete, text
from sqlmodel import Session

from src.core import clock
from src.platform.context import WorkspaceSessionRow

RETENTION_HOURS = 72
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


def run_purge(engine: Engine, now: datetime | None = None) -> int:
    """排程工作：取得 advisory lock 後清除過期 session；鎖被其他實例持有時跳過並回 0。"""
    with engine.connect() as conn:
        locked = conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": ADVISORY_LOCK_ID})
        if not locked.scalar_one():
            conn.rollback()
            return 0
        conn.commit()
        try:
            count = purge_expired(conn, now or clock.utcnow())
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": ADVISORY_LOCK_ID})
            conn.commit()
    if count:
        logger.info("已清除 {} 個逾期工作區", count)
    return count


def _job(engine: Engine) -> None:
    try:
        run_purge(engine)
    except Exception:
        # 排程執行緒的例外不能讓排程停止，下一輪再試
        logger.exception("清除逾期工作區失敗")


def start_scheduler(engine: Engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _job,
        "interval",
        args=[engine],
        id=JOB_ID,
        minutes=int(PURGE_INTERVAL.total_seconds() // 60),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
