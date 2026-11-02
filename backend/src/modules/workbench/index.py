"""工作台的紀錄索引與全站搜尋（F§2 Record kinds、Index and search）。

資料來源是工作區快照（各模組 `ModuleSpec.snapshot` 的輸出），這裡只做唯讀的衍生計算。
索引只涵蓋已啟用模組的 13 種業務紀錄；行政資料不在索引內，也不能作為釘選目標。
"""

import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.core import clock
from src.modules.administration.views import format_sim

Row = Mapping[str, Any]

# 紀錄種類 → (快照集合, 顯示名稱)，順序即索引順序
KINDS: dict[str, tuple[str, str]] = {
    "customer": ("customers", "客戶"),
    "deal": ("deals", "商機"),
    "contact": ("contacts", "聯絡人"),
    "case": ("cases", "案件"),
    "quote": ("quotes", "報價"),
    "product": ("products", "商品"),
    "wallet": ("wallets", "錢包"),
    "order": ("orders", "訂單"),
    "service": ("services", "服務"),
    "bom": ("boms", "BOM"),
    "workOrder": ("work_orders", "工單"),
    "task": ("tasks", "任務"),
    "milestone": ("milestones", "里程碑"),
}

_MODULE_OF: dict[str, str] = {
    "customer": "crm",
    "deal": "crm",
    "contact": "crm",
    "case": "crm",
    "product": "inventory",
    "wallet": "wallets",
    "order": "sales",
    "service": "services",
    "bom": "manufacturing",
    "workOrder": "manufacturing",
    "task": "projects",
    "milestone": "projects",
}

# 狀態顯示文字，與前端 STATUS_LABELS 相同語意；未列出的狀態原樣顯示
STATUS_LABELS: dict[str, str] = {
    "pending": "待付款",
    "partially_paid": "部分付款",
    "paid": "已付清",
    "partially_shipped": "部分出貨",
    "shipped": "已出貨",
    "partially_returned": "部分退貨",
    "returned": "已退貨",
    "cancelled": "已取消",
    "draft": "草稿",
    "issued": "已發出",
    "superseded": "已被新版取代",
    "simulated_confirmed": "已模擬確認",
    "confirmed": "已確認",
    "submitted": "待驗收",
    "changes_requested": "需補件",
    "accepted": "已驗收",
    "new": "待聯繫",
    "open": "進行中",
    "won": "成交",
    "lost": "未成交",
    "planned": "計畫中",
    "todo": "待辦",
    "in_progress": "進行中",
    "done": "完成",
    "closed": "已結案",
    "reserved": "已備料",
    "started": "製作中",
    "completed": "已完工",
}

# 搜尋比對的欄位（F§2）：標題、描述之外，再加上紀錄本身的這些文字欄位
_SEARCH_FIELDS = ("name", "title", "sku", "notes", "email", "phone", "lost_reason")
_SPACES = re.compile(r"\s+")

QUERY_MAX = 120


def normalize(text: str) -> str:
    """NFKC → 小寫 → 連續空白折疊成一個並去頭尾。"""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text).lower()).strip()


def money(minor: Any) -> str:
    return format_sim(minor if isinstance(minor, int) else 0)


def taipei_time(value: Any) -> str:
    """ISO 時間轉成台北時間 `YYYY-MM-DD HH:MM`；無法解析時原樣回傳。"""
    instant = parse_time(value)
    if instant is None:
        return str(value)
    return instant.astimezone(clock.TAIPEI).strftime("%Y-%m-%d %H:%M")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def num(row: Row | None, key: str) -> int:
    value = row.get(key) if row is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def text(row: Row | None, key: str) -> str | None:
    value = row.get(key) if row is not None else None
    return value if isinstance(value, str) else None


@dataclass
class World:
    """一份工作區快照加上依 id 的查找表。"""

    data: Mapping[str, Any]
    modules: list[str] = field(init=False)
    _by_id: dict[str, dict[str, Row]] = field(init=False)

    def __post_init__(self) -> None:
        self.modules = list(self.data.get("modules") or [])
        self._by_id = {
            kind: {r["id"]: r for r in self.rows(kind) if isinstance(r.get("id"), str)}
            for kind in KINDS
        }

    def has(self, module: str) -> bool:
        return module in self.modules

    def collection(self, key: str) -> list[Row]:
        value = self.data.get(key)
        return [r for r in value if isinstance(r, Mapping)] if isinstance(value, list) else []

    def rows(self, kind: str) -> list[Row]:
        return self.collection(KINDS[kind][0])

    def find(self, kind: str, row_id: Any) -> Row | None:
        return self._by_id[kind].get(row_id) if isinstance(row_id, str) else None

    def administration(self, key: str) -> list[Row]:
        office = self.data.get("administration")
        value = office.get(key) if isinstance(office, Mapping) else None
        return [r for r in value if isinstance(r, Mapping)] if isinstance(value, list) else []

    def module_for(self, kind: str) -> str:
        if kind == "quote":
            return "services" if self.has("services") else "crm"
        return _MODULE_OF[kind]

    def target(self, kind: str, row_id: str) -> dict[str, str]:
        return {"module": self.module_for(kind), "kind": kind, "id": row_id}

    def valid(self, target: Mapping[str, Any]) -> bool:
        """F§2 validTarget：種類已知、模組相符且啟用、紀錄存在。"""
        kind = target.get("kind")
        return (
            kind in KINDS
            and target.get("module") == self.module_for(kind)
            and self.has(target["module"])
            and self.find(kind, target.get("id")) is not None
        )


def label(kind: str) -> str:
    return KINDS[kind][1]


def title(kind: str, row: Row) -> str:
    """name → title → sku → 「種類 id 前 8 碼」。"""
    for key in ("name", "title", "sku"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return f"{label(kind)} {str(row.get('id', ''))[:8]}"


def _relations(w: World, kind: str, row: Row) -> list[str]:
    out: list[str] = []

    def add(k: str, row_id: Any) -> None:
        other = w.find(k, row_id)
        if other is not None:
            out.append(title(k, other))
            sku = text(other, "sku")
            if sku is not None:
                out.append(sku)

    if kind in ("contact", "deal", "case", "task", "milestone") and row.get("customer_id"):
        add("customer", row.get("customer_id"))
    if kind in ("quote", "service", "task", "milestone") and row.get("case_id"):
        add("case", row.get("case_id"))
        case = w.find("case", row.get("case_id"))
        if case is not None and case.get("customer_id"):
            add("customer", case.get("customer_id"))
    if kind == "order":
        add("wallet", row.get("buyer_wallet_id"))
        for line in row.get("lines") or []:
            add("product", line.get("product_id"))
            if isinstance(line.get("name"), str) and line["name"]:
                out.append(line["name"])
    if kind in ("bom", "workOrder"):
        bom = row if kind == "bom" else row.get("bom_snapshot")
        if isinstance(bom, Mapping):
            add("product", bom.get("product_id"))
            for component in bom.get("components") or []:
                add("product", component.get("product_id"))
        if kind == "workOrder":
            current = w.find("bom", row.get("bom_id"))
            if current is not None:
                out.append(f"BOM 第 {current.get('revision')} 版")
    return list(dict.fromkeys(out))


@dataclass(frozen=True)
class Record:
    module: str
    kind: str
    id: str
    title: str
    description: str
    status_label: str | None
    search_text: str
    row: Row

    def target(self) -> dict[str, str]:
        return {"module": self.module, "kind": self.kind, "id": self.id}

    def item(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status_label": self.status_label,
        }


def index(w: World) -> Iterator[Record]:
    """依種類順序與集合順序列出已啟用模組的紀錄。"""
    for kind in KINDS:
        module = w.module_for(kind)
        if not w.has(module):
            continue
        for row in w.rows(kind):
            row_id = row.get("id")
            if not isinstance(row_id, str):
                continue
            status = text(row, "status") or None
            if status is None and kind == "product":
                status = "啟用中" if row.get("active") else "停用中"
            shown = status_label(status) if status else None
            name = title(kind, row)
            description = " · ".join(
                part for part in (label(kind), shown, *_relations(w, kind, row)) if part
            )
            fields = [text(row, key) or "" for key in _SEARCH_FIELDS]
            yield Record(
                module=module,
                kind=kind,
                id=row_id,
                title=name,
                description=description,
                status_label=shown,
                search_text=normalize(" ".join([name, description, *fields])),
                row=row,
            )


def search(w: World, query: str, offset: int, limit: int) -> dict[str, Any]:
    """每個以空白分隔的詞都要是 searchText 的子字串；空查詢沒有結果。"""
    tokens = normalize(query).split(" ")
    tokens = [t for t in tokens if t]
    if not tokens:
        return {"total": 0, "items": []}
    hits = [r for r in index(w) if all(t in r.search_text for t in tokens)]
    return {"total": len(hits), "items": [r.item() for r in hits[offset : offset + limit]]}
