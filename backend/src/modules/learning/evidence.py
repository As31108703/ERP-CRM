"""完成證據：以實際工作區紀錄判斷每一步是否完成，並產生「本輪／整個工作區」讀值。

一步要算完成，必須同時滿足：前面每一步都已完成、有檢查點、history 有相同的
`{action, result, version}`，以及實際紀錄通過該步的證據檢查。
"""

import json
import re
import uuid
from collections.abc import Iterable
from typing import Any, TypedDict

from sqlmodel import Session, select

from src.modules.learning.entity import LearningCheckpointRow, LearningSessionRow
from src.modules.learning.paths import (
    PATHS,
    QUOTE_AMOUNT,
    Checkpoint,
    LearningPath,
    Run,
    World,
    business_wallet,
    is_int,
    money,
    own_name,
    row,
    sale_product,
    single_component_bom,
)
from src.platform import registry
from src.platform.context import HistoryRow, WorkspaceRow, WorkspaceSessionRow

# 證據與讀值只需要這些模組的集合（快照不分模組是否啟用）
WORLD_MODULES = frozenset({"inventory", "wallets", "sales", "crm", "services", "manufacturing"})
RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,80}", re.ASCII)
PAYLOAD_MAX = 32_768
RESULT_MAX = 100
FACT_ROWS_MAX = 12

TEXT_INVALID = "教學紀錄與目前工作區不符，請開始新練習。"
TEXT_MISSING = "尚未找到本次操作與工作區資料的完整證據。"


class StepEvaluation(TypedDict):
    id: str
    complete: bool
    evidence_text: str
    checkpoint: dict[str, Any] | None


class Evaluation(TypedDict):
    steps: list[StepEvaluation]
    next_index: int
    complete: bool


Fact = dict[str, str]


# --- 讀值 -------------------------------------------------------------------------------------


def load_world(db: Session, workspace: WorkspaceRow, versions: Iterable[int] = ()) -> World:
    """工作區讀值：相關模組的快照集合、模組清單、目前版本，以及指定版本的 history。"""
    workspace_id = str(workspace.id)
    session_row = db.get(WorkspaceSessionRow, workspace.session_id)
    w: World = {
        "modules": list(workspace.modules),
        "version": session_row.version if session_row is not None else 0,
    }
    for spec in registry.all_specs():
        if spec.name in WORLD_MODULES:
            w.update(spec.snapshot(db, workspace_id))
    wanted = sorted(set(versions))
    history: list[dict[str, Any]] = []
    if wanted:
        stmt = select(HistoryRow).where(
            HistoryRow.workspace_id == workspace.id,
            HistoryRow.version.in_(wanted),  # type: ignore[attr-defined]
        )
        history = [
            {"action": h.action, "result": h.result, "version": h.version} for h in db.exec(stmt)
        ]
    w["history"] = history
    return w


def load_run(db: Session, session: LearningSessionRow) -> Run:
    stmt = (
        select(LearningCheckpointRow)
        .where(LearningCheckpointRow.session_id == session.id)
        .order_by(LearningCheckpointRow.version)  # type: ignore[arg-type]
    )
    checkpoints = [
        Checkpoint(c.step_id, c.action, dict(c.payload), c.result, c.version) for c in db.exec(stmt)
    ]
    return Run(session.path, session.run_id, checkpoints)


def path_available(w: World, path: LearningPath) -> bool:
    return all(m in w["modules"] for m in path.modules)


# --- 檢查 -------------------------------------------------------------------------------------


def valid_run(w: World, run: Run) -> bool:
    """檢查點依步驟順序、命令相符、結果 1–100 字、版本嚴格遞增且不超過目前版本。"""
    path = PATHS.get(run.path)
    if path is None or not path_available(w, path):
        return False
    if not isinstance(run.run_id, str) or RUN_ID_RE.fullmatch(run.run_id) is None:
        return False
    if len(run.checkpoints) > len(path.steps):
        return False
    version = -1
    for i, c in enumerate(run.checkpoints):
        step = path.steps[i]
        if c.step_id != step.id or c.action != step.action:
            return False
        if not isinstance(c.result, str) or not 0 < len(c.result) <= RESULT_MAX:
            return False
        if not is_int(c.version) or c.version <= version or c.version > w["version"]:
            return False
        version = c.version
        if not isinstance(c.payload, dict):
            return False
        if len(json.dumps(c.payload, ensure_ascii=False)) > PAYLOAD_MAX:
            return False
    return True


def history_matches(w: World, c: Checkpoint) -> bool:
    return any(
        h["version"] == c.version and h["action"] == c.action and h["result"] == c.result
        for h in w["history"]
    )


def evidence_for(w: World, run: Run, c: Checkpoint) -> str | None:
    """依步驟核對實際紀錄；成立時回傳成功說明，否則 None。"""
    p = c.payload
    previous = run.cp
    buyer = previous("buyer")

    def record(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        return row(items, c.result)

    if c.step_id == "customer":
        v = record(w["customers"])
        ok = v is not None and v.get("name") == own_name(run, "客戶") and p.get("name") == v["name"]
        return "本次教學客戶已建立。" if ok else None
    if c.step_id == "buyer":
        v = record(w["wallets"])
        ok = (
            v is not None
            and v.get("kind") == "buyer"
            and v.get("name") == own_name(run, "買家")
            and p.get("kind") == "buyer"
            and p.get("name") == v["name"]
        )
        return "本次專用買家錢包已建立。" if ok else None
    if c.action == "wallet.fund":
        return _fund_evidence(w, run, c)
    if c.step_id == "receive":
        purchase = record(w["purchases"])
        product = row(w["products"], p.get("product_id"))
        ok = (
            purchase is not None
            and product is not None
            and purchase.get("product_id") == p.get("product_id")
            and purchase.get("quantity") == p.get("quantity")
            and is_int(p.get("quantity"))
            and p["quantity"] > 0
        )
        return "本次採購與成本層已建立。" if ok else None
    if run.path == "sales":
        return _sales_evidence(w, run, c, buyer)
    if run.path == "manufacturing":
        return _manufacturing_evidence(w, run, c)
    if run.path == "service":
        return _service_evidence(w, run, c, buyer)
    return None


def _fund_evidence(w: World, run: Run, c: Checkpoint) -> str | None:
    p = c.payload
    previous = run.cp
    ledger = row(w["ledger"], c.result)
    if c.step_id == "fund-business":
        wallet = business_wallet(w)
        received = previous("receive")
        purchase = row(w["purchases"], received.result) if received else None
        cost: Any = purchase.get("total_minor") if purchase else None
        if cost is None:
            if run.path == "sales":
                cost = (sale_product(w) or {}).get("cost_minor")
            else:
                bom = single_component_bom(w)
                if bom is not None:
                    component = bom["components"][0]
                    material = row(w["products"], component.get("product_id")) or {}
                    unit = material.get("cost_minor")
                    cost = unit * component["quantity"] if is_int(unit) else None
        expected = max(100, cost) if is_int(cost) else None
    else:
        buyer_cp = previous("buyer")
        wallet = row(w["wallets"], buyer_cp.result) if buyer_cp else None
        if run.path == "service":
            service_cp = previous("service")
            service = row(w["services"], service_cp.result) if service_cp else None
            expected = (service or {}).get("amount_minor")
        else:
            order_cp = previous("order")
            order = row(w["orders"], order_cp.result) if order_cp else None
            if order is not None:
                expected = order.get("total_minor")
            else:
                received = previous("receive")
                product = (
                    row(w["products"], received.payload.get("product_id")) if received else None
                )
                expected = (product or {}).get("price_minor")
    amount = p.get("amount_minor")
    ok = (
        expected is not None
        and amount == expected
        and ledger is not None
        and ledger.get("kind") == "wallet.fund"
        and wallet is not None
        and p.get("wallet_id") == wallet["id"]
        and is_int(amount)
        and amount > 0
        and any(
            e.get("wallet_id") == wallet["id"] and e.get("amount_minor") == amount
            for e in ledger.get("entries") or []
        )
    )
    return f"已補入 {money(amount)}，流水可查。" if ok else None


def _sales_evidence(w: World, run: Run, c: Checkpoint, buyer: Checkpoint | None) -> str | None:
    p = c.payload
    order_cp = run.cp("order")
    o = row(w["orders"], order_cp.result) if order_cp else None
    if c.step_id == "order":
        v = row(w["orders"], c.result)
        receive = run.cp("receive")
        p_lines = p.get("lines") or []
        v_lines = (v or {}).get("lines") or []
        ok = (
            v is not None
            and buyer is not None
            and receive is not None
            and v.get("learning_run_id") == run.run_id
            and p.get("learning_run_id") == run.run_id
            and p.get("buyer_wallet_id") == buyer.result
            and v.get("buyer_wallet_id") == buyer.result
            and len(p_lines) == 1
            and len(v_lines) == 1
            and p_lines[0].get("product_id") == receive.payload.get("product_id")
            and p_lines[0].get("quantity") == 1
            and v_lines[0].get("product_id") == p_lines[0].get("product_id")
            and v_lines[0].get("quantity") == 1
        )
        return "本次訂單已建立；其後付款與出貨仍屬於這筆訂單。" if ok else None
    if o is None or c.result != o["id"] or p.get("id") != o["id"]:
        return None
    if c.step_id == "pay":
        ok = p.get("amount_minor") == o.get("total_minor") and o.get("paid_minor") == o.get(
            "total_minor"
        )
        return "本次訂單已付清測試幣。" if ok else None
    if c.step_id == "ship":
        p_lines = p.get("lines") or []
        o_lines = o.get("lines") or []
        ok = (
            len(p_lines) == 1
            and bool(o_lines)
            and p_lines[0].get("line_id") == o_lines[0].get("id")
            and p_lines[0].get("quantity") == 1
            and o_lines[0].get("shipped_quantity") == 1
        )
        return "本次訂單已出貨一件，成本依 FIFO 扣除。" if ok else None
    return None


_WO_STATUSES = {
    "reserve": (("reserved", "started", "completed"), "本次工單已預留材料。"),
    "start": (("started", "completed"), "本次工單已開工。"),
    "complete": (("completed",), "本次工單已完工，材料成本已轉入成品。"),
}


def _manufacturing_evidence(w: World, run: Run, c: Checkpoint) -> str | None:
    p = c.payload
    if c.step_id == "work-order":
        v = row(w["work_orders"], c.result)
        r = run.cp("receive")
        components = ((v or {}).get("bom_snapshot") or {}).get("components") or []
        ok = (
            v is not None
            and r is not None
            and v.get("learning_run_id") == run.run_id
            and p.get("learning_run_id") == run.run_id
            and v.get("bom_id") == p.get("bom_id")
            and p.get("quantity") == 1
            and v.get("quantity") == 1
            and len(components) == 1
            and components[0].get("product_id") == r.payload.get("product_id")
            and components[0].get("quantity") == r.payload.get("quantity")
        )
        return "本次製作單與 BOM 快照已建立。" if ok else None
    wo_cp = run.cp("work-order")
    o = row(w["work_orders"], wo_cp.result) if wo_cp else None
    rule = _WO_STATUSES.get(c.step_id)
    if o is None or rule is None or p.get("id") != o["id"] or c.result != o["id"]:
        return None
    statuses, text = rule
    ok = o.get("status") in statuses
    if c.step_id == "complete":
        ok = ok and is_int(o.get("actual_cost_minor"))
    return text if ok else None


def _service_evidence(w: World, run: Run, c: Checkpoint, buyer: Checkpoint | None) -> str | None:
    p = c.payload
    case_cp = run.cp("case")
    quote_cp = run.cp("quote")
    service_cp = run.cp("service")
    q = row(w["quotes"], quote_cp.result) if quote_cp else None
    service = row(w["services"], service_cp.result) if service_cp else None
    sid = c.step_id
    if sid == "case":
        v = row(w["cases"], c.result)
        customer = run.cp("customer")
        ok = (
            v is not None
            and customer is not None
            and v.get("customer_id") == customer.result
            and p.get("customer_id") == v.get("customer_id")
            and v.get("title") == own_name(run, "服務案件")
            and p.get("title") == v.get("title")
        )
        return "本次客戶與服務案件已連結。" if ok else None
    if sid == "quote":
        v = row(w["quotes"], c.result)
        ok = (
            v is not None
            and case_cp is not None
            and v.get("case_id") == case_cp.result
            and p.get("case_id") == v.get("case_id")
            and v.get("amount_minor") == QUOTE_AMOUNT
            and p.get("amount_minor") == v.get("amount_minor")
            and v.get("expires_at") == p.get("expires_at")
        )
        return "本次模擬報價草稿已建立。" if ok else None
    if sid in ("issue", "confirm-quote"):
        if q is None or c.result != q["id"] or p.get("id") != q["id"]:
            return None
        if sid == "issue":
            ok = q.get("status") in ("issued", "simulated_confirmed") and isinstance(
                q.get("digest"), str
            )
            return "本次報價已發出並凍結內容。" if ok else None
        ok = (
            p.get("digest") == q.get("digest")
            and q.get("status") == "simulated_confirmed"
            and q.get("legal_confirmation") is False
        )
        return "本次報價已模擬確認，沒有法律效力。" if ok else None
    if sid == "service":
        v = row(w["services"], c.result)
        ok = (
            v is not None
            and q is not None
            and case_cp is not None
            and p.get("case_id") == case_cp.result
            and v.get("case_id") == p.get("case_id")
            and p.get("amount_minor") == q.get("amount_minor")
            and v.get("amount_minor") == p.get("amount_minor")
            and v.get("currency") == "SIM"
        )
        return "本次服務已建立，金額沿用模擬報價。" if ok else None
    if service is None or c.result != service["id"] or p.get("id") != service["id"]:
        return None
    if sid == "confirm-service":
        return "本次服務已確認。" if service.get("status") != "draft" else None
    if sid == "deliver":
        ref = own_name(run, "交付物")
        d = next((v for v in service.get("deliveries") or [] if v.get("artifact_ref") == ref), None)
        ok = (
            p.get("artifact_ref") == ref
            and d is not None
            and service.get("latest_delivery_id") == d["id"]
        )
        return "本次交付版本已提交，摘要可核對。" if ok else None
    if sid == "accept":
        delivery = row(service.get("deliveries"), p.get("delivery_id"))
        ok = (
            service.get("status") == "accepted"
            and p.get("delivery_id") == service.get("latest_delivery_id")
            and delivery is not None
            and delivery.get("digest") == p.get("digest")
        )
        return "本次最新交付已模擬驗收。" if ok else None
    if sid == "pay":
        ok = (
            buyer is not None
            and p.get("buyer_wallet_id") == buyer.result
            and p.get("amount_minor") == service.get("amount_minor")
            and service.get("paid_minor") == service.get("amount_minor")
        )
        return "本次服務已收到全額測試幣。" if ok else None
    return None


# --- 進度 -------------------------------------------------------------------------------------


def evaluate_world(w: World, run: Run) -> Evaluation:
    """依 F§3 的進度計算：串鏈、檢查點、history 與實際紀錄四者皆成立才算完成。"""
    path = PATHS[run.path]
    valid = valid_run(w, run)
    chain = True
    steps: list[StepEvaluation] = []
    for step in path.steps:
        c = run.cp(step.id) if valid else None
        evidence = evidence_for(w, run, c) if c is not None and history_matches(w, c) else None
        complete = chain and evidence is not None
        chain = complete
        if complete:
            text = evidence or ""
        else:
            text = TEXT_INVALID if not valid else TEXT_MISSING
        steps.append(
            {
                "id": step.id,
                "complete": complete,
                "evidence_text": text,
                "checkpoint": c.public() if c is not None else None,
            }
        )
    next_index = next((i for i, s in enumerate(steps) if not s["complete"]), len(steps))
    return {"steps": steps, "next_index": next_index, "complete": next_index == len(steps)}


def evaluate(db: Session, ws_id: str, session: LearningSessionRow) -> Evaluation:
    """讀取工作區與該輪檢查點後計算進度。"""
    workspace = db.exec(select(WorkspaceRow).where(WorkspaceRow.id == uuid.UUID(ws_id))).one()
    run = load_run(db, session)
    w = load_world(db, workspace, (c.version for c in run.checkpoints))
    return evaluate_world(w, run)


# --- 讀值面板 ---------------------------------------------------------------------------------


def _fact(label: str, value: str) -> Fact:
    return {"label": label, "value": value}


def _sum(items: Iterable[dict[str, Any]], key: str) -> int:
    return sum(int(v.get(key) or 0) for v in items)


def facts(w: World, run: Run, scope: str = "lesson") -> list[Fact]:
    """F§3 Live data panel：本輪只算這一輪的紀錄（共用庫存與商家測試幣另標示），
    整個工作區則是全部合計。"""
    business = money(
        _sum((v for v in w["wallets"] if v.get("kind") == "business"), "balance_minor")
    )
    if scope == "workspace":
        return _workspace_facts(w, run, business)

    def checkpoint(step_id: str) -> Checkpoint | None:
        c = run.cp(step_id)
        return c if c is not None and history_matches(w, c) else None

    def result_of(step_id: str) -> str | None:
        c = checkpoint(step_id)
        return c.result if c else None

    customer = row(w["customers"], result_of("customer"))
    buyer_row = row(w["wallets"], result_of("buyer"))
    buyer = (
        buyer_row
        if buyer_row is not None
        and buyer_row.get("name") == own_name(run, "買家")
        and buyer_row.get("kind") == "buyer"
        else None
    )
    common = [
        _fact("共用商家測試幣", business),
        _fact("本輪買家測試幣", money((buyer or {}).get("balance_minor") or 0)),
    ]
    own_customer = customer is not None and customer.get("name") == own_name(run, "客戶")

    if run.path == "sales":
        o = row(w["orders"], result_of("order"))
        own = (
            o
            if o is not None
            and buyer is not None
            and o.get("learning_run_id") == run.run_id
            and o.get("buyer_wallet_id") == buyer["id"]
            else None
        )
        receive = checkpoint("receive")
        product = (
            row(w["products"], receive.payload.get("product_id")) if receive else None
        ) or sale_product(w)
        suffix = f" · {product['name']}" if product else ""
        return [
            _fact("本輪顧客", f"{1 if own_customer else 0} 位"),
            _fact("本輪訂單", f"{1 if own else 0} 筆"),
            _fact("本輪訂單已付款", money((own or {}).get("paid_minor") or 0)),
            _fact("本輪已出貨", f"{_sum((own or {}).get('lines') or [], 'shipped_quantity')} 件"),
            _fact(f"共用商品現有量{suffix}", f"{(product or {}).get('on_hand') or 0} 件"),
            _fact("共用商品預留", f"{(product or {}).get('reserved') or 0} 件"),
            *common,
        ]
    if run.path == "service":
        case = row(w["cases"], result_of("case"))
        own_case = (
            case
            if case is not None
            and customer is not None
            and case.get("title") == own_name(run, "服務案件")
            and case.get("customer_id") == customer["id"]
            else None
        )
        q = row(w["quotes"], result_of("quote"))
        service = row(w["services"], result_of("service"))
        own_service = (
            service
            if service is not None
            and own_case is not None
            and service.get("case_id") == own_case["id"]
            else None
        )
        own_quote = q is not None and own_case is not None and q.get("case_id") == own_case["id"]
        return [
            _fact("本輪案件", f"{1 if own_case else 0} 件"),
            _fact("本輪報價", f"{1 if own_quote else 0} 份"),
            _fact("本輪交付版本", f"{len((own_service or {}).get('deliveries') or [])} 份"),
            _fact(
                "本輪已驗收服務",
                f"{1 if own_service and own_service.get('status') == 'accepted' else 0} 件",
            ),
            _fact("本輪服務收款", money((own_service or {}).get("paid_minor") or 0)),
            *common,
        ]
    o = row(w["work_orders"], result_of("work-order"))
    own = o if o is not None and o.get("learning_run_id") == run.run_id else None
    receive = checkpoint("receive")
    bom: dict[str, Any] | None = (own or {}).get("bom_snapshot")
    if not bom and receive is not None:
        bom = next(
            (
                b
                for b in w["boms"]
                if len(b.get("components") or []) == 1
                and b["components"][0].get("product_id") == receive.payload.get("product_id")
                and b["components"][0].get("quantity") == receive.payload.get("quantity")
            ),
            None,
        )
    if not bom and receive is None:
        bom = single_component_bom(w)
    components = (bom or {}).get("components") or []
    material_id = components[0].get("product_id") if components else None
    if material_id is None and receive is not None:
        material_id = receive.payload.get("product_id")
    material = row(w["products"], material_id)
    finished = row(w["products"], (bom or {}).get("product_id"))
    completed = own is not None and own.get("status") == "completed"
    return [
        _fact("本輪工單", f"{1 if own else 0} 張"),
        _fact("本輪完工數量", f"{own['quantity'] if completed and own else 0} 件"),
        _fact(
            "本輪完工成本", money(((own or {}).get("actual_cost_minor") or 0) if completed else 0)
        ),
        _fact(
            f"共用材料現有量{' · ' + material['name'] if material else ''}",
            f"{(material or {}).get('on_hand') or 0} 件",
        ),
        _fact(
            f"共用成品現有量{' · ' + finished['name'] if finished else ''}",
            f"{(finished or {}).get('on_hand') or 0} 件",
        ),
        _fact("共用材料預留", f"{(material or {}).get('reserved') or 0} 件"),
        _fact("共用商家測試幣", business),
    ]


def _workspace_facts(w: World, run: Run, business: str) -> list[Fact]:
    buyers = (v for v in w["wallets"] if v.get("kind") == "buyer")
    common = [
        _fact("工作區商家測試幣", business),
        _fact("工作區買家測試幣", money(_sum(buyers, "balance_minor"))),
    ]
    products = w["products"]
    if run.path == "sales":
        orders = w["orders"]
        shipped = sum(_sum(o.get("lines") or [], "shipped_quantity") for o in orders)
        return [
            _fact("工作區顧客", f"{len(w['customers'])} 位"),
            _fact("工作區商品現有量", f"{_sum(products, 'on_hand')} 件"),
            _fact("工作區預留庫存", f"{_sum(products, 'reserved')} 件"),
            _fact("工作區訂單", f"{len(orders)} 筆"),
            _fact("工作區訂單已付款", money(_sum(orders, "paid_minor"))),
            _fact("工作區已出貨", f"{shipped} 件"),
            *common,
        ]
    if run.path == "service":
        services = w["services"]
        deliveries = sum(len(v.get("deliveries") or []) for v in services)
        accepted = sum(1 for v in services if v.get("status") == "accepted")
        return [
            _fact("工作區案件", f"{len(w['cases'])} 件"),
            _fact("工作區報價", f"{len(w['quotes'])} 份"),
            _fact("工作區交付版本", f"{deliveries} 份"),
            _fact("工作區已驗收服務", f"{accepted} 件"),
            _fact("工作區服務收款", money(_sum(services, "paid_minor"))),
            *common,
        ]
    completed = [v for v in w["work_orders"] if v.get("status") == "completed"]
    return [
        _fact("工作區庫存現有量", f"{_sum(products, 'on_hand')} 件"),
        _fact("工作區預留庫存", f"{_sum(products, 'reserved')} 件"),
        _fact("工作區庫存成本", money(_sum(products, "stock_value_minor"))),
        _fact("工作區 BOM 版本", f"{len(w['boms'])} 份"),
        _fact("工作區完工工單", f"{len(completed)} 張"),
        _fact("工作區完工數量", f"{_sum(completed, 'quantity')} 件"),
        *common,
    ]


def snapshot_rows(before: list[Fact], after: list[Fact]) -> list[dict[str, str]]:
    """前後讀值對照：以標籤「 ·」之前的文字配對，找不到時為「—」，至多 12 列。"""

    def key(label: str) -> str:
        return label.split(" ·")[0]

    previous = {key(f["label"]): f["value"] for f in before}
    return [
        {"label": f["label"], "before": previous.get(key(f["label"]), "—"), "after": f["value"]}
        for f in after[:FACT_ROWS_MAX]
    ]
