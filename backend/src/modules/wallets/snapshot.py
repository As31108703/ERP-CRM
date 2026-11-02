"""wallets 模組的快照與還原：集合 `wallets` 與 `ledger`（含 `entries`）。"""

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from src.core import clock
from src.modules.wallets.entity import LedgerEntryRow, LedgerRow, WalletRow
from src.modules.wallets.service import list_wallets, load_ledger


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    wallets = [
        {
            "id": str(w.id),
            "kind": w.kind,
            "name": w.name,
            "balance_minor": w.balance_minor,
            "created_at": clock.iso(w.created_at),
            "updated_at": clock.iso(w.updated_at),
        }
        for w in list_wallets(db, workspace_id)
    ]
    ledger = [
        {
            "id": str(row.id),
            "kind": row.kind,
            "reference_id": str(row.reference_id),
            "created_at": clock.iso(row.created_at),
            "entries": [
                {"wallet_id": str(wallet_id), "amount_minor": amount}
                for wallet_id, amount in entries
            ],
        }
        for row, entries in load_ledger(db, workspace_id)
    ]
    return {"wallets": wallets, "ledger": ledger}


def _time(value: Any, default: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else default


def restore(db: Session, workspace_id: str, data: dict[str, Any]) -> None:
    """依陣列順序插入（保留 seq 順序）；資料須先通過備份驗證（Task 18）。"""
    ws = uuid.UUID(workspace_id)
    now = clock.utcnow()
    for w in data.get("wallets", []):
        created = _time(w.get("created_at"), now)
        db.add(
            WalletRow(
                id=uuid.UUID(w["id"]),
                workspace_id=ws,
                kind=w["kind"],
                name=w["name"],
                balance_minor=w["balance_minor"],
                created_at=created,
                updated_at=_time(w.get("updated_at"), created),
            )
        )
        db.flush()
    for row in data.get("ledger", []):
        ledger_id = uuid.UUID(row["id"])
        db.add(
            LedgerRow(
                id=ledger_id,
                workspace_id=ws,
                kind=row["kind"],
                reference_id=uuid.UUID(row["reference_id"]),
                created_at=_time(row.get("created_at"), now),
            )
        )
        db.flush()
        for idx, e in enumerate(row["entries"]):
            db.add(
                LedgerEntryRow(
                    ledger_id=ledger_id,
                    idx=idx,
                    wallet_id=uuid.UUID(e["wallet_id"]),
                    amount_minor=e["amount_minor"],
                )
            )
        db.flush()
