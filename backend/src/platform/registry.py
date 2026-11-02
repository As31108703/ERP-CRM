"""模組登錄：各業務模組在自己的 Task 註冊快照、還原與一致性檢查。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

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
    # (db, workspace_id)：不成立時拋出 Problem，命令整筆回滾
    invariants: tuple[Callable[[Session, str], None], ...] = ()


# 依註冊順序保存；同名模組重複註冊時取代原本的設定（模組被重新匯入也不會重複）
_SPECS: dict[str, ModuleSpec] = {}


def register(spec: ModuleSpec) -> None:
    _SPECS[spec.name] = spec


def all_specs() -> list[ModuleSpec]:
    return list(_SPECS.values())
