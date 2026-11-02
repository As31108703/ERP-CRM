"""業務命令共用工具：B§3.1 通用前置檢查、路徑參數合併、識別碼解析與集合筆數上限。

每個模組的 `HANDLERS[action]` 都以 `command(action, fn)` 包裝，讓 HTTP 路由與教學執行
（直接呼叫 HANDLERS）走同一套檢查。模組閘（B§3.1 第 3 步）由命令管線的 `module=` 負責，
因此「禁用鍵名＋模組未啟用」同時成立時，這裡回的是 403 module_disabled。
"""

import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlmodel import Session

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.platform.context import CommandContext

Handler = Callable[[CommandContext, dict[str, Any]], str | None]

RECORD_LIMIT = 500
LINES_MAX = 50
# JavaScript Number.MAX_SAFE_INTEGER：金額相乘超過這個值時回 simulation_amount_overflow
MAX_SAFE_INTEGER = 2**53 - 1

_FORBIDDEN_KEY = re.compile(r"(bank|payer|finance|legal|payment_url)", re.IGNORECASE)
PROTECTED_KEYS = (
    "currency",
    "simulation",
    "real_finance",
    "balance_minor",
    "on_hand",
    "reserved",
    "lots",
    "stock_value_minor",
)
_LEARNING_ACTIONS = ("order.create", "workOrder.create")
LEARNING_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,80}", re.ASCII)
_PRODUCT_KEYS = frozenset({"id", "name", "sku", "price_minor", "cost_minor", "active"})
PRODUCT_NAME_MAX = 100


def _product_name_ok(name: object) -> bool:
    return isinstance(name, str) and 0 < len(name) <= PRODUCT_NAME_MAX


def precheck(action: str, payload: Any) -> dict[str, Any]:
    """依 B§3.1 的順序檢查 payload（模組閘除外），回傳整數欄位正規化（5.0 → 5）後的副本。"""
    ensure(
        isinstance(payload, dict) and all(isinstance(k, str) for k in payload),
        422,
        "payload_invalid",
        "參數不符",
    )
    p: dict[str, Any] = dict(payload)
    ensure(
        not any(_FORBIDDEN_KEY.search(k) for k in p),
        422,
        "simulation_required",
        "不允許真實金融欄位",
    )
    ensure(not any(k in p for k in PROTECTED_KEYS), 422, "protected_field", "不能覆寫系統欄位")
    if "learning_run_id" in p:
        run_id = p["learning_run_id"]
        ensure(
            action in _LEARNING_ACTIONS
            and isinstance(run_id, str)
            and LEARNING_ID_RE.fullmatch(run_id) is not None,
            422,
            "learning_id_invalid",
            "教學識別不符",
        )
    if action in ("product.create", "product.update"):
        if action == "product.create":
            ensure(
                _product_name_ok(p.get("name")) and isinstance(p.get("sku"), str),
                422,
                "product_invalid",
                "請填商品名稱及SKU",
            )
        for key in ("price_minor", "cost_minor"):
            if key in p:
                p[key] = check_int(p[key])
        ensure(set(p) <= _PRODUCT_KEYS, 422, "product_invalid", "商品欄位不符")
    if action == "wallet.create":
        ensure(
            p.get("kind") == "buyer" and isinstance(p.get("name"), str),
            422,
            "wallet_invalid",
            "只能建立買家錢包",
        )
    if action.split(".")[0] != "office":
        for key in ("quantity", "amount_minor"):
            if key in p:
                p[key] = check_int(p[key], min_=1)
    if "lines" in p and p["lines"] is not None:
        lines = p["lines"]
        ensure(
            isinstance(lines, list) and 0 < len(lines) <= LINES_MAX,
            422,
            "lines_invalid",
            "品項不符",
        )
        normalized = []
        for line in lines:
            quantity = check_int(line.get("quantity") if isinstance(line, dict) else None, min_=1)
            normalized.append({**line, "quantity": quantity})
        p["lines"] = normalized
    return p


def with_path(handler: Handler, **params: str) -> Handler:
    """把路徑參數併進 payload（覆蓋 body 中的同名鍵）再交給 handler。"""

    def wrapped(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
        merged = {**payload, **params} if isinstance(payload, dict) else payload
        return handler(ctx, merged)  # type: ignore[arg-type]

    return wrapped


def command(action: str, fn: Handler, **params: str) -> Handler:
    """業務命令 handler：（併入路徑參數後）先跑 `precheck`，再以正規化後的 payload 執行 fn。"""

    def checked(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
        return fn(ctx, precheck(action, payload))

    return with_path(checked, **params) if params else checked


def parse_id(value: object) -> uuid.UUID | None:
    """把 payload 的識別碼轉成 UUID；型別或格式不符時回 None（呼叫端回 404）。"""
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def record_missing(code: str = "simulation_record_missing") -> Problem:
    return Problem(404, code, "找不到這個模擬世界的紀錄。")


def check_record_limit(db: Session, model: Any, workspace_id: str) -> None:
    """集合（資料表）在該工作區的筆數不得超過 500，否則 422 record_limit。"""
    stmt = select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
    ensure(db.execute(stmt).scalar_one() <= RECORD_LIMIT, 422, "record_limit", "紀錄超出上限")


def check_safe(n: int) -> int:
    """相乘或累加後的金額不得超過 MAX_SAFE_INTEGER，否則 422 simulation_amount_overflow。"""
    ensure(abs(n) <= MAX_SAFE_INTEGER, 422, "simulation_amount_overflow", "模擬數值超出範圍。")
    return n
