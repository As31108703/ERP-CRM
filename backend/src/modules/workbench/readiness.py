"""操作提示（F§2 Operation hints）：每筆紀錄目前能做什麼、被什麼擋住。

回傳 `{summary, blockers: [{message, target}]}`；blocker 的 target 無效時改指回紀錄本身。
"""

from typing import Any

from src.modules.workbench.index import World, label, money, num, status_label, taipei_time, text

Readiness = dict[str, Any]


class _Blockers:
    def __init__(self, w: World, own: dict[str, str]) -> None:
        self.w = w
        self.own = own
        self.items: list[dict[str, Any]] = []

    def add(self, message: str, kind: str, row_id: Any) -> None:
        to = self.w.target(kind, row_id) if isinstance(row_id, str) else self.own
        self.items.append({"message": message, "target": to if self.w.valid(to) else self.own})


def readiness(w: World, kind: str, row_id: str) -> Readiness:
    own = w.target(kind, row_id)
    if not w.valid(own):
        return {"summary": "這筆紀錄不在目前啟用的工作區。", "blockers": []}
    row = w.find(kind, row_id)
    if row is None:  # valid(own) 已確認紀錄存在；保險起見與不在工作區同樣處理
        return {"summary": "這筆紀錄不在目前啟用的工作區。", "blockers": []}
    blockers = _Blockers(w, own)
    summary = _SUMMARIES.get(kind, _other)(w, kind, row, blockers)
    return {"summary": summary, "blockers": blockers.items}


def _order(w: World, _kind: str, r: Any, b: _Blockers) -> str:
    if r.get("status") in ("cancelled", "returned"):
        return "這筆訂單已取消或全部退貨，不列為一般待辦。"
    remaining = num(r, "total_minor") - num(r, "paid_minor")
    if remaining > 0:
        buyer = w.find("wallet", r.get("buyer_wallet_id"))
        balance = num(buyer, "balance_minor")
        if balance <= 0:
            buyer_id = buyer["id"] if buyer is not None else r.get("buyer_wallet_id")
            b.add(f"買家沒有可用測試幣，尚欠 {money(remaining)}。", "wallet", buyer_id)
            return f"尚欠 {money(remaining)}，請先準備買家測試幣。"
        payable = money(min(remaining, balance))
        return f"尚欠 {money(remaining)}，目前可先支付最多 {payable}；允許部分付款。"
    unshipped = [
        line
        for line in r.get("lines") or []
        if num(line, "shipped_quantity") < num(line, "quantity")
    ]
    for line in unshipped:
        product = w.find("product", line.get("product_id"))
        need = num(line, "quantity") - num(line, "shipped_quantity")
        if product is None or num(product, "on_hand") < need or num(product, "reserved") < need:
            b.add("本筆訂單的現有庫存或預留數量不足。", "product", line.get("product_id"))
    return "已付清測試幣，可依訂單剩餘數量出貨。" if unshipped else "已全部出貨，不再建議出貨。"


def _work_order(w: World, _kind: str, r: Any, b: _Blockers) -> str:
    status = r.get("status")
    if status == "completed":
        cost = money(num(r, "actual_cost_minor"))
        return f"已完工 {num(r, 'quantity')} 件，實際材料成本 {cost}。"
    if status == "cancelled":
        return "工單已取消，不列為待辦。"
    bom = r.get("bom_snapshot") if isinstance(r.get("bom_snapshot"), dict) else {}
    for component in bom.get("components") or []:
        product = w.find("product", component.get("product_id"))
        need = num(component, "quantity") * num(r, "quantity")
        on_hand, reserved = num(product, "on_hand"), num(product, "reserved")
        available = on_hand - reserved if status == "planned" else min(on_hand, reserved)
        if available < need:
            name = text(product, "name") or "材料"
            state = "可用" if status == "planned" else "已預留"
            b.add(
                f"「{name}」需要 {need} 件，目前{state} {available} 件；依本工單凍結的 BOM。",
                "product",
                component.get("product_id"),
            )
    if status == "planned":
        return "依凍結 BOM 核對共享庫存；材料足夠後可備料。"
    if status == "reserved":
        return "材料已為本工單預留，可開工。"
    return "製作中；完工才消耗材料並轉入成品成本。"


def _service(w: World, _kind: str, r: Any, b: _Blockers) -> str:
    status = r.get("status")
    if status == "draft":
        return "服務草稿，確認內容後才能提交交付物。"
    if status == "confirmed":
        return "已確認服務，可提交第一版交付物。"
    if status == "changes_requested":
        return "需要補件；請提交新版本，舊版本不可作為最新驗收依據。"
    latest = next(
        (d for d in r.get("deliveries") or [] if d.get("id") == r.get("latest_delivery_id")),
        None,
    )
    if latest is None or not text(latest, "digest"):
        b.add("找不到最新交付與摘要，請核對服務版本。", "service", r["id"])
    if status == "submitted":
        return "請以最新交付識別與正確摘要進行模擬驗收。"
    if status == "accepted" and num(r, "paid_minor") < num(r, "amount_minor"):
        buyers = [v for v in w.rows("wallet") if v.get("kind") == "buyer"]
        if not any(num(v, "balance_minor") > 0 for v in buyers):
            b.add(
                "沒有買家可用測試幣；請選擇並補充付款錢包。",
                "wallet",
                buyers[0]["id"] if buyers else r["id"],
            )
        remaining = money(num(r, "amount_minor") - num(r, "paid_minor"))
        return f"已驗收，尚欠 {remaining}；付款時需明確選擇買家錢包，可部分付款。"
    return "服務測試幣已收足，不列為收款待辦。"


def _quote(_w: World, _kind: str, r: Any, _b: _Blockers) -> str:
    status = r.get("status")
    if status == "issued":
        expires = taipei_time(r.get("expires_at"))
        return f"報價已凍結，確認時需使用正確摘要；有效期限 {expires}。"
    if status == "draft":
        return "草稿可發出；發出後內容凍結。"
    return "這份報價已確認或被取代，不列為待辦。"


def _product(_w: World, _kind: str, r: Any, _b: _Blockers) -> str:
    on_hand, reserved = num(r, "on_hand"), num(r, "reserved")
    return f"共用庫存：現有 {on_hand} 件、預留 {reserved} 件、可用 {on_hand - reserved} 件。"


def _wallet(_w: World, _kind: str, r: Any, _b: _Blockers) -> str:
    return f"可用餘額 {money(num(r, 'balance_minor'))}，只提供 SIM 測試幣。"


def _other(_w: World, kind: str, r: Any, _b: _Blockers) -> str:
    status = text(r, "status")
    return f"{label(kind)}{'：' + status_label(status) if status else '可在對應模組查看及更新'}。"


_SUMMARIES = {
    "order": _order,
    "workOrder": _work_order,
    "service": _service,
    "quote": _quote,
    "product": _product,
    "wallet": _wallet,
}
