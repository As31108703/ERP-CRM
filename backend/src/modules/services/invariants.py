"""服務的一致性檢查（B§2 validateWorld 的筆數上限與案件參照、validateIntegrity 的 Services）。"""

from sqlmodel import Session

from src.core.money import check_int
from src.core.problem import Problem, ensure
from src.modules.crm.service import list_records
from src.modules.services.entity import ServiceRow
from src.modules.services.service import (
    ACCEPTED,
    STATUSES,
    deliveries_of,
    delivery_digest,
    list_services,
)
from src.modules.wallets.service import credits_by_reference
from src.platform.records import check_record_limit, crm_record_missing


def _service_invalid(message: str) -> Problem:
    return Problem(422, "service_invalid", message)


def _delivery_invalid(message: str) -> Problem:
    return Problem(422, "delivery_invalid", message)


def check_services(db: Session, workspace_id: str) -> None:
    """最多 500 筆（record_limit）；case_id 指向同工作區的案件（404 record_missing）；
    paid_minor 等於 service.pay 流水合計、paid ≤ amount、狀態合法、legal_confirmation 為 false、
    只有 accepted 可以 paid > 0（service_invalid）；每個交付的摘要相符、latest_delivery_id 為
    最後一個交付或 null（delivery_invalid）；金額與版本為範圍內整數（number_invalid）。"""
    check_record_limit(db, ServiceRow, workspace_id)
    services = list_services(db, workspace_id)
    cases = {r.id for r in list_records(db, workspace_id, "cases")}
    for s in services:
        if s.case_id not in cases:
            raise crm_record_missing()
    paid = credits_by_reference(db, workspace_id, "service.pay")
    for s in services:
        if s.paid_minor != paid.get(s.id, 0):
            raise _service_invalid("服務付款與流水不符")
    deliveries = deliveries_of(db, [s.id for s in services])
    for s in services:
        check_int(s.amount_minor)
        check_int(s.paid_minor)
        if (
            s.legal_confirmation is not False
            or s.paid_minor > s.amount_minor
            or s.status not in STATUSES
        ):
            raise _service_invalid("服務狀態不符")
        rows = deliveries[s.id]
        for d in rows:
            check_int(d.revision, min_=1)
            if d.digest != delivery_digest(s.id, d.revision, d.artifact_ref):
                raise _delivery_invalid("交付摘要不符")
        ensure(
            s.latest_delivery_id == (rows[-1].id if rows else None),
            422,
            "delivery_invalid",
            "最新交付不符",
        )
        if s.paid_minor > 0 and s.status != ACCEPTED:
            raise _service_invalid("服務付款不符")
