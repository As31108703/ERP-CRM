"""行政指標（A§4，報表的 `administration` 區塊）。只讀取，不改任何資料。

報表只在工作區啟用行政模組時才輸出這個區塊，由呼叫端（Task 15 報表）以
`snapshot.enabled()` 判斷；這裡只負責計算。
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from src.modules.administration.attendance import actual_work_minutes

_COUNTS = text(
    """
    SELECT
      (SELECT count(*) FROM adm_unit WHERE workspace_id = :w AND active) AS active_units,
      (SELECT count(*) FROM adm_staff WHERE workspace_id = :w AND status = 'active')
        AS active_staff,
      (SELECT count(*) FROM adm_shift WHERE workspace_id = :w AND status = 'scheduled')
        AS scheduled_shifts,
      (SELECT count(*) FROM adm_request
        WHERE workspace_id = :w AND status IN ('draft', 'submitted', 'returned'))
        AS open_requests,
      (SELECT count(*) FROM adm_request
        WHERE workspace_id = :w AND status = 'prepared_unreviewed')
        AS prepared_unreviewed_requests,
      (SELECT count(*) FROM adm_equipment WHERE workspace_id = :w AND state = 'available')
        AS available_equipment,
      (SELECT count(*) FROM adm_reservation WHERE workspace_id = :w AND status = 'reserved')
        AS active_reservations,
      (SELECT count(*) FROM adm_notice WHERE workspace_id = :w AND pinned AND NOT archived)
        AS pinned_notices
    """
)

KEYS = (
    "active_units",
    "active_staff",
    "scheduled_shifts",
    "actual_work_minutes",
    "open_requests",
    "prepared_unreviewed_requests",
    "available_equipment",
    "active_reservations",
    "pinned_notices",
)


def admin_metrics(db: Session, ws_id: str) -> dict[str, Any]:
    """九個行政指標；actual_work_minutes 為未作廢出勤的（結束 − 開始）分鐘減休息，不截斷。"""
    counts = db.execute(_COUNTS, {"w": uuid.UUID(ws_id)}).mappings().one()
    values = {key: int(value) for key, value in counts.items()}
    values["actual_work_minutes"] = actual_work_minutes(db, ws_id)
    return {key: values[key] for key in KEYS}
