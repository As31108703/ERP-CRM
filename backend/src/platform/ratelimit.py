"""每個工作區（session）每 60 秒最多 120 個請求，GET 也計入。"""

from datetime import datetime, timedelta

from src.core.problem import Problem
from src.platform.context import WorkspaceSessionRow

WINDOW = timedelta(milliseconds=60_000)
LIMIT = 120
# retry_after_ms = start + 60001ms - now，限制在 1..60001
_RETRY_BASE = timedelta(milliseconds=60_001)
_RETRY_MAX = 60_001


def _ms(delta: timedelta) -> int:
    return delta // timedelta(milliseconds=1)


def hit(session_row: WorkspaceSessionRow, now: datetime) -> None:
    """記一次請求；超過上限拋 429 rate_limit。呼叫端須持有該列的鎖並負責提交。

    超過上限的請求不計數，也不更新最後存取時間。
    """
    if now - session_row.rate_start >= WINDOW:
        session_row.rate_start = now
        session_row.rate_count = 0
    if session_row.rate_count >= LIMIT:
        # 視窗起點理論上不晚於 now；萬一晚於（時鐘回撥等），也不回超過一個視窗的等待時間
        retry = min(_RETRY_MAX, max(1, _ms(session_row.rate_start + _RETRY_BASE - now)))
        raise Problem(429, "rate_limit", "操作較密集，請稍候接續原工作", retry)
    session_row.rate_count += 1
    session_row.last_seen_at = now
