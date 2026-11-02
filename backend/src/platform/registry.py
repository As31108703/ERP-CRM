"""模組登錄：各業務模組在自己的 Task 註冊快照、還原與一致性檢查。"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

# (db, workspace_id)：不成立時拋出 Problem，命令整筆回滾
Check = Callable[[Session, str], None]

MODULES = (
    "inventory",
    "sales",
    "wallets",
    "services",
    "crm",
    "projects",
    "manufacturing",
    "administration",
)
MODULE_DEPENDENCIES: dict[str, list[str]] = {
    "sales": ["inventory", "wallets"],
    "services": ["crm", "wallets"],
    "manufacturing": ["inventory", "wallets"],
}


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    # (db, workspace_id) -> {集合鍵: 資料}，供 view 與 export 使用
    snapshot: Callable[[Session, str], dict[str, Any]]
    # (db, workspace_id, {集合鍵: 資料})：匯入時插入資料
    restore: Callable[[Session, str, dict[str, Any]], None]
    # 依 SPEC_ORDER 執行的模組自身檢查
    invariants: tuple[Check, ...] = ()
    # 快照中以 id 識別的資料列位置，以點分隔（例如 "orders.lines"）；匯入時由 record_ids
    # 收集所有模組的 id，在同一個集合中檢查是否重複（B§2 id_collision）
    id_paths: tuple[str, ...] = ()


# 快照、一致性檢查與還原的固定執行順序，與模組匯入或登錄的先後無關：
# 被參照的模組在前（錢包、商品先於訂單，案件先於服務）；inventory 在 wallets 之前，
# 讓採購金額（purchase_invalid）先於流水語意（ledger_invalid）檢查，與參考系統的錯誤優先序一致
SPEC_ORDER = (
    "inventory",
    "wallets",
    "sales",
    "crm",
    "services",
    "manufacturing",
    "projects",
    "administration",
)

# 同名模組重複註冊時取代原本的設定（模組被重新匯入也不會重複）
_SPECS: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> None:
    _SPECS[spec.name] = spec


def all_specs() -> list[ModuleSpec]:
    """依 SPEC_ORDER 排序；不在清單中的模組排在最後，彼此維持登錄順序。"""
    rank = {name: i for i, name in enumerate(SPEC_ORDER)}
    specs = list(_SPECS.values())
    return sorted(specs, key=lambda s: rank.get(s.name, len(SPEC_ORDER)))


# 所有模組的 invariants 都通過之後才執行的整體檢查，依 FINAL_ORDER 執行（與登錄先後無關）：
# 預留量是跨模組加總（訂單、工單），要等各模組先確認自己的資料成立，竄改工單 BOM 複本才會回
# production_invalid 而不是 reservation_invalid；工作區大小（workspace_limit）在最後，
# 與參考系統 validateWorld 的錯誤優先序一致
FINAL_ORDER = ("reservations", "workspace_limit")

_FINALS: dict[str, Check] = {}


def register_final(name: str, check: Check) -> None:
    """登錄最終檢查；同名重複登錄時取代原本的設定。"""
    _FINALS[name] = check


def final_invariants() -> list[Check]:
    """依 FINAL_ORDER 排序；不在清單中的檢查排在最後，彼此維持登錄順序。"""
    rank = {name: i for i, name in enumerate(FINAL_ORDER)}
    names = sorted(_FINALS, key=lambda n: rank.get(n, len(FINAL_ORDER)))
    return [_FINALS[n] for n in names]


def _children(nodes: Iterable[Any], key: str) -> Iterator[Any]:
    for node in nodes:
        child = node.get(key) if isinstance(node, dict) else None
        if isinstance(child, list):
            yield from child
        elif isinstance(child, dict):
            yield child


def ids_at(collections: dict[str, Any], path: str) -> Iterator[Any]:
    """`path` 指到的每一筆資料列的 id；鍵不存在或型別不符時略過（結構錯誤由各模組檢查）。"""
    nodes: list[Any] = [collections]
    for key in path.split("."):
        nodes = list(_children(nodes, key))
    for node in nodes:
        if isinstance(node, dict) and "id" in node:
            yield node["id"]


def record_ids(collections: dict[str, Any]) -> Iterator[Any]:
    """依 SPEC_ORDER 收集所有模組宣告（ModuleSpec.id_paths）的資料列 id。"""
    for spec in all_specs():
        for path in spec.id_paths:
            yield from ids_at(collections, path)
