"""待處理工作（F§2 Pending work queue）：依目前資料整理下一步，attention 排在前面。

每筆 `{id: "<kind>:<id>:<op>", target, title, description, priority, label}`；
只會指向紀錄，不會自動付款、出貨或更新資料。
"""

from datetime import datetime
from typing import Any

from src.modules.workbench.index import World, num, parse_time, taipei_time, title
from src.modules.workbench.readiness import readiness

_SERVICE_LABELS = {
    "draft": "確認服務",
    "confirmed": "提交交付物",
    "changes_requested": "提交補件",
    "submitted": "驗收最新交付",
    "accepted": "收取測試幣",
}
_EXPIRED = "報價已過期，請回到原案件重新起草模擬報價。"


def work_queue(w: World, now: datetime) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(
        kind: str,
        row: Any,
        operation: str,
        label: str,
        to: dict[str, str] | None = None,
        attention: bool = False,
    ) -> None:
        to = to or w.target(kind, row["id"])
        if not w.valid(to):
            return
        ready = readiness(w, kind, row["id"])
        if operation == "expired":
            description = _EXPIRED
        elif kind in ("task", "milestone") and attention:
            description = f"期限 {taipei_time(row.get('due_at'))} 已過；{ready['summary']}"
        else:
            description = " ".join(b["message"] for b in ready["blockers"]) or ready["summary"]
        items.append(
            {
                "id": f"{kind}:{row['id']}:{operation}",
                "target": to,
                "title": title(kind, row),
                "description": description,
                "priority": "attention" if attention else "next",
                "label": label,
            }
        )

    def first_blocker(kind: str, row: Any) -> tuple[dict[str, str], bool]:
        blockers = readiness(w, kind, row["id"])["blockers"]
        return (blockers[0]["target"] if blockers else w.target(kind, row["id"])), bool(blockers)

    if w.has("sales"):
        for order in w.rows("order"):
            if order.get("status") in ("cancelled", "returned"):
                continue
            if num(order, "paid_minor") < num(order, "total_minor"):
                funded = num(w.find("wallet", order.get("buyer_wallet_id")), "balance_minor") > 0
                if funded:
                    add("order", order, "pay", "支付測試幣")
                else:
                    wallet = w.target("wallet", str(order.get("buyer_wallet_id")))
                    add("order", order, "pay", "準備買家測試幣", wallet, True)
            elif any(
                num(line, "shipped_quantity") < num(line, "quantity")
                for line in order.get("lines") or []
            ):
                to, blocked = first_blocker("order", order)
                add("order", order, "ship", "核對並出貨", to, blocked)

    if w.has("manufacturing"):
        steps = {"planned": "預留材料", "reserved": "開始製作", "started": "完成製作"}
        for wo in w.rows("workOrder"):
            status = wo.get("status")
            if status not in steps:
                continue
            to, blocked = first_blocker("workOrder", wo)
            add("workOrder", wo, status, "補足工單材料" if blocked else steps[status], to, blocked)

    if w.has("services"):
        for service in w.rows("service"):
            status = service.get("status")
            if status not in _SERVICE_LABELS:
                continue
            if status == "accepted" and num(service, "paid_minor") >= num(service, "amount_minor"):
                continue
            to, blocked = first_blocker("service", service)
            attention = blocked or status == "changes_requested"
            add("service", service, status, _SERVICE_LABELS[status], to, attention)

    if w.has(w.module_for("quote")):
        for quote in w.rows("quote"):
            expires = parse_time(quote.get("expires_at"))
            if quote.get("status") != "issued" or expires is None or expires > now:
                continue
            case = w.find("case", quote.get("case_id"))
            to = w.target("case", case["id"]) if case is not None else None
            add("quote", quote, "expired", "重新起草報價", to, True)

    if w.has("projects"):
        for kind in ("task", "milestone"):
            for row in w.rows(kind):
                if row.get("status") in ("done", "completed", "cancelled", "closed"):
                    continue
                due = parse_time(row.get("due_at"))
                overdue = due is not None and due < now
                add(kind, row, "progress", "處理逾期待辦" if overdue else "更新進度", None, overdue)

    # 穩定排序：attention 在前，同組維持產生順序
    return sorted(items, key=lambda item: item["priority"] != "attention")
