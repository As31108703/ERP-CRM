from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from src.config.settings import Settings

APP_NAME = "erpcrm"
APP_VERSION = "0.1.0"

health_router = APIRouter()


@health_router.get("/api/health")
def health() -> JSONResponse:
    # 安全標頭於 Task 2 改由 middleware 統一加上，這裡先手動設定
    return JSONResponse(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "simulation": True,
            "real_finance": False,
            "currency": "SIM",
        },
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


# 新模組的 router 加在這個清單即可，create_app 會依序掛上
ROUTERS: list[APIRouter] = [
    health_router,
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="星軌 ERP-CRM", version=APP_VERSION)
    app.state.settings = settings
    for router in ROUTERS:
        app.include_router(router)
    return app
