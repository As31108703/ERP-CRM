"""產業範本目錄：8 個範本的模組、術語與示範資料，以及建立工作區時的模組檢查。"""

from typing import Any

from pydantic import BaseModel

from src.core.problem import Problem, ensure
from src.platform.registry import MODULE_DEPENDENCIES, MODULES

DEFAULT_CONFIG: dict[str, Any] = {"currency": "SIM", "simulation": True, "real_finance": False}


class Terminology(BaseModel):
    customer: str
    product: str
    work_order: str


class Sample(BaseModel):
    sku: str
    product: str
    customer: str
    service: str
    component: str
    price_minor: int
    cost_minor: int
    bom_quantity: int | None = None
    milestone: str | None = None
    task: str | None = None


class Template(BaseModel):
    id: str
    name: str
    purpose: str
    modules: list[str]
    terminology: Terminology
    sample: Sample
    version: int = 1

    def public(self) -> dict[str, Any]:
        """`GET /api/templates` 的單一範本：未設定的選填示範欄位不輸出。"""
        out = self.model_dump(exclude_none=True)
        out["module_dependencies"] = {k: list(v) for k, v in MODULE_DEPENDENCIES.items()}
        out["default_config"] = dict(DEFAULT_CONFIG)
        return out


_COMMERCE = ["inventory", "sales", "wallets", "crm"]
_CRAFT = ["inventory", "sales", "wallets", "crm", "manufacturing"]
_SERVICE = ["services", "wallets", "crm", "projects"]


def _t(
    id: str,
    name: str,
    purpose: str,
    modules: list[str],
    terms: tuple[str, str, str],
    sample: dict[str, Any],
    version: int = 1,
) -> Template:
    customer, product, work_order = terms
    return Template(
        id=id,
        name=name,
        purpose=purpose,
        modules=list(modules),
        terminology=Terminology(customer=customer, product=product, work_order=work_order),
        sample=Sample(**sample),
        version=version,
    )


_ALL: list[Template] = [
    _t(
        "retail",
        "零售商店",
        "練習店內銷售、庫存預留與退貨",
        _COMMERCE,
        ("顧客", "零售商品", "製作單"),
        {
            "sku": "SHOP-MUG-001",
            "product": "示範陶瓷杯",
            "customer": "社區顧客林小姐",
            "service": "商品客製服務",
            "component": "杯體材料",
            "price_minor": 35000,
            "cost_minor": 16000,
        },
    ),
    _t(
        "wholesale",
        "批發商",
        "練習箱裝進貨、批發客戶與出貨追蹤",
        _COMMERCE,
        ("經銷客戶", "箱裝商品", "製作單"),
        {
            "sku": "WHOLE-BOX-001",
            "product": "示範清潔用品箱（12瓶）",
            "customer": "示範經銷商",
            "service": "經銷合作",
            "component": "示範包裝材料",
            "price_minor": 240000,
            "cost_minor": 150000,
        },
    ),
    _t(
        "service",
        "服務工作室",
        "練習客戶、報價、交付、驗收與測試幣付款",
        _SERVICE,
        ("委託客戶", "參考商品", "工作單"),
        {
            "sku": "SERVICE-REF-001",
            "product": "服務參考方案",
            "customer": "品牌委託客戶",
            "service": "網站視覺設計",
            "component": "參考素材",
            "price_minor": 3000000,
            "cost_minor": 0,
        },
    ),
    _t(
        "restaurant",
        "餐飲店",
        "以配方BOM練習食材預留、餐點製作與模擬銷售；不含食安管理",
        _CRAFT,
        ("用餐顧客", "餐點", "餐點製作單"),
        {
            "sku": "MENU-TEA-001",
            "product": "示範冷泡茶",
            "customer": "常客陳先生",
            "service": "活動餐飲服務",
            "component": "茶包（份）",
            "price_minor": 8000,
            "cost_minor": 2500,
            "bom_quantity": 1,
        },
    ),
    _t(
        "manufacturing",
        "製造工廠",
        "練習版本化BOM、原料FIFO、開工及完工成本轉移",
        _CRAFT,
        ("採購客戶", "成品", "生產工單"),
        {
            "sku": "FG-BRACKET-001",
            "product": "示範金屬支架",
            "customer": "設備採購公司",
            "service": "工程打樣",
            "component": "鋼料片（件）",
            "price_minor": 120000,
            "cost_minor": 60000,
            "bom_quantity": 2,
        },
    ),
    _t(
        "ecommerce",
        "電商",
        "練習品牌商品、顧客、模擬付款與分批出貨；沒有物流串接",
        _COMMERCE,
        ("網店顧客", "品牌商品", "製作單"),
        {
            "sku": "WEB-TOTE-001",
            "product": "示範品牌帆布袋",
            "customer": "網店顧客王小姐",
            "service": "品牌售後服務",
            "component": "包材",
            "price_minor": 49000,
            "cost_minor": 22000,
        },
    ),
    _t(
        "projects",
        "專案公司",
        "練習案件、待辦、里程碑與交付；不含工時薪資",
        _SERVICE,
        ("專案客戶", "參考方案", "任務"),
        {
            "sku": "PROJECT-REF-001",
            "product": "系統建置參考方案",
            "customer": "企業專案委託方",
            "service": "內部系統原型建置",
            "component": "參考元件",
            "price_minor": 10000000,
            "cost_minor": 0,
            "milestone": "原型驗收",
            "task": "確認需求與交付範圍",
        },
    ),
    _t(
        "general",
        "一般企業",
        "探索已實作模組，作為自訂範本起點",
        list(MODULES),
        ("客戶", "商品", "製作單"),
        {
            "sku": "DEMO-001",
            "product": "示範成品",
            "customer": "示範企業客戶",
            "service": "示範顧問服務",
            "component": "示範材料",
            "price_minor": 10000,
            "cost_minor": 5000,
        },
        version=2,
    ),
]

TEMPLATES: dict[str, Template] = {t.id: t for t in _ALL}


def get_template(industry: object) -> Template:
    """找不到範本時拋出 422 industry_invalid。"""
    template = TEMPLATES.get(industry) if isinstance(industry, str) else None
    if template is None:
        raise Problem(422, "industry_invalid", "無效產業範本")
    return template


def resolve_modules(industry: str, modules: list[str] | None) -> list[str]:
    """依範本決定啟用模組：未指定時用範本預設；指定時須為不重複的已知模組且相依齊全。"""
    template = get_template(industry)
    selected: object = template.modules if modules is None else modules
    if not (
        isinstance(selected, list)
        and all(isinstance(m, str) and m in MODULES for m in selected)
        and len(set(selected)) == len(selected)
    ):
        raise Problem(422, "module_invalid", "無效模組")
    for m in selected:
        deps = MODULE_DEPENDENCIES.get(m, [])
        ensure(
            all(dep in selected for dep in deps),
            422,
            "module_dependency",
            f"{m} 需要 {'、'.join(deps)}",
        )
    return list(selected)


def known_modules(names: list[str] | None) -> list[str] | None:
    """`defaults.modules`：只保留出現在任何範本中的模組名稱；未設定時為 None。"""
    if names is None:
        return None
    used = {m for t in _ALL for m in t.modules}
    return [n for n in names if n in used]
