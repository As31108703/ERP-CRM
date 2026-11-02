"""整數檢查：金額與數量一律是整數最小單位，上限 1_000_000_000。"""

from typing import Any

from src.core.problem import Problem

INT_MAX = 1_000_000_000


def check_int(
    n: Any,
    *,
    min_: int = 0,
    code: str = "number_invalid",
    message: str = "數量或金額必須是範圍內整數",
) -> int:
    """n 必須是 min_ ≤ n ≤ 1e9 的整數；JSON 的 5.0 視同 5，布林值不算整數。"""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int) or not (min_ <= n <= INT_MAX):
        raise Problem(422, code, message)
    return n


def format_sim(minor: int) -> str:
    """`1,234.50 SIM`（100 minor = 1 SIM）；負數前面加負號。"""
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    return f"{sign}{whole:,}.{cents:02d} SIM"
