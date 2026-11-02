"""備份匯出與匯入。

匯出：`{"format", "format_version", "exported_at", "workspace": {meta}, "collections": {…}}`，
collections 是各模組 `ModuleSpec.snapshot` 的集合加上 history，不含 csrf、收據等 session 資料。

匯入（在命令管線的 SAVEPOINT 內執行，任何一步失敗整筆回滾、原資料完整保留）：
1. 嚴格結構檢查（422 import_invalid），以及工作區設定、識別碼與資料表外鍵參照的前置檢查；
2. 刪除現有工作區（業務資料以外鍵串聯刪除）；
3. 建立新工作區（新 generation_id），依 registry 順序執行每個模組的 restore，不論模組是否啟用；
4. 還原 history；
之後由命令管線把版本號加 1、執行 `invariants.check_all`（含最終的工作區大小檢查）。
"""

import uuid
from collections.abc import Iterator
from itertools import chain
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete
from sqlmodel import Session

from src.core import clock
from src.core.ids import token_hex
from src.core.problem import Problem, ensure
from src.modules.backup.schema import BACKUP_FORMAT, BACKUP_FORMAT_VERSION, Backup, Collections
from src.modules.catalog.templates import get_template, resolve_modules
from src.modules.wallets.entity import WALLET_KINDS
from src.modules.workspace.service import SCHEMA_VERSION, normalize_company_name, snapshot
from src.platform import registry
from src.platform.context import CommandContext, HistoryRow, WorkspaceRow

BACKUP_FILENAME = "erpcrm-sim-backup.json"
# 工作區快照中屬於 meta 的鍵；其餘鍵（各模組集合、history、administration）放在 collections
META_KEYS = (
    "generation_id",
    "version",
    "industry",
    "company_name",
    "modules",
    "template_version",
    "schema_version",
    "currency",
    "simulation",
    "real_finance",
)


# --- 匯出 -----------------------------------------------------------------------


def export(ctx: CommandContext) -> dict[str, Any]:
    world = snapshot(ctx.db, ctx.require_workspace(), ctx.session_row.version)
    return {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "exported_at": clock.iso(ctx.now),
        "workspace": {k: world[k] for k in META_KEYS},
        "collections": {k: v for k, v in world.items() if k not in META_KEYS},
    }


# --- 匯入：前置檢查 ---------------------------------------------------------------


def _invalid(message: str) -> Problem:
    return Problem(422, "import_invalid", message)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _parse(payload: dict[str, Any]) -> Backup:
    """結構檢查。錯誤訊息只帶欄位位置，不帶輸入值。"""
    # PostgreSQL 的 TEXT 與 JSONB 都不能存 NUL 字元
    if any("\x00" in s for s in _strings(payload)):
        raise _invalid("備份含有不允許的字元")
    try:
        return Backup.model_validate(payload)
    except ValidationError as exc:
        where = ".".join(str(p) for p in exc.errors()[0]["loc"])
        raise _invalid(f"備份格式不符（{where}）") from None


def _check_simulation(backup: Backup) -> None:
    meta = backup.workspace
    c = backup.collections
    ensure(
        meta.schema_version == SCHEMA_VERSION
        and meta.currency == "SIM"
        and meta.simulation is True
        and meta.real_finance is False
        and all(s.currency == "SIM" and not s.legal_confirmation for s in c.services)
        and not any(q.legal_confirmation for q in c.quotes),
        422,
        "simulation_required",
        "備份只能包含 SIM 模擬資料",
    )


def _id_key(value: Any) -> str | None:
    """比對用的識別碼：UUID 轉成標準小寫形式，其他字串以 casefold 比較（不分大小寫）；
    不是字串時略過，由各模組的結構檢查回正式錯誤碼。"""
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return value.casefold()


def _check_ids(collections: dict[str, Any]) -> None:
    """B§2：所有以 id 識別的資料列（各模組 ModuleSpec.id_paths 宣告的資料列，含訂單品項、
    跟進、交付與行政資料，加上 history）在整份備份中不分大小寫不得重複。"""
    seen: set[str] = set()
    for value in chain(registry.record_ids(collections), registry.ids_at(collections, "history")):
        key = _id_key(value)
        if key is None:
            continue
        ensure(key not in seen, 422, "id_collision", "備份中的紀錄識別重複")
        seen.add(key)


def _check_rows(c: Collections) -> None:
    """資料表層級的約束（外鍵、錢包種類）先以業務錯誤碼擋下，避免寫入時才觸發資料庫錯誤。"""
    for w in c.wallets:
        ensure(w.kind in WALLET_KINDS, 422, "wallet_invalid", "錢包不符")
    wallets = {uuid.UUID(w.id) for w in c.wallets}
    products = {uuid.UUID(p.id) for p in c.products}
    refs = [
        *((e.wallet_id, wallets) for row in c.ledger for e in row.entries),
        *((x.product_id, products) for x in c.purchases),
        *((o.buyer_wallet_id, wallets) for o in c.orders),
        *((line.product_id, products) for o in c.orders for line in o.lines),
    ]
    for ref, known in refs:
        if uuid.UUID(ref) not in known:
            raise Problem(404, "record_missing", "找不到工作區紀錄")
    for s in c.services:
        # source_snapshot.case.id 由 case_id 衍生，還原時不另外儲存
        if uuid.UUID(s.source_snapshot.case.id) != uuid.UUID(s.case_id):
            raise _invalid("服務來源案件與 case_id 不符")


# --- 匯入：寫入 -------------------------------------------------------------------


def _restore_history(db: Session, workspace_id: uuid.UUID, c: Collections) -> None:
    for h in c.history:
        db.add(
            HistoryRow(
                id=uuid.UUID(h.id),
                workspace_id=workspace_id,
                action=h.action,
                result=h.result,
                version=h.version,
                created_at=clock.parse_instant(h.created_at),
            )
        )
    db.flush()


def import_backup(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    """以備份整筆取代目前工作區，回傳新的 generation_id。"""
    backup = _parse(payload)
    meta = backup.workspace
    _check_simulation(backup)
    template = get_template(meta.industry)
    name = normalize_company_name(meta.company_name)
    modules = resolve_modules(template.id, list(meta.modules))
    _check_ids(payload["collections"])
    _check_rows(backup.collections)

    db = ctx.db
    if ctx.workspace is not None:
        db.expunge(ctx.workspace)
    db.execute(
        delete(WorkspaceRow)
        .where(WorkspaceRow.session_id == ctx.session_row.id)  # type: ignore[arg-type]
        .execution_options(synchronize_session=False)
    )
    workspace = WorkspaceRow(
        session_id=ctx.session_row.id,
        generation_id=token_hex(16),
        industry=template.id,
        company_name=name,
        modules=modules,
        template_version=meta.template_version,
        schema_version=SCHEMA_VERSION,
        created_at=ctx.now,
    )
    db.add(workspace)
    db.flush()
    ctx.workspace = workspace

    # 各模組的 restore 讀原始 dict（行政資料要分辨舊格式缺少的鍵）；不論模組是否啟用都執行，
    # 例如 tasks、milestones 由 crm 的 restore 寫入，projects 啟用而 crm 關閉時也要還原
    collections = payload["collections"]
    workspace_id = str(workspace.id)
    for spec in registry.all_specs():
        spec.restore(db, workspace_id, collections)
    _restore_history(db, workspace.id, backup.collections)
    return workspace.generation_id
