"""備份檔的嚴格結構：鍵名完全相符、型別不轉換（布林不算整數、字串不轉數字）。

只檢查形狀與欄位型別；跨資料列的規則（金額守恆、流水、參照、狀態）交給各模組的 invariants，
行政資料的內容由行政模組的 restore 自行驗證（含舊格式缺少的 changes、voided、archived）。
"""

import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from src.core import clock
from src.core.problem import Problem
from src.platform.records import MAX_SAFE_INTEGER

BACKUP_FORMAT = "erpcrm-sim-backup"
BACKUP_FORMAT_VERSION = 1
# INT 欄位（history.version、template_version）的上限
INT4_MAX = 2**31 - 1
# 以 SMALLINT 編號的巢狀陣列（訂單品項、BOM 材料、流水分錄）；實際筆數規則由 invariants 檢查
NESTED_MAX = 1000


def _uuid(value: str) -> str:
    uuid.UUID(value)
    return value


def _instant(value: str) -> str:
    try:
        clock.parse_instant(value)
    except Problem:
        raise ValueError("時間格式不符") from None
    return value


Id = Annotated[str, AfterValidator(_uuid)]
Instant = Annotated[str, AfterValidator(_instant)]
Int = Annotated[int, Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _Stamped(_Strict):
    id: Id
    created_at: Instant
    updated_at: Instant


class WorkspaceMeta(_Strict):
    generation_id: str
    version: Int
    industry: str
    company_name: str
    modules: list[str]
    template_version: Annotated[int, Field(ge=1, le=INT4_MAX)]
    schema_version: int
    currency: str
    simulation: bool
    real_finance: bool


class Lot(_Strict):
    quantity: Int
    cost_minor: Int


class Product(_Stamped):
    sku: str
    name: str
    price_minor: Int
    cost_minor: Int
    active: bool
    on_hand: Int
    reserved: Int
    stock_value_minor: Int
    lots: list[Lot]


class Purchase(_Stamped):
    product_id: Id
    name: str
    quantity: Int
    cost_minor: Int
    total_minor: Int


class Wallet(_Stamped):
    kind: str
    name: str
    balance_minor: Int


class LedgerEntry(_Strict):
    wallet_id: Id
    amount_minor: Int


class Ledger(_Strict):
    id: Id
    kind: str
    reference_id: Id
    created_at: Instant
    entries: Annotated[list[LedgerEntry], Field(max_length=NESTED_MAX)]


class ShippedCostLot(_Strict):
    quantity: Int
    cost_minor: Int
    returned: Int


class OrderLine(_Strict):
    id: Id
    product_id: Id
    name: str
    price_minor: Int
    cost_minor: Int
    quantity: Int
    shipped_quantity: Int
    returned_quantity: Int
    shipped_cost_lots: list[ShippedCostLot]


class Order(_Stamped):
    learning_run_id: str | None
    buyer_wallet_id: Id
    status: str
    total_minor: Int
    paid_minor: Int
    refunded_minor: Int
    lines: Annotated[list[OrderLine], Field(max_length=NESTED_MAX)]


class Record(_Stamped):
    """customers、contacts、cases、tasks、milestones 共用的通用紀錄。"""

    name: str | None
    title: str | None
    customer_id: Id | None
    case_id: Id | None
    status: str | None
    notes: str | None
    lost_reason: str | None
    due_at: Instant | None
    email: str | None
    phone: str | None
    amount_minor: Int | None


class Followup(_Strict):
    id: Id
    note: str
    created_at: Instant


class Deal(Record):
    followups: list[Followup]


class Quote(_Stamped):
    case_id: Id
    amount_minor: Int
    expires_at: Instant
    status: str
    digest: str | None
    issued_at: Instant | None
    legal_confirmation: bool


class SourceCase(_Strict):
    id: Id
    title: str


class SourceSnapshot(_Strict):
    case: SourceCase
    price_source: str


class Delivery(_Strict):
    id: Id
    revision: Int
    artifact_ref: str
    digest: str


class Service(_Stamped):
    case_id: Id
    title: str
    source_snapshot: SourceSnapshot
    amount_minor: Int
    currency: str
    status: str
    paid_minor: Int
    deliveries: list[Delivery]
    latest_delivery_id: Id | None
    legal_confirmation: bool


class BomComponent(_Strict):
    product_id: Id
    quantity: Int


class Bom(_Strict):
    id: Id
    product_id: Id
    components: Annotated[list[BomComponent], Field(max_length=NESTED_MAX)]
    revision: Int
    created_at: Instant


class ConsumedLot(_Strict):
    product_id: Id
    quantity: Int
    cost_minor: Int


class WorkOrder(_Stamped):
    learning_run_id: str | None
    bom_id: Id
    # 須與 BOM 的快照形式完全相同，由製造模組的 invariants 比對
    bom_snapshot: dict[str, Any]
    quantity: Int
    status: str
    actual_cost_minor: Int | None
    consumed_material_lots: list[ConsumedLot]


class History(_Strict):
    id: Id
    action: str
    result: str | None
    created_at: Instant
    version: Annotated[int, Field(ge=0, le=INT4_MAX)]


class Collections(_Strict):
    products: list[Product]
    purchases: list[Purchase]
    wallets: list[Wallet]
    ledger: list[Ledger]
    orders: list[Order]
    customers: list[Record]
    contacts: list[Record]
    deals: list[Deal]
    cases: list[Record]
    quotes: list[Quote]
    services: list[Service]
    boms: list[Bom]
    work_orders: list[WorkOrder]
    tasks: list[Record]
    milestones: list[Record]
    history: list[History]
    # 只在啟用行政模組時出現；內容由行政模組的 restore 驗證（含舊格式預設值）
    administration: dict[str, Any] = None  # type: ignore[assignment]


class Backup(_Strict):
    format: Literal["erpcrm-sim-backup"]
    # 嚴格整數 1（Literal 會接受 true 與 1.0）
    format_version: Annotated[int, Field(ge=BACKUP_FORMAT_VERSION, le=BACKUP_FORMAT_VERSION)]
    exported_at: Instant
    workspace: WorkspaceMeta
    collections: Collections
