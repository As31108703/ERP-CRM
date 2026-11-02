from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from src.config.settings import Settings
from src.core.db import make_engine
from src.middleware.errors import register_error_handlers
from src.middleware.headers import SecurityHeadersMiddleware
from src.middleware.session import SessionCookieMiddleware
from src.modules.administration.router import router as administration_router
from src.modules.backup.router import router as backup_router
from src.modules.catalog.router import router as catalog_router
from src.modules.crm.router import router as crm_router
from src.modules.inventory.router import router as inventory_router
from src.modules.learning.router import router as learning_router
from src.modules.manufacturing.router import router as manufacturing_router
from src.modules.projects.router import router as projects_router
from src.modules.reports.router import router as reports_router
from src.modules.sales.router import router as sales_router
from src.modules.services.router import router as services_router
from src.modules.wallets.router import router as wallets_router
from src.modules.workbench.router import router as workbench_router
from src.modules.workspace.retention import start_scheduler
from src.modules.workspace.router import router as workspace_router

APP_NAME = "erpcrm"
APP_VERSION = "0.1.0"

health_router = APIRouter()


@health_router.get("/api/health")
def health() -> dict[str, object]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "simulation": True,
        "real_finance": False,
        "currency": "SIM",
    }


# 新模組的 router 加在這個清單即可，create_app 會依序掛上
ROUTERS: list[APIRouter] = [
    health_router,
    catalog_router,
    workspace_router,
    # 匯入 router 時一併登錄模組（快照、一致性檢查、seed）。登錄先後不影響執行順序：
    # 快照、一致性檢查與還原依 registry.SPEC_ORDER，seed 依 register_seeder 的 order
    wallets_router,
    inventory_router,
    sales_router,
    crm_router,
    services_router,
    manufacturing_router,
    projects_router,
    administration_router,
    reports_router,
    workbench_router,
    backup_router,
    learning_router,
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # 引擎採延遲連線，建立 app 時不會連資料庫
    engine = make_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 兩種模式都清除從未寫入的 session；72 小時保留只在公開展示模式
        app.state.scheduler = start_scheduler(engine, public_demo=settings.app.public_demo)
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)
            engine.dispose()

    app = FastAPI(title="星軌 ERP-CRM", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.scheduler = None
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionCookieMiddleware)
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
