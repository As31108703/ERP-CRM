"""模擬報表（B§4）。只讀取，不改任何資料。

- `sales_minor`＝Σ 售價 × 已出貨數量；`refunds_minor`＝Σ 售價 × 已退貨數量。
- `cost_of_goods_sold_minor`＝Σ 出貨成本批次的 成本 ×（數量 − 已退回），即實際 FIFO 成本。
- `gross_profit_minor`＝出貨金額 − 退貨金額 − FIFO 出貨成本。
- `estimated_gross_profit_minor` 改用下單當時的目錄成本快照：
  出貨金額 − 退貨金額 − Σ 品項成本 ×（已出貨 − 已退貨）。
- `inventory_value_minor`＝Σ 商品庫存價值；`service_payments_minor`＝Σ 服務已收款。
- 每個金額（含相減後的毛利）都要在 JS 安全整數內，否則 422 `simulation_amount_overflow`。
- 工作區啟用行政模組時，加上 `administration` 區塊（A§4 的九個指標）。
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from src.modules.administration import snapshot as administration
from src.modules.administration.metrics import admin_metrics
from src.platform.records import check_safe

GROSS_PROFIT_BASIS = "actual_simulation_fifo"

_TOTALS = text(
    """
    WITH lines AS (
      SELECT l.id, l.price_minor, l.cost_minor, l.shipped_quantity, l.returned_quantity
      FROM order_line l
      WHERE l.workspace_id = :w
    )
    SELECT
      (SELECT COALESCE(SUM(price_minor * shipped_quantity), 0) FROM lines) AS sales,
      (SELECT COALESCE(SUM(price_minor * returned_quantity), 0) FROM lines) AS refunds,
      (SELECT COALESCE(SUM(cost_minor * (shipped_quantity - returned_quantity)), 0)
        FROM lines) AS estimated_cost,
      (SELECT COALESCE(SUM(c.cost_minor * (c.quantity - c.returned)), 0)
        FROM shipped_cost_lot c WHERE c.workspace_id = :w) AS cost,
      (SELECT COALESCE(SUM(stock_value_minor), 0) FROM product WHERE workspace_id = :w)
        AS inventory_value,
      (SELECT COALESCE(SUM(paid_minor), 0) FROM service WHERE workspace_id = :w)
        AS service_payments
    """
)


def build_report(db: Session, ws_id: str) -> dict[str, Any]:
    totals = db.execute(_TOTALS, {"w": uuid.UUID(ws_id)}).mappings().one()
    t = {key: check_safe(int(value)) for key, value in totals.items()}
    report: dict[str, Any] = {
        "sales_minor": t["sales"],
        "refunds_minor": t["refunds"],
        "cost_of_goods_sold_minor": t["cost"],
        "gross_profit_minor": check_safe(t["sales"] - t["refunds"] - t["cost"]),
        "estimated_gross_profit_minor": check_safe(t["sales"] - t["refunds"] - t["estimated_cost"]),
        "gross_profit_basis": GROSS_PROFIT_BASIS,
        "inventory_value_minor": t["inventory_value"],
        "service_payments_minor": t["service_payments"],
    }
    if administration.enabled(db, ws_id):
        report["administration"] = admin_metrics(db, ws_id)
    return report
