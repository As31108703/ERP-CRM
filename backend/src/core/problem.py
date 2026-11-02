"""業務錯誤：以 Problem 拋出，由錯誤處理器轉成統一的錯誤格式。"""


class Problem(Exception):
    def __init__(
        self, status: int, code: str, message: str, retry_after_ms: int | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after_ms = retry_after_ms


def ensure(cond: bool, status: int, code: str, message: str) -> None:
    """條件不成立時拋出 Problem。"""
    if not cond:
        raise Problem(status, code, message)
