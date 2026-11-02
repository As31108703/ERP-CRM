"""工作區：建立（含自動建立）、清除、快照與檢視。"""

import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, select

from src.core import clock
from src.core.ids import new_id, token_hex
from src.core.problem import Problem, ensure
from src.modules.catalog.seed import seed_workspace
from src.modules.catalog.templates import get_template, resolve_modules
from src.modules.reports.service import build_report
from src.modules.workspace.retention import RETENTION_HOURS
from src.platform import registry
from src.platform.context import CommandContext, HistoryRow, WorkspaceRow, WorkspaceSessionRow

SCHEMA_VERSION = 1
NAME_MAX = 100
# B§2：工作區序列化後最多 1,000,000 個字元（JavaScript 字串長度，即 UTF-16 code unit 數）
WORKSPACE_LIMIT = 1_000_000


def _company_name(value: object) -> str:
    name = value.strip() if isinstance(value, str) else ""
    ensure(0 < len(name) <= NAME_MAX, 422, "name_invalid", "請填店名")
    return name


def create_workspace(
    ctx: CommandContext, industry: object, company_name: object, modules: object
) -> WorkspaceRow:
    """依 B§3.0 檢查並建立工作區與示範資料；檢查順序為範本、名稱、模組。"""
    template = get_template(industry)
    name = _company_name(company_name)
    selected = resolve_modules(template.id, modules)  # type: ignore[arg-type]
    workspace = WorkspaceRow(
        session_id=ctx.session_row.id,
        generation_id=new_id(),
        industry=template.id,
        company_name=name,
        modules=selected,
        template_version=template.version,
        schema_version=SCHEMA_VERSION,
        created_at=ctx.now,
    )
    ctx.db.add(workspace)
    ctx.db.flush()
    ctx.workspace = workspace
    seed_workspace(ctx, template)
    return workspace


def setup(ctx: CommandContext, payload: dict[str, Any]) -> str | None:
    ensure(ctx.workspace is None, 409, "workspace_exists", "工作區已存在，請先備份及清除")
    workspace = create_workspace(
        ctx, payload.get("industry"), payload.get("company_name"), payload.get("modules")
    )
    return workspace.generation_id


def clear(ctx: CommandContext, _payload: dict[str, Any]) -> str | None:
    """刪除工作區（資料表以外鍵串聯刪除）並輪換 csrf。沒有工作區時也會輪換。"""
    ctx.db.execute(
        delete(WorkspaceRow)
        .where(WorkspaceRow.session_id == ctx.session_row.id)
        .execution_options(synchronize_session=False)
    )
    ctx.workspace = None
    ctx.session_row.csrf = token_hex(32)
    return None


def _history(db: Session, workspace_id: Any) -> list[dict[str, Any]]:
    stmt = (
        select(HistoryRow)
        .where(HistoryRow.workspace_id == workspace_id)
        .order_by(HistoryRow.version, HistoryRow.created_at)
    )
    return [
        {
            "id": str(h.id),
            "action": h.action,
            "result": h.result,
            "created_at": clock.iso(h.created_at),
            "version": h.version,
        }
        for h in db.exec(stmt)
    ]


def snapshot(db: Session, workspace: WorkspaceRow, version: int) -> dict[str, Any]:
    """工作區快照：meta 加上各模組 `ModuleSpec.snapshot` 的集合，以及依版本排序的 history。"""
    out: dict[str, Any] = {
        "generation_id": workspace.generation_id,
        "version": version,
        "industry": workspace.industry,
        "company_name": workspace.company_name,
        "modules": list(workspace.modules),
        "template_version": workspace.template_version,
        "schema_version": workspace.schema_version,
        "currency": "SIM",
        "simulation": True,
        "real_finance": False,
    }
    workspace_id = str(workspace.id)
    for spec in registry.all_specs():
        out.update(spec.snapshot(db, workspace_id))
    out["history"] = _history(db, workspace.id)
    return out


def serialized_length(world: dict[str, Any]) -> int:
    """與 HTTP 回應相同的緊湊 JSON（不跳脫非 ASCII 字元）的 UTF-16 code unit 數，
    對應參考系統 `JSON.stringify(w).length`：BMP 外的字元（例如 emoji）算 2 個字元。"""
    text = json.dumps(world, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return len(text.encode("utf-16-le")) // 2


def check_workspace_limit(db: Session, workspace_id: str) -> None:
    """最終檢查：命令或匯入完成後的工作區快照（含新版本號與 history）不得超過
    WORKSPACE_LIMIT 個字元，否則 422 workspace_limit。

    一個 UTF-16 code unit 在 UTF-8 最多 3 bytes，因此合法工作區匯出的備份
    （同一份快照加上固定的外層欄位）一定小於 3 MiB 匯入上限，可以完整還原。"""
    workspace = db.get(WorkspaceRow, uuid.UUID(workspace_id))
    session_row = None if workspace is None else db.get(WorkspaceSessionRow, workspace.session_id)
    if workspace is None or session_row is None:
        raise Problem(409, "workspace_missing", "請先建立工作區")
    world = snapshot(db, workspace, session_row.version)
    ensure(
        serialized_length(world) <= WORKSPACE_LIMIT,
        422,
        "workspace_limit",
        "工作區超出容量",
    )


def view(ctx: CommandContext) -> dict[str, Any]:
    row = ctx.session_row
    public_demo = ctx.settings.app.public_demo
    workspace = None
    report = None
    if ctx.workspace is not None:
        workspace = snapshot(ctx.db, ctx.workspace, row.version)
        report = build_report(ctx.db, ctx.workspace_id)
    expires_at = None
    if public_demo:
        expires_at = clock.iso(row.last_seen_at + timedelta(hours=RETENTION_HOURS))
    return {
        "workspace": workspace,
        "csrf": row.csrf,
        "version": row.version,
        "retention_hours": RETENTION_HOURS if public_demo else None,
        "expires_at": expires_at,
        # 與 GET /api/v1/reports 同一份計算；沒有工作區時為 null
        "report": report,
    }


def should_auto_setup(ctx: CommandContext) -> bool:
    """只有私人模式開啟 auto_setup、且 session 從未有過任何寫入（版本 0、無工作區）時自動建立。"""
    app = ctx.settings.app
    return (
        app.auto_setup
        and not app.public_demo
        and ctx.workspace is None
        and ctx.session_row.version == 0
    )


def auto_setup(ctx: CommandContext) -> None:
    """以部署預設值建立工作區，版本設為 1。不寫收據與 history；交易由呼叫端負責。"""
    app = ctx.settings.app
    create_workspace(ctx, app.default_industry, app.default_company, app.default_modules)
    ctx.session_row.version = 1
