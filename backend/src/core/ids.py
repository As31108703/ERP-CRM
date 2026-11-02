"""識別碼與隨機權杖。"""

import secrets
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


def token_hex(n: int) -> str:
    """n 個隨機位元組，輸出 2n 個小寫十六進位字元。"""
    return secrets.token_hex(n)
