"""三條教學路線：步驟文案、命令、payload 產生規則、前置條件與阻擋原因。

`prepare` 以「工作區讀值」`w`（各模組快照的集合，見 evidence.load_world）與目前這一輪的
`Run` 產生下一步的命令；呼叫端負責先確認這一步確實是下一個未完成的步驟。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.core import clock

World = dict[str, Any]


@dataclass(frozen=True)
class LearningStep:
    id: str
    action: str
    title: str
    body: str
    change: str
    nav: str
    node: str

    def public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "action": self.action,
            "title": self.title,
            "body": self.body,
            "change": self.change,
            "nav": self.nav,
            "node": self.node,
        }


@dataclass(frozen=True)
class Quiz:
    question: str
    choices: tuple[str, str, str]
    answer: int
    explanation: str


@dataclass(frozen=True)
class LearningPath:
    id: str
    title: str
    subtitle: str
    modules: tuple[str, ...]
    headline: str
    intro: str
    outcome: str
    nodes: tuple[str, ...]
    steps: tuple[LearningStep, ...]
    quiz: Quiz

    def step(self, step_id: str) -> LearningStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def index(self, step_id: str) -> int:
        return next(i for i, s in enumerate(self.steps) if s.id == step_id)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "modules": list(self.modules),
            "headline": self.headline,
            "intro": self.intro,
            "outcome": self.outcome,
            "nodes": list(self.nodes),
            "steps": [s.public() for s in self.steps],
            "quiz": {
                "question": self.quiz.question,
                "choices": list(self.quiz.choices),
                "answer": self.quiz.answer,
                "explanation": self.quiz.explanation,
            },
        }


@dataclass(frozen=True)
class Checkpoint:
    step_id: str
    action: str
    payload: dict[str, Any]
    result: str
    version: int

    def public(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "payload": self.payload,
            "result": self.result,
            "version": self.version,
        }


@dataclass
class Run:
    """一輪練習：路線、教學識別與依版本排序的檢查點。"""

    path: str
    run_id: str
    checkpoints: list[Checkpoint] = field(default_factory=list)

    def cp(self, step_id: str) -> Checkpoint | None:
        return next((c for c in self.checkpoints if c.step_id == step_id), None)


@dataclass(frozen=True)
class Command:
    action: str
    payload: dict[str, Any]
    preview: str


@dataclass(frozen=True)
class Blocked:
    reason: str


def _s(id: str, action: str, title: str, body: str, change: str, nav: str, node: str):
    return LearningStep(id, action, title, body, change, nav, node)


SALES = LearningPath(
    id="sales",
    title="把第一筆訂單送出去",
    subtitle="從顧客到出貨，練習一筆完整的模擬交易。",
    modules=("crm", "wallets", "inventory", "sales"),
    headline="把一筆訂單，走到出貨。",
    intro="先備好商品和測試幣，再看訂單如何保留庫存、收款與出貨。每一步都會留下可以核對的紀錄。",
    outcome="你會看見：付款不會移動庫存，出貨才會扣除 FIFO 成本層。",
    nodes=("wallet", "inventory", "order", "inventory"),
    steps=(
        _s(
            "customer",
            "customer.create",
            "建立練習顧客",
            "建立本次教學專用顧客，方便辨認這次練習。",
            "新增一位顧客。",
            "crm",
            "customer",
        ),
        _s(
            "buyer",
            "wallet.create",
            "建立買家錢包",
            "建立本次專用錢包，稍後用它支付測試幣。",
            "新增餘額為零的買家錢包。",
            "wallets",
            "wallet",
        ),
        _s(
            "fund-business",
            "wallet.fund",
            "準備進貨測試幣",
            "明確補充商家測試幣，供下一步進貨使用。",
            "補入本次採購所需 SIM，補幣流水同步建立。",
            "wallets",
            "wallet",
        ),
        _s(
            "receive",
            "inventory.receive",
            "進貨一件商品",
            "採用一件啟用中的商品，成本依目前商品設定。",
            "庫存增加一件，留下採購與 FIFO 成本層。",
            "inventory",
            "inventory",
        ),
        _s(
            "fund-buyer",
            "wallet.fund",
            "準備買家測試幣",
            "補入恰好等於這件商品售價的測試幣。",
            "本次買家錢包增加本筆售價。",
            "wallets",
            "wallet",
        ),
        _s(
            "order",
            "order.create",
            "建立訂單",
            "只用本次專用買家與剛進貨的商品建立一件訂單。",
            "建立訂單並預留一件庫存。",
            "sales",
            "order",
        ),
        _s(
            "pay",
            "order.pay",
            "付清訂單",
            "用本次買家錢包付清這筆模擬訂單。",
            "測試幣移至商家，訂單付款狀態更新。",
            "sales",
            "order",
        ),
        _s(
            "ship",
            "order.ship",
            "出貨",
            "付款完成後，把本筆訂單的一件商品出貨。",
            "庫存與預留各減一件，出貨成本採 FIFO。",
            "sales",
            "inventory",
        ),
    ),
    quiz=Quiz(
        question="建立訂單後，保留庫存代表什麼？",
        choices=(
            "已經出貨，商品離開庫存",
            "保留給這筆訂單，現有量還沒有減少",
            "買家已經付清測試幣",
        ),
        answer=1,
        explanation=(
            "建立訂單會保留數量，可用庫存因此減少，現有量維持不變。全額模擬付款後才能出貨；"
            "出貨時才扣除現有量與 FIFO 成本。"
        ),
    ),
)

MANUFACTURING = LearningPath(
    id="manufacturing",
    title="把材料做成成品",
    subtitle="沿著一份 BOM，練習預留材料、開工與完工。",
    modules=("manufacturing", "inventory", "wallets"),
    headline="把材料，變成一件成品。",
    intro=(
        "沿用範本中的材料與 BOM，採購這次需要的材料，再依序備料、開工與完工。"
        "看庫存數量和材料成本如何一起移動。"
    ),
    outcome="你會看見：備料保留材料，完工才消耗材料，並把成本帶進成品。",
    nodes=("inventory", "bom", "production", "inventory"),
    steps=(
        _s(
            "fund-business",
            "wallet.fund",
            "準備材料測試幣",
            "明確補充商家測試幣，用於本次材料採購。",
            "補入本次材料採購所需 SIM。",
            "wallets",
            "wallet",
        ),
        _s(
            "receive",
            "inventory.receive",
            "採購本次材料",
            "教學採用只有一種元件的 BOM；多元件請先在製造模組練習。",
            "材料數量增加，留下採購成本層。",
            "inventory",
            "inventory",
        ),
        _s(
            "work-order",
            "workOrder.create",
            "建立製作單",
            "建立本次專屬工單，計畫製作一件成品。",
            "工單凍結 BOM 版本，狀態為計畫中。",
            "manufacturing",
            "production",
        ),
        _s(
            "reserve",
            "workOrder.reserve",
            "預留材料",
            "檢查材料足夠後，預留本次工單需要的數量。",
            "可用材料減少，實際庫存尚未扣除。",
            "manufacturing",
            "inventory",
        ),
        _s(
            "start",
            "workOrder.start",
            "開始製作",
            "把本次工單從已預留推進至製作中。",
            "工單進入製作中。",
            "manufacturing",
            "production",
        ),
        _s(
            "complete",
            "workOrder.complete",
            "完成製作",
            "依 FIFO 消耗材料，將成本完整轉入一件成品。",
            "材料減少、成品增加；測試幣流水不因製作改動。",
            "manufacturing",
            "inventory",
        ),
    ),
    quiz=Quiz(
        question="工單備料後，材料什麼時候真正被消耗？",
        choices=("備料時", "開工時", "完工入庫時"),
        answer=2,
        explanation=(
            "備料會保留材料，開工會更新工單狀態。完工才消耗材料的 FIFO 成本層，"
            "並把材料成本轉入成品庫存。取消未完工工單會釋放保留量。"
        ),
    ),
)

SERVICE = LearningPath(
    id="service",
    title="完成一件服務委託",
    subtitle="從案件、報價到交付驗收，最後收取測試幣。",
    modules=("crm", "services", "wallets"),
    headline="讓交付有版本，讓驗收有依據。",
    intro="從案件開始，把需求變成報價、服務與交付。核對最新版本後，再完成模擬驗收和付款。",
    outcome="你會看見：交付與驗收對應同一個最新版本，測試幣付款接在驗收之後。",
    nodes=("case", "quote", "service", "delivery", "wallet"),
    steps=(
        _s(
            "customer",
            "customer.create",
            "建立委託客戶",
            "建立本次服務練習專用客戶。",
            "新增一位客戶。",
            "crm",
            "customer",
        ),
        _s(
            "case",
            "case.create",
            "建立服務案件",
            "把本次客戶與新案件連在一起。",
            "新增本次教學案件。",
            "crm",
            "case",
        ),
        _s(
            "quote",
            "quote.create",
            "起草模擬報價",
            "本次以 1,000 SIM 示範報價，有效期限為七天。",
            "新增報價草稿，沒有正式契約效力。",
            "crm",
            "quote",
        ),
        _s(
            "issue",
            "quote.issue",
            "發出報價",
            "發出本次報價，金額與有效期限將凍結。",
            "產生報價摘要，同案件舊報價會失效。",
            "crm",
            "quote",
        ),
        _s(
            "confirm-quote",
            "quote.confirm",
            "確認最新報價",
            "只使用本次最新報價的摘要確認。",
            "留下模擬確認，沒有法律效力。",
            "crm",
            "quote",
        ),
        _s(
            "service",
            "service.create",
            "建立模擬服務",
            "沿用本次案件與已確認報價金額。",
            "新增服務草稿，價格來源為明確的模擬輸入。",
            "services",
            "service",
        ),
        _s(
            "confirm-service",
            "service.confirm",
            "確認服務內容",
            "將本次服務推進到可提交交付物的狀態。",
            "服務狀態更新為已確認。",
            "services",
            "service",
        ),
        _s(
            "deliver",
            "service.deliver",
            "提交教學交付物",
            "提交本次專用的教學交付標記。",
            "新增交付版本與摘要，等待模擬驗收。",
            "services",
            "delivery",
        ),
        _s(
            "accept",
            "service.accept",
            "驗收最新交付",
            "核對最新交付識別與摘要後驗收。",
            "服務標記為已驗收。",
            "services",
            "delivery",
        ),
        _s(
            "buyer",
            "wallet.create",
            "建立付款錢包",
            "建立本次委託方專用的測試幣錢包。",
            "新增餘額為零的買家錢包。",
            "wallets",
            "wallet",
        ),
        _s(
            "fund-buyer",
            "wallet.fund",
            "準備服務測試幣",
            "補入恰好等於服務金額的測試幣。",
            "本次買家收到 1,000 SIM。",
            "wallets",
            "wallet",
        ),
        _s(
            "pay",
            "service.pay",
            "支付服務測試幣",
            "只對本次已驗收服務支付測試幣。",
            "服務收款更新，錢包流水保持守恆。",
            "services",
            "wallet",
        ),
    ),
    quiz=Quiz(
        question="補交一個新版本後，應驗收哪個版本？",
        choices=("第一個版本，因為最早提交", "任意一個已提交版本", "最新交付版本及其正確摘要"),
        answer=2,
        explanation=(
            "系統只接受最新交付與正確摘要。補交會更新最新版本；已收取測試幣的服務不能再改交付。"
            "這些確認只供模擬流程。"
        ),
    ),
)

# 定義順序即 available_paths 的順序
PATHS: dict[str, LearningPath] = {p.id: p for p in (SALES, MANUFACTURING, SERVICE)}

QUOTE_AMOUNT = 100_000
QUOTE_DAYS = 7

BLOCKED_INVALID = "教學紀錄無效或工作區已更換，請開始新練習。"
BLOCKED_COMPLETE = "本次教學已完成，請開始另一輪練習。"
BLOCKED_ORDER = "請先完成目前這一步，不會跳過前面的操作。"
BLOCKED_NOT_STARTED = "尚未開始這條教學路線，請先開始練習。"


# --- 讀值工具 ---------------------------------------------------------------------------------


def money(n: int) -> str:
    """minor 轉成 SIM 顯示：千分位、最多兩位小數，例如 `1,000 SIM`、`3.5 SIM`。"""
    value = n / 100
    if value == int(value):
        text = f"{int(value):,}"
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{text} SIM"


def row(items: list[dict[str, Any]] | None, id: Any) -> dict[str, Any] | None:
    if id is None or not items:
        return None
    return next((v for v in items if v.get("id") == id), None)


def is_int(n: Any) -> bool:
    return isinstance(n, int) and not isinstance(n, bool)


def own_name(run: Run, kind: str) -> str:
    return f"教學{kind} {run.run_id}"


def business_wallet(w: World) -> dict[str, Any] | None:
    return next((v for v in w["wallets"] if v.get("kind") == "business"), None)


def sale_product(w: World) -> dict[str, Any] | None:
    """第一件啟用中、售價大於 0 的商品。"""
    return next(
        (
            p
            for p in w["products"]
            if p.get("active") and is_int(p.get("price_minor")) and p["price_minor"] > 0
        ),
        None,
    )


def single_component_bom(w: World) -> dict[str, Any] | None:
    """第一份成品啟用、且只有一項啟用中材料的 BOM。"""
    for b in w["boms"]:
        finished = row(w["products"], b.get("product_id"))
        components = b.get("components") or []
        if finished and finished.get("active") and len(components) == 1:
            material = row(w["products"], components[0].get("product_id"))
            if material and material.get("active"):
                return b
    return None


def _available(p: dict[str, Any]) -> int:
    return int(p.get("on_hand") or 0) - int(p.get("reserved") or 0)


def _expired(expires_at: Any, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(expires_at)) <= now
    except ValueError:
        return True


# --- 命令產生 ---------------------------------------------------------------------------------


def _preview(w: World, run: Run, step: LearningStep, payload: dict[str, Any]) -> str:
    sid = step.id
    product = _lesson_product(w, run)
    if sid == "customer":
        return "新增本次專用客戶，保留現有客戶資料。"
    if sid == "buyer":
        return "新增本次專用買家錢包，起始餘額為 0 SIM。"
    if step.action == "wallet.fund":
        who = "商家錢包" if sid == "fund-business" else "本次買家錢包"
        return f"{who}增加 {money(payload['amount_minor'])}，留下補幣流水。"
    if sid == "receive":
        p = row(w["products"], payload["product_id"]) or {}
        cost = int(p.get("cost_minor") or 0) * payload["quantity"]
        name = p.get("name") or "本次材料"
        return f"採購「{name}」{payload['quantity']} 件，商家支付 {money(cost)} 測試幣。"
    if sid == "order":
        name = (product or {}).get("name") or "本次商品"
        price = money((product or {}).get("price_minor") or 0)
        return f"新增一筆「{name}」訂單，數量 1 件，售價 {price}。"
    if sid == "work-order":
        b = row(w["boms"], payload["bom_id"]) or {}
        finished = row(w["products"], b.get("product_id")) or {}
        name = finished.get("name") or "本次成品"
        return f"新增「{name}」製作單，計畫製作 1 件；沿用 BOM 第 {b.get('revision') or 1} 版。"
    if sid == "quote":
        return "新增 1,000 SIM 模擬報價草稿，有效期限七天。"
    if sid == "service":
        return f"新增本次服務草稿，金額 {money(payload['amount_minor'])}，沿用本次案件。"
    if sid == "pay":
        kind = "訂單" if run.path == "sales" else "服務"
        return f"本次買家支付 {money(payload['amount_minor'])} 測試幣，留下{kind}收款流水。"
    return step.change


def _lesson_product(w: World, run: Run) -> dict[str, Any] | None:
    receive = run.cp("receive")
    if receive is not None:
        return row(w["products"], receive.payload.get("product_id"))
    return sale_product(w)


def prepare(w: World, run: Run, step: LearningStep, now: datetime) -> Command | Blocked:
    """產生 `step` 的命令與預覽；前置條件不成立時回傳阻擋原因。"""
    payload = _payload(w, run, step, now)
    if isinstance(payload, Blocked):
        return payload
    return Command(step.action, payload, _preview(w, run, step, payload))


def _payload(w: World, run: Run, step: LearningStep, now: datetime) -> dict[str, Any] | Blocked:
    sid = step.id
    c = run.cp
    business = business_wallet(w)
    buyer_cp = c("buyer")
    buyer = row(w["wallets"], buyer_cp.result) if buyer_cp else None
    product = _lesson_product(w, run)
    bom = single_component_bom(w)

    if sid == "customer":
        return {"name": own_name(run, "客戶")}
    if sid == "buyer":
        return {"name": own_name(run, "買家"), "kind": "buyer"}
    if sid == "fund-business":
        if business is None:
            return Blocked("商家錢包不存在，請檢查工作區。")
        cost: Any
        if run.path == "manufacturing":
            if bom is None:
                cost = None
            else:
                component = bom["components"][0]
                material = row(w["products"], component.get("product_id")) or {}
                cost = (
                    material.get("cost_minor") * component["quantity"]
                    if is_int(material.get("cost_minor")) and is_int(component.get("quantity"))
                    else None
                )
        else:
            cost = (product or {}).get("cost_minor")
        if not is_int(cost) or cost < 0:
            return Blocked("找不到可用商品或單元件 BOM，請先在對應模組建立。")
        return {"wallet_id": business["id"], "amount_minor": max(100, cost)}
    if sid == "receive":
        if run.path == "manufacturing":
            if bom is None:
                return Blocked("找不到單元件且成品與材料皆啟用的 BOM；多元件請先在製造模組操作。")
            component = bom["components"][0]
            payload = {"product_id": component["product_id"], "quantity": component["quantity"]}
        else:
            if not product or not product.get("active"):
                return Blocked("找不到啟用中的商品，請先建立商品。")
            payload = {"product_id": product["id"], "quantity": 1}
        received = row(w["products"], payload["product_id"]) or {}
        total = int(received.get("cost_minor") or 0) * payload["quantity"]
        if business is None or business.get("balance_minor", 0) < total:
            return Blocked("商家測試幣不足，請先明確補幣後回來。")
        return payload
    if sid == "fund-buyer":
        if run.path == "sales":
            amount = (product or {}).get("price_minor")
        else:
            service_cp = c("service")
            amount = (
                (row(w["services"], service_cp.result) or {}).get("amount_minor")
                if service_cp
                else None
            )
        if buyer is None or not is_int(amount) or amount <= 0:
            return Blocked("本次買家或付款金額不存在。")
        return {"wallet_id": buyer["id"], "amount_minor": amount}

    if run.path == "sales":
        return _sales_payload(w, run, sid, buyer, product)
    if run.path == "manufacturing":
        return _manufacturing_payload(w, run, sid)
    if run.path == "service":
        return _service_payload(w, run, sid, buyer, now)
    return Blocked("這一步沒有可執行的教學指令。")


def _sales_payload(
    w: World, run: Run, sid: str, buyer: dict[str, Any] | None, product: dict[str, Any] | None
) -> dict[str, Any] | Blocked:
    if sid == "order":
        if buyer is None or not product or not product.get("active") or _available(product) < 1:
            return Blocked("本次買家或可用商品不足，請檢查工作區。")
        return {
            "learning_run_id": run.run_id,
            "buyer_wallet_id": buyer["id"],
            "lines": [{"product_id": product["id"], "quantity": 1}],
        }
    order_cp = run.cp("order")
    o = row(w["orders"], order_cp.result) if order_cp else None
    if o is None:
        return Blocked("找不到本次教學訂單。")
    if sid == "pay":
        if (
            o.get("paid_minor") != 0
            or o.get("status") != "pending"
            or buyer is None
            or buyer.get("balance_minor", 0) < o["total_minor"]
        ):
            return Blocked("本次訂單已變更或買家測試幣不足；請檢查後開始新練習。")
        return {"id": o["id"], "amount_minor": o["total_minor"]}
    if sid == "ship":
        lines = o.get("lines") or []
        if (
            o.get("paid_minor") != o.get("total_minor")
            or not lines
            or lines[0].get("shipped_quantity") != 0
        ):
            return Blocked("本次訂單未付清或已出貨。")
        return {"id": o["id"], "lines": [{"line_id": lines[0]["id"], "quantity": 1}]}
    return Blocked("這一步沒有可執行的教學指令。")


def _manufacturing_payload(w: World, run: Run, sid: str) -> dict[str, Any] | Blocked:
    receive = run.cp("receive")
    if sid == "work-order":
        selected = None
        for b in w["boms"]:
            components = b.get("components") or []
            finished = row(w["products"], b.get("product_id"))
            if (
                receive is not None
                and len(components) == 1
                and components[0].get("product_id") == receive.payload.get("product_id")
                and components[0].get("quantity") == receive.payload.get("quantity")
                and finished
                and finished.get("active")
            ):
                selected = b
                break
        if selected is None:
            return Blocked("找不到本次材料對應的 BOM。")
        return {"learning_run_id": run.run_id, "bom_id": selected["id"], "quantity": 1}
    wo_cp = run.cp("work-order")
    o = row(w["work_orders"], wo_cp.result) if wo_cp else None
    if o is None:
        return Blocked("找不到本次製作單。")
    expected = {"reserve": "planned", "start": "reserved", "complete": "started"}
    if sid not in expected:
        return Blocked("這一步沒有可執行的教學指令。")
    if o.get("status") != expected[sid]:
        return Blocked("本次製作單狀態已變更，請檢查後開始新練習。")
    if sid == "reserve":
        for component in (o.get("bom_snapshot") or {}).get("components") or []:
            p = row(w["products"], component.get("product_id"))
            if p is None or _available(p) < component.get("quantity", 0):
                return Blocked("本次材料不足，請先檢查庫存。")
    return {"id": o["id"]}


def _service_payload(
    w: World, run: Run, sid: str, buyer: dict[str, Any] | None, now: datetime
) -> dict[str, Any] | Blocked:
    c = run.cp
    case_cp, quote_cp, service_cp = c("case"), c("quote"), c("service")
    q = row(w["quotes"], quote_cp.result) if quote_cp else None
    service = row(w["services"], service_cp.result) if service_cp else None
    if sid == "case":
        customer_cp = c("customer")
        return {
            "title": own_name(run, "服務案件"),
            "customer_id": customer_cp.result if customer_cp else None,
            "status": "open",
        }
    if sid == "quote":
        return {
            "case_id": case_cp.result if case_cp else None,
            "amount_minor": QUOTE_AMOUNT,
            "expires_at": clock.iso(now + timedelta(days=QUOTE_DAYS)),
        }
    if sid == "issue":
        if q is None or q.get("status") != "draft":
            return Blocked("本次報價不是草稿。")
        return {"id": q["id"]}
    if sid == "confirm-quote":
        if q is None or q.get("status") != "issued" or _expired(q.get("expires_at"), now):
            return Blocked("本次報價已失效，請開始新練習。")
        return {"id": q["id"], "digest": q.get("digest")}
    if sid == "service":
        if q is None:
            return Blocked("找不到本次報價。")
        return {"case_id": case_cp.result if case_cp else None, "amount_minor": q["amount_minor"]}
    if service is None:
        return Blocked("找不到本次服務。")
    if sid == "confirm-service":
        if service.get("status") != "draft":
            return Blocked("本次服務不是草稿。")
        return {"id": service["id"]}
    if sid == "deliver":
        if service.get("status") != "confirmed":
            return Blocked("本次服務尚未確認或已變更。")
        return {"id": service["id"], "artifact_ref": own_name(run, "交付物")}
    if sid == "accept":
        d = row(service.get("deliveries"), service.get("latest_delivery_id"))
        if (
            service.get("status") != "submitted"
            or d is None
            or d.get("artifact_ref") != own_name(run, "交付物")
        ):
            return Blocked("本次最新交付已變更，請檢查服務。")
        return {"id": service["id"], "delivery_id": d["id"], "digest": d.get("digest")}
    if sid == "pay":
        if (
            service.get("status") != "accepted"
            or service.get("paid_minor") != 0
            or buyer is None
            or buyer.get("balance_minor", 0) < service["amount_minor"]
        ):
            return Blocked("本次服務尚未驗收、已收款或買家測試幣不足。")
        return {
            "id": service["id"],
            "buyer_wallet_id": buyer["id"],
            "amount_minor": service["amount_minor"],
        }
    return Blocked("這一步沒有可執行的教學指令。")
