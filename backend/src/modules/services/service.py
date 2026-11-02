"""服務交付（B§3.7）：由案件建立草稿、確認、版本化交付、驗收或要求修改、驗收後分次付款。

交付摘要為 `digest({service_id, revision, artifact_ref})`，驗收／要求修改時必須帶最新版本的
交付 id 與摘要。付款透過 wallets 的 `move`，流水 kind 為 `service.pay`（買家 → 商家），
reference_id 指向服務。
"""

import uuid
from typing import Any

from sqlmodel import Session, select

from src.core.canonical import digest
from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.catalog.templates import Template
from src.modules.crm.entity import CrmRecordRow
from src.modules.crm.service import list_records
from src.modules.services.entity import ServiceDeliveryRow, ServiceRow
from src.modules.wallets import service as wallets
from src.modules.wallets.service import LedgerView, ledger_invalid, register_ledger_rule
from src.platform.context import CommandContext
from src.platform.records import find_record, parse_id, record_missing

DRAFT = "draft"
CONFIRMED = "confirmed"
SUBMITTED = "submitted"
CHANGES_REQUESTED = "changes_requested"
ACCEPTED = "accepted"
STATUSES = (DRAFT, CONFIRMED, SUBMITTED, CHANGES_REQUESTED, ACCEPTED)
DELIVERABLE = (CONFIRMED, SUBMITTED, CHANGES_REQUESTED, ACCEPTED)
EXPLICIT_INPUT = "explicit_simulation_input"
TEMPLATE_DEMO = "industry_template_demo"
DEFAULT_TITLE = "模擬服務"


# --- 查詢 -----------------------------------------------------------------------


def list_services(db: Session, workspace_id: str) -> list[ServiceRow]:
    stmt = (
        select(ServiceRow)
        .where(ServiceRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(ServiceRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def deliveries_of(
    db: Session, service_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ServiceDeliveryRow]]:
    """各服務的交付，依交付順序。"""
    out: dict[uuid.UUID, list[ServiceDeliveryRow]] = {sid: [] for sid in service_ids}
    if service_ids:
        stmt = (
            select(ServiceDeliveryRow)
            .where(ServiceDeliveryRow.service_id.in_(service_ids))  # type: ignore[attr-defined]
            .order_by(ServiceDeliveryRow.service_id, ServiceDeliveryRow.seq)  # type: ignore[arg-type]
        )
        for d in db.exec(stmt):
            out[d.service_id].append(d)
    return out


def delivery_digest(service_id: uuid.UUID, revision: int, artifact_ref: str) -> str:
    return digest(
        {"service_id": str(service_id), "revision": revision, "artifact_ref": artifact_ref}
    )


def get_service(ctx: CommandContext, service_id: object) -> ServiceRow:
    """工作區內的服務；不存在時 404 simulation_record_missing。"""
    parsed = parse_id(service_id)
    row = ctx.db.get(ServiceRow, parsed) if parsed is not None else None
    if row is None or str(row.workspace_id) != ctx.workspace_id:
        raise record_missing()
    return row


def _case_title(case: CrmRecordRow) -> str:
    """案件的 title，沒有時用 name，都沒有時為「模擬服務」（空字串照用）。"""
    if case.title is not None:
        return case.title
    if case.name is not None:
        return case.name
    return DEFAULT_TITLE


def _touch(ctx: CommandContext, s: ServiceRow) -> str:
    s.updated_at = ctx.now
    ctx.db.flush()
    return str(s.id)


# --- 命令 handler ---------------------------------------------------------------


def _new_service(ctx: CommandContext, case: CrmRecordRow, amount: int, price_source: str) -> str:
    title = _case_title(case)
    row = ServiceRow(
        workspace_id=uuid.UUID(ctx.workspace_id),
        case_id=case.id,
        title=title,
        source_case_title=title,
        price_source=price_source,
        amount_minor=amount,
        status=DRAFT,
        paid_minor=0,
        latest_delivery_id=None,
        legal_confirmation=False,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    ctx.db.flush()
    return str(row.id)


def create_service(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.create {case_id, amount_minor}`：案件不存在 404 record_missing；建立草稿服務，
    來源快照記下案件 id、標題與 `explicit_simulation_input`。"""
    case = find_record(ctx, "cases", p.get("case_id"))
    amount = check_int(p.get("amount_minor"), min_=1)
    return _new_service(ctx, case, amount, EXPLICIT_INPUT)


def confirm_service(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.confirm {id}`：draft → confirmed，否則 409 simulation_service_state。"""
    s = get_service(ctx, p.get("id"))
    ensure(s.status == DRAFT, 409, "simulation_service_state", "服務已模擬確認。")
    s.status = CONFIRMED
    return _touch(ctx, s)


def deliver_service(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.deliver {id, artifact_ref}`：確認後、收款前可交付新版本，狀態變 submitted。"""
    s = get_service(ctx, p.get("id"))
    ensure(s.status in DELIVERABLE, 409, "simulation_service_state", "請先模擬確認服務。")
    ensure(s.paid_minor == 0, 409, "simulation_service_paid", "已收模擬款的服務不可改交付。")
    ref = p.get("artifact_ref")
    if not isinstance(ref, str):
        raise Problem(422, "delivery_invalid", "交付摘要不符")
    revision = len(deliveries_of(ctx.db, [s.id])[s.id]) + 1
    delivery = ServiceDeliveryRow(
        service_id=s.id,
        revision=revision,
        artifact_ref=ref,
        digest=delivery_digest(s.id, revision, ref),
    )
    ctx.db.add(delivery)
    ctx.db.flush()
    s.latest_delivery_id = delivery.id
    s.status = SUBMITTED
    return _touch(ctx, s)


def _review(ctx: CommandContext, p: dict[str, Any], status: str) -> str:
    s = get_service(ctx, p.get("id"))
    delivery_id = parse_id(p.get("delivery_id"))
    delivery = next((d for d in deliveries_of(ctx.db, [s.id])[s.id] if d.id == delivery_id), None)
    if delivery is None:
        raise record_missing()
    ensure(
        s.status == SUBMITTED
        and s.latest_delivery_id == delivery.id
        and p.get("digest") == delivery.digest,
        409,
        "simulation_delivery_outdated",
        "只能處理最新交付與正確摘要。",
    )
    s.status = status
    return _touch(ctx, s)


def accept_service(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.accept {id, delivery_id, digest}`：驗收最新交付，狀態變 accepted。"""
    return _review(ctx, p, ACCEPTED)


def request_changes(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.request_changes {id, delivery_id, digest}`：最新交付要求修改。"""
    return _review(ctx, p, CHANGES_REQUESTED)


def pay_service(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`service.pay {id, buyer_wallet_id, amount_minor}`：驗收後由買家分次付款，不得超收。"""
    s = get_service(ctx, p.get("id"))
    ensure(s.status == ACCEPTED, 409, "simulation_acceptance_required", "模擬驗收後才能付款。")
    buyer = wallets.get_wallet(ctx, p.get("buyer_wallet_id"))
    ensure(buyer.kind == "buyer", 422, "simulation_buyer_required", "請選擇模擬買家。")
    amount = check_int(p.get("amount_minor"), min_=1)
    ensure(
        s.paid_minor + amount <= s.amount_minor,
        409,
        "simulation_overpayment",
        "不能超收模擬服務款。",
    )
    business = wallets.wallet_of_kind(ctx, "business")
    wallets.move(ctx, "service.pay", str(buyer.id), str(business.id), amount, str(s.id))
    s.paid_minor += amount
    return _touch(ctx, s)


# --- seed -----------------------------------------------------------------------


def seed_services(ctx: CommandContext, template: Template) -> None:
    """B§3.0：同時啟用 crm 與 services 時，為示範案件建立範本價格的草稿服務。"""
    assert ctx.workspace is not None
    modules = ctx.workspace.modules
    if "crm" not in modules or "services" not in modules:
        return
    case = list_records(ctx.db, ctx.workspace_id, "cases")[0]
    _new_service(ctx, case, template.sample.price_minor, TEMPLATE_DEMO)


# --- 流水種類 -------------------------------------------------------------------


def _service_pay_rule(
    db: Session, workspace_id: str, ledger: LedgerView
) -> tuple[uuid.UUID, uuid.UUID]:
    """service.pay：買家 → 商家。參照的服務不存在 404 record_missing；
    來源不是買家 422 ledger_invalid。"""
    service = db.get(ServiceRow, ledger.reference_id)
    if service is None or str(service.workspace_id) != workspace_id:
        raise Problem(404, "record_missing", "找不到工作區紀錄")
    business = ledger.system["business"].id
    source = next((w for w, _ in ledger.entries if w != business), None)
    source_row = ledger.wallets.get(source) if source is not None else None
    if source is None or source_row is None or source_row.kind != "buyer":
        raise ledger_invalid("服務付款流水不符")
    return source, business


register_ledger_rule("service.pay", _service_pay_rule)
