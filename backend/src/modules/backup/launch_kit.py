"""本機啟動包：把建置精靈的選擇寫成 `.env` 與啟動腳本，打包成 zip 讓使用者放到 repo 根目錄。

參數檢查沿用本機啟動設定的規則（B§7 normalizeLaunchConfig），只檢查產業、公司名稱與模組三項：
產業須為已知範本；公司名稱去頭尾空白後 1–100 字且不含控制字元；模組未指定時用範本預設，
指定時須非空、不重複、皆為已知模組且相依齊全。
"""

import io
import json
import re
import zipfile

from src.core.problem import ensure
from src.modules.catalog.templates import get_template, resolve_modules
from src.modules.workspace.service import NAME_MAX

LAUNCH_KIT_FILENAME = "erpcrm-launch-kit.zip"
_CONTROL_RE = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
# zip 內檔案的固定時間，讓同樣的設定產生相同內容
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def normalize(industry: str | None, company_name: str | None, modules: str | None) -> dict:
    template = get_template(industry)
    name = company_name.strip() if isinstance(company_name, str) else ""
    ensure(
        0 < len(name) <= NAME_MAX and _CONTROL_RE.search(name) is None,
        422,
        "name_invalid",
        "請填店名（1 到 100 字，不含控制字元）",
    )
    selected = None if modules is None else modules.split(",")
    ensure(selected is None or selected != [""], 422, "module_invalid", "請至少啟用一個模組")
    return {
        "industry": template.id,
        "company_name": name,
        "modules": resolve_modules(template.id, selected),
    }


def _env_value(value: str) -> str:
    """docker compose 的 env_file 寫法：沒有單引號時用單引號（內容原樣）；否則用雙引號並跳脫
    反斜線、雙引號與 `$`（`$$` 代表字面上的 `$`）。"""
    if "'" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
    return f'"{escaped}"'


def _env(config: dict) -> str:
    modules = json.dumps(config["modules"], separators=(",", ":"))
    lines = [
        "# 星軌 ERP-CRM 本機啟動設定（由啟動包產生）",
        "# 資料庫（docker compose 內的 db 服務）",
        "DATABASE__HOST=db",
        "DATABASE__PORT=5432",
        "DATABASE__USER=erpcrm",
        "DATABASE__PASSWORD=erpcrm",
        "DATABASE__NAME=erpcrm",
        "",
        "# 應用設定：私人模式、第一次開啟時自動以下列預設建立工作區",
        "APP__PUBLIC_DEMO=false",
        "APP__AUTO_SETUP=true",
        "APP__ALLOWED_ORIGINS=[]",
        f"APP__DEFAULT_INDUSTRY={config['industry']}",
        f"APP__DEFAULT_COMPANY={_env_value(config['company_name'])}",
        f"APP__DEFAULT_MODULES={modules}",
        "",
    ]
    return "\n".join(lines)


START_SH = """#!/bin/sh
# 星軌 ERP-CRM：在 repo 根目錄以 docker compose 建置並啟動
set -e
cd "$(dirname "$0")"
docker compose up -d --build
"""

START_CMD = """@echo off
rem 星軌 ERP-CRM：在 repo 根目錄以 docker compose 建置並啟動
cd /d "%~dp0"
docker compose up -d --build
"""


def _readme(config: dict) -> str:
    return "\n".join(
        [
            "星軌 ERP-CRM 本機啟動包",
            "",
            f"產業範本：{config['industry']}",
            f"公司名稱：{config['company_name']}",
            f"啟用模組：{'、'.join(config['modules'])}",
            "",
            "使用方式：",
            "1. 解壓縮後，把 .env、start.sh、start.cmd 放到 repo 根目錄"
            "（與 docker-compose.yaml 同一層）。",
            "   根目錄已有 .env 時會被覆蓋，請先備份。",
            "2. 確認已安裝並啟動 Docker（需支援 docker compose）。",
            "3. macOS／Linux 執行 ./start.sh；Windows 執行 start.cmd。",
            "4. 啟動完成後用瀏覽器開啟前端網址，第一次開啟會自動以上述設定建立模擬工作區。",
            "",
            "所有金額都是 SIM 模擬幣，不連接任何真實金流。",
            "",
        ]
    )


def _add(zf: zipfile.ZipFile, name: str, content: str, mode: int = 0o644) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o100000 | mode) << 16
    zf.writestr(info, content.encode("utf-8"))


def build(config: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        _add(zf, ".env", _env(config))
        _add(zf, "start.sh", START_SH, 0o755)
        _add(zf, "start.cmd", START_CMD.replace("\n", "\r\n"))
        _add(zf, "README.txt", _readme(config))
    return buffer.getvalue()
