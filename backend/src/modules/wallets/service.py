"""錢包與複式帳本（B§3.5）：系統錢包、買家錢包、補幣與 `move()`。

每筆資金移動寫一筆 ledger 與兩個分錄（來源 -amount、目的 +amount）。其他模組以
`register_ledger_rule(kind, rule)` 宣告自己的流水種類與資金方向，一致性檢查依此驗證。
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.catalog.templates import Template
from src.modules.wallets.entity import SYSTEM_KINDS, LedgerEntryRow, LedgerRow, WalletRow
from src.platform.context import CommandContext
from src.platform.records import check_safe, parse_id, record_missing

DEMO_BUYER_NAME = "示範買家"
FUNDABLE_KINDS = ("buyer", "business")


# --- 查詢 -----------------------------------------------------------------------


def _ws(ctx: CommandContext) -> uuid.UUID:
    return uuid.UUID(ctx.workspace_id)


def list_wallets(db: Session, workspace_id: str) -> list[WalletRow]:
    stmt = (
        select(WalletRow)
        .where(WalletRow.workspace_id == uuid.UUID(workspace_id))
        .order_by(WalletRow.seq)  # type: ignore[arg-type]
    )
    return list(db.exec(stmt))


def load_ledger(
    db: Session, workspace_id: str
) -> list[tuple[LedgerRow, list[tuple[uuid.UUID, int]]]]:
    """工作區的流水（依寫入順序）與各自的分錄 `(wallet_id, amount_minor)`（依 idx）。"""
    ledgers = list(
        db.exec(
            select(LedgerRow)
            .where(LedgerRow.workspace_id == uuid.UUID(workspace_id))
            .order_by(LedgerRow.seq)  # type: ignore[arg-type]
        )
    )
    entries: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = {row.id: [] for row in ledgers}
    if ledgers:
        stmt = (
            select(LedgerEntryRow)
            .where(LedgerEntryRow.ledger_id.in_(list(entries)))  # type: ignore[attr-defined]
            .order_by(LedgerEntryRow.ledger_id, LedgerEntryRow.idx)  # type: ignore[arg-type]
        )
        for e in db.exec(stmt):
            entries[e.ledger_id].append((e.wallet_id, e.amount_minor))
    return [(row, entries[row.id]) for row in ledgers]


def get_wallet(ctx: CommandContext, wallet_id: object) -> WalletRow:
    """工作區內的錢包；不存在時 404 simulation_record_missing。"""
    parsed = parse_id(wallet_id)
    row = ctx.db.get(WalletRow, parsed) if parsed is not None else None
    if row is None or row.workspace_id != _ws(ctx):
        raise record_missing()
    return row


def wallet_of_kind(ctx: CommandContext, kind: str) -> WalletRow:
    """系統錢包（business、supplier、faucet）；不存在表示資料毀損，拋出 RuntimeError。"""
    if kind not in SYSTEM_KINDS:
        raise ValueError(f"{kind} 不是系統錢包")
    stmt = select(WalletRow).where(WalletRow.workspace_id == _ws(ctx), WalletRow.kind == kind)
    row = ctx.db.exec(stmt).first()
    if row is None:
        raise RuntimeError(f"缺少系統錢包 {kind}")
    return row


# --- 寫入 -----------------------------------------------------------------------


def _new_wallet(ctx: CommandContext, kind: str, name: str) -> WalletRow:
    row = WalletRow(
        workspace_id=_ws(ctx),
        kind=kind,
        name=name,
        balance_minor=0,
        created_at=ctx.now,
        updated_at=ctx.now,
    )
    ctx.db.add(row)
    # 依序 flush，讓 seq 依建立順序遞增
    ctx.db.flush()
    return row


def ensure_system_wallets(ctx: CommandContext) -> None:
    """缺少的系統錢包以 `name = kind`、餘額 0 建立；已存在的不動。"""
    existing = {w.kind for w in list_wallets(ctx.db, ctx.workspace_id)}
    for kind in SYSTEM_KINDS:
        if kind not in existing:
            _new_wallet(ctx, kind, kind)


def move(
    ctx: CommandContext,
    kind: str,
    from_id: str,
    to_id: str,
    amount: int,
    reference_id: str | None = None,
) -> str:
    """把 amount 從 from 移到 to，寫一筆 `kind` 流水並回傳其 id。

    reference_id 未指定時指向流水自己（例如 wallet.fund）。金額為負 422
    simulation_amount_invalid；來源不是 faucet 且餘額不足 409 simulation_insufficient_funds。
    """
    source = get_wallet(ctx, from_id)
    target = get_wallet(ctx, to_id)
    ensure(
        isinstance(amount, int) and not isinstance(amount, bool),
        422,
        "simulation_amount_invalid",
        "模擬金額不符。",
    )
    check_safe(amount)
    ensure(amount >= 0, 422, "simulation_amount_invalid", "模擬金額不符。")
    ensure(
        source.kind == "faucet" or source.balance_minor >= amount,
        409,
        "simulation_insufficient_funds",
        "模擬錢包餘額不足。",
    )
    source.balance_minor = check_safe(source.balance_minor - amount)
    target.balance_minor = check_safe(target.balance_minor + amount)
    source.updated_at = target.updated_at = ctx.now
    ledger_id = uuid.uuid4()
    reference = ledger_id if reference_id is None else parse_id(reference_id)
    if reference is None:
        raise ValueError("reference_id 必須是 UUID")
    ctx.db.add(
        LedgerRow(
            id=ledger_id,
            workspace_id=_ws(ctx),
            kind=kind,
            reference_id=reference,
            created_at=ctx.now,
        )
    )
    ctx.db.flush()
    ctx.db.add(
        LedgerEntryRow(ledger_id=ledger_id, idx=0, wallet_id=source.id, amount_minor=-amount)
    )
    ctx.db.add(LedgerEntryRow(ledger_id=ledger_id, idx=1, wallet_id=target.id, amount_minor=amount))
    ctx.db.flush()
    return str(ledger_id)


# --- 命令 handler ---------------------------------------------------------------


def create_wallet(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`wallet.create {kind: 'buyer', name}`；payload 的 id 與其他欄位一律忽略。"""
    return str(_new_wallet(ctx, "buyer", p["name"]).id)


def fund_wallet(ctx: CommandContext, p: dict[str, Any]) -> str:
    """`wallet.fund {wallet_id, amount_minor}`：faucet → 買家或商家錢包，回傳流水 id。"""
    wallet = get_wallet(ctx, p.get("wallet_id"))
    ensure(
        wallet.kind in FUNDABLE_KINDS,
        422,
        "simulation_wallet_invalid",
        "只能補充買家或商家的測試幣。",
    )
    amount = check_int(p.get("amount_minor"), min_=1)
    faucet = wallet_of_kind(ctx, "faucet")
    return move(ctx, "wallet.fund", str(faucet.id), str(wallet.id), amount)


def seed_wallets(ctx: CommandContext, _template: Template) -> None:
    """B§3.0：系統錢包與餘額 0 的示範買家錢包，不論啟用哪些模組都建立。"""
    ensure_system_wallets(ctx)
    _new_wallet(ctx, "buyer", DEMO_BUYER_NAME)


# --- 流水種類 -------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerView:
    """一致性檢查時交給流水規則的資料。"""

    id: uuid.UUID
    kind: str
    reference_id: uuid.UUID
    entries: list[tuple[uuid.UUID, int]]
    # 正向（入帳）分錄的金額
    credit: int
    wallets: dict[uuid.UUID, WalletRow]
    system: dict[str, WalletRow]


# (db, workspace_id, ledger) -> (來源錢包 id, 目的錢包 id)；規則不符時拋 Problem
LedgerRule = Callable[[Session, str, LedgerView], tuple[uuid.UUID, uuid.UUID]]
_LEDGER_RULES: dict[str, LedgerRule] = {}


def register_ledger_rule(kind: str, rule: LedgerRule) -> None:
    """宣告一種流水；未註冊的流水種類一律視為 ledger_invalid。"""
    _LEDGER_RULES[kind] = rule


def ledger_rule(kind: str) -> LedgerRule | None:
    return _LEDGER_RULES.get(kind)


def ledger_invalid(message: str = "流水不符") -> Problem:
    return Problem(422, "ledger_invalid", message)


def _fund_rule(_db: Session, _ws_id: str, ledger: LedgerView) -> tuple[uuid.UUID, uuid.UUID]:
    faucet = ledger.system["faucet"].id
    target = next((w for w, _ in ledger.entries if w != faucet), None)
    target_row = ledger.wallets.get(target) if target is not None else None
    if (
        target is None
        or target_row is None
        or target_row.kind not in FUNDABLE_KINDS
        or ledger.reference_id != ledger.id
    ):
        raise ledger_invalid("補幣流水不符")
    return faucet, target


register_ledger_rule("wallet.fund", _fund_rule)


def credit_of(entries: list[tuple[uuid.UUID, int]]) -> int:
    """流水的入帳金額：第一個非負分錄的金額（沒有時為 0）。"""
    return next((amount for _, amount in entries if amount >= 0), 0)


def credits_by_reference(db: Session, workspace_id: str, kind: str) -> dict[uuid.UUID, int]:
    """各 reference_id 的 `kind` 流水入帳金額合計，例如每筆採購的 inventory.receive 金額。"""
    stmt = (
        select(
            LedgerRow.id,
            LedgerRow.reference_id,
            LedgerEntryRow.wallet_id,
            LedgerEntryRow.amount_minor,
        )
        .join(LedgerEntryRow, LedgerEntryRow.ledger_id == LedgerRow.id)  # type: ignore[arg-type]
        .where(LedgerRow.workspace_id == uuid.UUID(workspace_id), LedgerRow.kind == kind)
        .order_by(LedgerRow.id, LedgerEntryRow.idx)  # type: ignore[arg-type]
    )
    entries: dict[uuid.UUID, tuple[uuid.UUID, list[tuple[uuid.UUID, int]]]] = {}
    for ledger_id, ref, wallet_id, amount in db.execute(stmt):
        entries.setdefault(ledger_id, (ref, []))[1].append((wallet_id, amount))
    sums: dict[uuid.UUID, int] = {}
    for ref, rows in entries.values():
        sums[ref] = sums.get(ref, 0) + credit_of(rows)
    return sums
