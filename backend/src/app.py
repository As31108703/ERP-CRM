from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from src.config.settings import Settings
from src.core.db import make_engine
from src.middleware.errors import register_error_handlers
from src.middleware.headers import SecurityHeadersMiddleware
from src.middleware.session import SessionCookieMiddleware

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
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # 引擎採延遲連線，建立 app 時不會連資料庫
    engine = make_engine(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="星軌 ERP-CRM", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionCookieMiddleware)
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
