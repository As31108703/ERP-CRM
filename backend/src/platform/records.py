"""業務命令共用工具：B§3.1 通用前置檢查、路徑參數合併、識別碼解析與集合筆數上限。

每個模組的 `HANDLERS[action]` 都以 `command(action, fn)` 包裝，讓 HTTP 路由與教學執行
（直接呼叫 HANDLERS）走同一套檢查。模組閘（B§3.1 第 3 步）由命令管線的 `module=` 負責，
因此「禁用鍵名＋模組未啟用」同時成立時，這裡回的是 403 module_disabled。
"""

import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlmodel import Session, SQLModel

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.crm.entity import CrmRecordRow
from src.platform.context import CommandContext

Handler = Callable[[CommandContext, dict[str, Any]], str | None]

RECORD_LIMIT = 500
LINES_MAX = 50
# JavaScript Number.MAX_SAFE_INTEGER：金額相乘超過這個值時回 simulation_amount_overflow
MAX_SAFE_INTEGER = 2**53 - 1

FINANCE_KEY_RE = re.compile(r"(bank|payer|finance|legal|payment_url)", re.IGNORECASE)
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
        not any(FINANCE_KEY_RE.search(k) for k in p),
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


def scoped_get[T: SQLModel](
    db: Session,
    model: type[T],
    workspace_id: str | uuid.UUID,
    record_id: object,
    *,
    lock: bool = False,
) -> T | None:
    """以工作區範圍的主鍵 (workspace_id, id) 取得資料列；id 格式不符或不存在時回 None。

    業務資料的 id 只在工作區內唯一（同一份備份可匯入多個工作區），所以一律帶著工作區查詢，
    其他工作區的同 id 資料視為不存在，不會跨工作區讀到或洩漏。"""
    parsed = parse_id(record_id)
    if parsed is None:
        return None
    ws = workspace_id if isinstance(workspace_id, uuid.UUID) else uuid.UUID(workspace_id)
    return db.get(model, {"workspace_id": ws, "id": parsed}, with_for_update=lock or None)


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


# --- 通用紀錄（B§3.2）：customers、contacts、deals、cases、tasks、milestones ---------------

RECORD_COLLECTIONS = ("customers", "contacts", "deals", "cases", "tasks", "milestones")
RECORD_FIELDS = (
    "id",
    "name",
    "title",
    "customer_id",
    "case_id",
    "status",
    "notes",
    "lost_reason",
    "due_at",
    "email",
    "phone",
    "amount_minor",
)
_TEXT_FIELDS = ("name", "title", "status", "notes", "lost_reason", "email", "phone")
_REF_FIELDS = ("customer_id", "case_id")
TEXT_LIMIT = 4000
LOST = "lost"


def js_length(s: str) -> int:
    """JavaScript 字串長度（UTF-16 碼元數），與參考系統的 `.length` 一致。"""
    return len(s.encode("utf-16-le")) // 2


def parse_loose_instant(value: object) -> datetime | None:
    """寬鬆解析日期字串（ISO 8601，可只有日期；沒有時區時視為 UTC），回傳截到毫秒的 UTC 時間；
    無法解析時回 None。截到毫秒讓儲存值與 API 輸出（毫秒精度）一致。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return parsed.replace(microsecond=parsed.microsecond // 1000 * 1000)


def crm_record_missing() -> Problem:
    return Problem(404, "record_missing", "找不到工作區紀錄")


def _fields_invalid() -> Problem:
    return Problem(422, "fields_invalid", "欄位不符")


def find_record(ctx: CommandContext, collection: str, record_id: object) -> CrmRecordRow:
    """工作區內指定集合的紀錄；不存在（或屬於其他集合）時 404 record_missing。"""
    row = scoped_get(ctx.db, CrmRecordRow, ctx.workspace_id, record_id)
    if row is None or row.collection != collection:
        raise crm_record_missing()
    return row


def _check_record_payload(p: dict[str, Any]) -> None:
    ensure(all(k in RECORD_FIELDS for k in p), 422, "fields_invalid", "欄位不符")
    text = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    ensure(js_length(text) <= TEXT_LIMIT, 422, "text_limit", "文字過長")
    if p.get("status") == LOST:
        reason = p.get("lost_reason")
        ensure(
            isinstance(reason, str) and reason.strip() != "",
            422,
            "lost_reason_required",
            "請填失單原因",
        )


def _apply(row: CrmRecordRow, p: dict[str, Any]) -> None:
    """把 payload 合併進紀錄；id 不採用。參照是否存在由一致性檢查負責（404 record_missing）。"""
    for key in _TEXT_FIELDS:
        if key in p:
            value = p[key]
            if value is not None and not isinstance(value, str):
                raise _fields_invalid()
            setattr(row, key, value)
    for key in _REF_FIELDS:
        if key in p:
            value = p[key]
            if value is None or value == "":
                setattr(row, key, None)
                continue
            if not isinstance(value, str):
                raise _fields_invalid()
            parsed = parse_id(value)
            if parsed is None:
                # 不是 UUID 的參照不可能指向任何紀錄
                raise crm_record_missing()
            setattr(row, key, parsed)
    if "due_at" in p:
        due = p["due_at"]
        if due is None:
            row.due_at = None
        else:
            parsed_due = parse_loose_instant(due)
            if parsed_due is None:
                raise _fields_invalid()
            row.due_at = parsed_due
    if "amount_minor" in p:
        # precheck 已檢查並正規化（5.0 → 5）；這裡再檢查一次，直接呼叫時也不會存入非整數
        row.amount_minor = check_int(p["amount_minor"], min_=1)


def _check_collection(collection: str) -> None:
    if collection not in RECORD_COLLECTIONS:
        raise ValueError(f"未知的通用紀錄集合：{collection}")


def generic_create(ctx: CommandContext, collection: str, payload: dict[str, Any]) -> str:
    """`<x>.create`：檢查欄位、長度與失單原因後新增紀錄；payload 的 id 不採用，回傳新 id。"""
    _check_collection(collection)
    _check_record_payload(payload)
    row = CrmRecordRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        collection=collection,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    _apply(row, payload)
    ctx.db.add(row)
    ctx.db.flush()
    return str(row.id)


def generic_update(ctx: CommandContext, collection: str, payload: dict[str, Any]) -> str:
    """`<x>.update {id, ...}`：找不到 404 record_missing；合併欄位並更新 updated_at。"""
    _check_collection(collection)
    _check_record_payload(payload)
    row = find_record(ctx, collection, payload.get("id"))
    _apply(row, payload)
    row.updated_at = ctx.now
    ctx.db.flush()
    return str(row.id)
