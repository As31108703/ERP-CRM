"""`GET /api/templates`：範本目錄與部署預設值（不需要 session）。"""

from typing import Any

from fastapi import APIRouter, Request

from src.config.settings import Settings
from src.modules.catalog.templates import TEMPLATES, known_modules
from src.modules.workspace.retention import RETENTION_HOURS

router = APIRouter()


def template_defaults(settings: Settings) -> dict[str, Any]:
    app = settings.app
    return {
        "industry": app.default_industry,
        "company_name": app.default_company,
        "modules": known_modules(app.default_modules),
        "public_demo": app.public_demo,
        "auto_setup": not app.public_demo and app.auto_setup,
        "retention_hours": RETENTION_HOURS if app.public_demo else None,
    }


@router.get("/api/templates")
def list_templates(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "items": [t.public() for t in TEMPLATES.values()],
        "defaults": template_defaults(settings),
    }
