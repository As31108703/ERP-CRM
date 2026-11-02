"""錢包與帳本的一致性檢查（B§2 validateWorld 子集），命令執行後由命令管線呼叫。"""

from sqlmodel import Session

from src.core.problem import Problem, ensure
from src.modules.wallets.entity import SYSTEM_KINDS, WALLET_KINDS, LedgerRow, WalletRow
from src.modules.wallets.service import (
    LedgerView,
    credit_of,
    ledger_invalid,
    ledger_rule,
    list_wallets,
    load_ledger,
)
from src.platform.records import MAX_SAFE_INTEGER, check_record_limit


def check_wallets(db: Session, workspace_id: str) -> None:
    check_record_limit(db, WalletRow, workspace_id)
    check_record_limit(db, LedgerRow, workspace_id)
    wallets = list_wallets(db, workspace_id)
    for w in wallets:
        ensure(
            w.kind in WALLET_KINDS
            and abs(w.balance_minor) <= MAX_SAFE_INTEGER
            and (w.kind == "faucet" or w.balance_minor >= 0),
            422,
            "wallet_invalid",
            "錢包不符",
        )
    ensure(sum(w.balance_minor for w in wallets) == 0, 422, "money_conservation", "測試幣不守恆")
    for kind in SYSTEM_KINDS:
        ensure(
            sum(1 for w in wallets if w.kind == kind) == 1, 422, "wallet_invalid", "系統錢包不符"
        )
    by_id = {w.id: w for w in wallets}
    system = {w.kind: w for w in wallets if w.kind in SYSTEM_KINDS}
    balances = dict.fromkeys(by_id, 0)
    for row, entries in load_ledger(db, workspace_id):
        for wallet_id, _ in entries:
            if wallet_id not in by_id:
                raise Problem(404, "record_missing", "找不到工作區紀錄")
        ensure(
            len(entries) == 2 and sum(a for _, a in entries) == 0,
            422,
            "ledger_invalid",
            "流水不守恆",
        )
        rule = ledger_rule(row.kind)
        if rule is None:
            raise ledger_invalid("未知流水種類")
        credit = credit_of(entries)
        view = LedgerView(
            id=row.id,
            kind=row.kind,
            reference_id=row.reference_id,
            entries=entries,
            credit=credit,
            wallets=by_id,
            system=system,
        )
        source, target = rule(db, workspace_id, view)
        ensure(
            source != target and (source, -credit) in entries and (target, credit) in entries,
            422,
            "ledger_invalid",
            "流水對象不符",
        )
        for wallet_id, amount in entries:
            balances[wallet_id] += amount
    for w in wallets:
        ensure(
            balances[w.id] == w.balance_minor,
            422,
            "ledger_balance_invalid",
            "錢包與流水不符",
        )
