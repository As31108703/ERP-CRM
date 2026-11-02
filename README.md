# 星軌 ERP-CRM

星軌 ERP-CRM 是一套「SIM 模擬」用的 ERP／CRM 工作台，介面採科幻艦橋風格。商品、訂單、錢包、客戶、報價、製造工單與行政排班都可以實際操作，資料也會照規則串在一起。但所有金額都是 SIM 測試幣，所有人物與公司都是假資料，用途是練習與展示業務流程。

後端使用 Python 3.12＋FastAPI＋PostgreSQL，前端使用 Vue 3＋TypeScript＋Vite，兩者放在不同資料夾，用 docker compose 一鍵啟動。

## SIM 模擬的限制（請先讀）

- **只有 SIM 測試幣**：幣別固定為 `SIM`，金額以整數最小單位儲存（100 minor = 1 SIM），單一數值上限 1,000,000,000。不連接任何銀行、金流、物流或電子發票。
- **不是會計或稅務系統**：沒有真實稅額、發票、會計科目或財務報表。「模擬報表」只是依工作區紀錄即時計算的練習數字。錢包流水採雙分錄，總和恆為 0，用來練習核對，不能當作帳務依據。
- **行政工作台只用合成資料**：排班、出勤、申請與設備借用都只是練習，不能當作薪資、准假、採購或付款的依據。
- **沒有帳號與權限**：每個瀏覽器以 `erpcrm_session` cookie（HttpOnly、SameSite=Strict）對應一個工作區。沒有登入、角色或權限控管。清除 cookie 或換一個瀏覽器，就會拿到新的空白工作區。
- **資料保留**：公開試用模式（`APP__PUBLIC_DEMO=true`）下，工作區 72 小時沒有存取就會整筆自動刪除。後端每 10 分鐘清理一次，cookie 的 Max-Age 為 259200 秒。自架模式（預設）的資料永久保留，cookie 的 Max-Age 為 31536000 秒（365 天）。兩種模式都會清掉從未寫入（版本 0、沒有工作區）且 24 小時沒有存取的 session。
- **筆數與大小上限**：
  - 每個集合（商品、訂單、客戶等）最多 500 筆，超過時回 `record_limit`。操作歷史不計入這個上限。
  - 每筆命令的明細（`lines`）為 1 到 50 行；客戶等 CRM 紀錄的文字內容合計最多 4000 字。
  - 每個工作區每分鐘最多 120 個請求，GET 也計入，超過時回 429 `rate_limit` 並附 `Retry-After`。
  - 一般寫入的 body 上限 32,768 bytes，備份匯入上限 3 MiB。
  - 冪等收據最多 500 筆。超過時只允許建立、清除與匯入三種操作，這三種操作會把收據修剪到最近 100 筆。
- **禁止輸入真實金融資訊**：欄位名稱含 bank、payer、finance、legal、payment_url 的資料一律拒收（`simulation_required`）。

## 功能總覽

### 共用工作台

- **快速上手（建置精靈）**：三步完成。先填店名、選產業範本，再確認推薦模組，最後建立工作區或下載本機啟動包。草稿暫存在 sessionStorage。
- **自訂建置**：自己勾選模組。啟用某個流程模組時，會自動補上它相依的模組。
- **工作總覽**：首次使用導覽、指標、待辦工作佇列、角色中心、釘選紀錄、全域搜尋（Ctrl K，先做全形轉半形等 NFKC 正規化再比對）、快速新增八種紀錄。
- **沉浸教學**：用自己的工作區實際操作三條流程，每一步都會留下操作證據與前後讀值。三條流程如下：
  - 銷售：8 步，從顧客到出貨。
  - 製造：6 步，從 BOM 到完工入庫。
  - 服務：12 步，從案件、報價到驗收收款。
- **功能地圖、系統藍圖**：列出已啟用的能力、模組相依與資料流向。
- **模擬報表**：依目前資料即時計算銷售額、退款、銷貨成本、毛利、庫存價值與服務收款；啟用行政工作台時另有行政指標。
- **設定與資料**：匯出或匯入 SIM JSON 備份、切換產業範本、清除測試資料，並查看模擬操作歷史。
- **主題圖庫**：六套原創主題，可以先試看再套用。試看期間所有資料操作都會暫停。另有「跟隨系統／日間艦橋／夜間」三種明暗模式，以及「舒適／緊湊」兩種密度。

| 主題 | 英文名稱 | 風格 |
| --- | --- | --- |
| 深空艦橋 | Deep Space Bridge | 冷青色儀表光暈配琥珀警示 |
| 霓虹都會 | Neon Arcology | 洋紅與電光青交錯的夜市招牌色 |
| 軌道站 | Orbital Station | 磷光綠讀數搭配鋼藍 |
| 量子實驗室 | Quantum Lab | 薄荷青與干涉紫 |
| 星際鑄造廠 | Star Foundry | 熔爐橘與高溫金黃壓在煤灰底色上 |
| 星雲航道 | Nebula Lane | 紫羅蘭星雲帶一點玫瑰粉 |

### 業務模組

| 模組（代號） | 畫面名稱 | 功能 |
| --- | --- | --- |
| `inventory` | 商品庫存 | 商品目錄、採購入庫、FIFO 成本批次；可用量 = 現有 − 已保留 |
| `sales` | 模擬訂單 | 多品項接單、部分付款、全額付清後分批出貨、部分退貨與取消；需要 inventory、wallets |
| `wallets` | 測試幣流水 | 商家、供應商與買家的 SIM 錢包，入金與移轉都寫雙分錄 |
| `crm` | 客戶與商機 | 客戶、聯絡人、商機與跟進、案件、報價版本（發出、確認） |
| `services` | 報價與服務 | 服務確認、提交交付版本、驗收或要求補件，驗收後分次收款；需要 crm、wallets |
| `projects` | 任務與里程碑 | 任務與里程碑的狀態與到期時間，逾期會標示 |
| `manufacturing` | BOM 與製造 | 版本化 BOM（建立後不可改，改版產生新版）；工單備料、開工、完工入庫，材料成本以 FIFO 轉入成品；需要 inventory、wallets |
| `administration` | 行政工作台 | 組織、假員工、週班表（台北週一為週首，可複製一週）、手動出勤與更正差異、申請流程（準備、送出、退回、撤回）、設備借用、公告；可一鍵建立合成示範，並匯出 CSV 或列印目前範圍 |

### 產業範本

建置時可以從八種範本中挑一種。範本決定預設模組、稱呼與示範商品：

| 代號 | 名稱 | 用途 |
| --- | --- | --- |
| `retail` | 零售商店 | 練習店內銷售、庫存預留與退貨 |
| `wholesale` | 批發商 | 練習箱裝進貨、批發客戶與出貨追蹤 |
| `service` | 服務工作室 | 練習客戶、報價、交付、驗收與測試幣付款 |
| `restaurant` | 餐飲店 | 以配方 BOM 練習食材預留、餐點製作與模擬銷售 |
| `manufacturing` | 製造工廠 | 練習版本化 BOM、原料 FIFO、開工及完工成本轉移 |
| `ecommerce` | 電商 | 練習品牌商品、顧客、模擬付款與分批出貨 |
| `projects` | 專案公司 | 練習案件、待辦、里程碑與交付 |
| `general` | 一般企業 | 啟用全部模組，作為自訂起點 |

### 資料安全機制

- 每個寫入請求都必須帶 `x-csrf-token`、`Idempotency-Key` 與 `If-Match-Version`，Origin 也必須通過檢查。
- 同一版本只能有一筆寫入成功，另一筆回 412 `version_stale`，資料不會只寫一半。
- 重送相同的 `Idempotency-Key` 會回傳原本的結果，不會重複執行；同一個鍵配上不同內容則回 409 `idempotency_conflict`。
- 每次寫入後都會做一致性檢查（例如錢包總和為 0、庫存批次與帳本相符），不通過就整筆回滾。
- 錯誤一律用 `{"error": {"code", "message", "retry_after_ms"?}}` 格式回傳，訊息為繁體中文。

## 架構

```
        瀏覽器（Vue 3 SPA，hash 路由）
                 │  http://localhost:8080
                 ▼
┌─────────────────────────────────────────┐
│ frontend（nginx 1.27）                  │
│  ・靜態檔 /usr/share/nginx/html          │
│  ・/api/ 反向代理 → backend:8000        │
│  ・client_max_body_size 4m              │
└─────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ backend（FastAPI，uvicorn :8000）       │
│  middleware：錯誤格式、session cookie   │
│  platform：命令管線（寫入請求）         │
│    速率限制 → Origin → CSRF → 冪等鍵    │
│    → 版本標頭 → body 上限 → JSON        │
│    → 重播 → 版本鎖 → 收據上限 → 工作區  │
│    → 模組閘 → handler → 一致性檢查      │
│    → 版本 +1 → 歷史 → 收據              │
│  modules：inventory sales wallets crm   │
│    services projects manufacturing      │
│    administration learning backup       │
│    reports workbench workspace catalog  │
│  APScheduler：每 10 分鐘清理 session    │
└─────────────────────────────────────────┘
                 │  psycopg 3／SQLAlchemy 2
                 ▼
┌─────────────────────────────────────────┐
│ db（postgres:16-alpine）                │
│  資料在 ./data/postgres                 │
│  主機埠 127.0.0.1:5436                  │
│  schema 由 goose migration 管理         │
└─────────────────────────────────────────┘
```

每個寫入請求先鎖住所屬 session 列，再依序經過命令管線（`backend/src/platform/pipeline.py`）：速率限制 → Origin → CSRF → `Idempotency-Key` 格式 → `If-Match-Version` 格式 → body 大小上限 → JSON 解析 → 同一識別的重播 → 版本鎖 → 收據上限 → 工作區是否存在 → 模組閘 → 模組 handler → 一致性檢查 → 版本號 +1 → 寫入 history → 寫入收據。速率計數在 SAVEPOINT 之外先寫入；之後任何一步失敗都只回滾 SAVEPOINT，業務資料、版本號、history 與收據完全不變。

待辦、提示、搜尋、教學證據、報表與 CSV 等衍生資料都由後端計算，前端只負責呈現，並透過型別化的 API client 呼叫後端。

## 目錄結構

```
ERP-CRM/
├── .env.example              # 環境變數範本
├── docker-compose.yaml       # db、backend、frontend 三個服務
├── LICENSE
├── README.md
├── scripts/
│   └── check_repo_text.py    # 名稱與簡體字檢查
├── backend/
│   ├── Dockerfile  docker-entrypoint.sh  Makefile  main.py
│   ├── pyproject.toml  uv.lock
│   ├── migrations/           # goose SQL migration，依時間戳排序
│   ├── scripts/migrate.sh    # migration 包裝腳本
│   ├── src/
│   │   ├── app.py            # create_app()
│   │   ├── config/           # pydantic-settings 設定
│   │   ├── core/             # 錯誤、資料庫、時間、金額等共用元件
│   │   ├── middleware/       # 錯誤處理、session
│   │   ├── platform/         # 命令管線、速率限制、收據、模組登錄、一致性檢查
│   │   └── modules/          # 各業務模組（entity、schema、service、router）
│   └── tests/                # pytest
└── frontend/
    ├── Dockerfile  nginx.conf  index.html
    ├── package.json  vite.config.ts  tsconfig.json
    ├── playwright.config.ts  # 轉接 e2e/playwright.config.ts
    ├── src/
    │   ├── api/              # 型別化 client、待確認操作
    │   ├── lib/  stores/     # 工具函式、Pinia store
    │   ├── themes/           # 主題 token 與六套主題
    │   ├── ui/               # 科幻元件
    │   ├── modules/          # 各頁面
    │   └── views/
    ├── tests/                # Vitest
    └── e2e/                  # Playwright 端對端煙霧測試
```

## 快速開始

需要 Docker（支援 `docker compose`）。

```sh
cp .env.example .env && docker compose up -d --build
```

啟動後開啟 <http://localhost:8080>。backend 容器啟動時會先執行 `./scripts/migrate.sh up` 套用 migration，再啟動 API。健康檢查：

```sh
curl http://localhost:8080/api/health
# {"name":"erpcrm","version":"0.1.0","simulation":true,"real_finance":false,"currency":"SIM"}
```

連接埠：前端 8080 對所有網路介面開放；後端 API 8000 與 PostgreSQL 5436 只綁 `127.0.0.1`，供本機除錯與測試使用，區網其他機器連不到，對外一律經由前端的 nginx。前端埠被占用時，在 `.env` 設定 `FRONTEND_PORT=18080` 之類的值後重新 `docker compose up -d`，再改開 `http://localhost:18080`；其他連接埠請修改 `docker-compose.yaml` 的 `ports`。

## 環境變數

設定以 pydantic-settings 讀取，巢狀欄位用雙底線（`APP__…`、`DATABASE__…`）分隔。docker compose 的 db 與 backend 會讀取根目錄的 `.env`；frontend 不讀 `.env`，避免把資料庫帳密帶進容器。

| 變數 | `.env.example` 的值 | 程式預設值 | 說明 |
| --- | --- | --- | --- |
| `DATABASE__HOST` | `db` | `localhost` | 資料庫主機。compose 內固定覆寫為 `db` |
| `DATABASE__PORT` | `5432` | `5432` | 資料庫埠。compose 內固定覆寫為 `5432` |
| `DATABASE__USER` | `erpcrm` | `erpcrm` | 資料庫帳號，也是 db 容器初始化的帳號 |
| `DATABASE__PASSWORD` | `erpcrm` | 空字串 | 資料庫密碼。只檢查型別，不做強度規則 |
| `DATABASE__NAME` | `erpcrm` | `erpcrm` | 資料庫名稱 |
| `APP__PUBLIC_DEMO` | `false` | `false` | `true` 為公開試用模式，差異見下節 |
| `APP__AUTO_SETUP` | `false` | `false` | 自架模式下，新的 session 第一次進站時自動以預設值建立工作區 |
| `APP__ALLOWED_ORIGINS` | `[]` | `[]` | 寫入請求允許的 Origin，JSON 陣列，例如 `["https://erp.example.com"]`。空陣列時改與 `X-Forwarded-Proto`／`X-Forwarded-Host`（沒有則用 `Host`）組出的 origin 比對 |
| `APP__DEFAULT_INDUSTRY` | （未列） | `retail` | 預設產業範本代號 |
| `APP__DEFAULT_COMPANY` | （未列） | `星軌示範商店` | 預設公司名稱。只在自架模式下預先填入建置精靈 |
| `APP__DEFAULT_MODULES` | （未列） | 未設定 | 預設啟用的模組，JSON 陣列。未設定時沿用範本的推薦模組 |

後三項通常由本機啟動包寫入。

## 公開試用與自架模式

| 項目 | 公開試用（`APP__PUBLIC_DEMO=true`） | 自架（`APP__PUBLIC_DEMO=false`，預設） |
| --- | --- | --- |
| 資料保留 | 72 小時沒有存取就整筆刪除，持續使用會自動延後 | 永久保留 |
| 自動清理 | 每 10 分鐘清理：72 小時沒有存取的工作區，以及從未寫入且 24 小時沒有存取的 session | 每 10 分鐘只清理從未寫入（版本 0、沒有工作區）且 24 小時沒有存取的 session |
| 清理排程 | APScheduler；多個實例時以 advisory lock 確保只有一個執行 | 同左 |
| cookie Max-Age | 259200（72 小時） | 31536000（365 天） |
| `APP__AUTO_SETUP` | 一律忽略，每位訪客都從建置精靈開始 | 可開啟：第一次進站就以 `APP__DEFAULT_*` 自動建立工作區 |
| 建置精靈的公司名稱 | 不預填 | 預填 `APP__DEFAULT_COMPANY` |
| 畫面提示 | 顯示預計清除時間 | 提醒定期匯出備份 |

### 本機啟動包

在建置精靈第 3 步選「下載本機啟動包」，或在自訂建置頁下載，會呼叫 `GET /api/v1/backup/launch-kit`，取得 `erpcrm-launch-kit.zip`。內容如下：

- `.env`：自架模式，`APP__AUTO_SETUP=true`，並帶入所選的產業、公司名稱與模組；資料庫帳密為 `erpcrm`，`FRONTEND_PORT=8080`。
- `start.sh`、`start.cmd`：執行 `docker compose up -d --build`。
- `README.txt`：使用步驟。

把這四個檔案解壓縮到專案根目錄（與 `docker-compose.yaml` 同一層；原有的 `.env` 會被覆蓋），執行 `./start.sh`（Windows 用 `start.cmd`），再開啟 <http://localhost:8080>。第一次進站就會依設定自動建立工作區。

PostgreSQL 只在 `./data/postgres` 第一次建立時設定密碼，之後一律沿用。原本的 `.env` 若改過 `DATABASE__PASSWORD`（或 `FRONTEND_PORT`），請把同樣的值填回新的 `.env`，否則後端會連不上資料庫。啟動包的 `README.txt` 也有同樣的提醒。

## 本機開發

### 後端（uv）

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 與 [goose](https://github.com/pressly/goose)。先只啟動資料庫：

```sh
docker compose up -d db
cd backend
uv sync
# backend/.env：複製根目錄 .env，並把資料庫改連主機埠
#   DATABASE__HOST=localhost
#   DATABASE__PORT=5436
./scripts/migrate.sh up
uv run python main.py        # http://localhost:8000，等同 make run
```

程式碼檢查與格式化：

```sh
uv run ruff check . && uv run ruff format --check .   # 等同 make lint
make format
```

### 前端（npm）

需要 Node 22。

```sh
cd frontend
npm ci
npm run dev        # Vite 開發伺服器，/api 代理到 http://localhost:8000
npm run build      # vue-tsc 型別檢查 + 正式建置
```

## Migration

migration 是 `backend/migrations/` 底下的 goose SQL 檔。`backend/scripts/migrate.sh` 會讀取 `backend/.env`（沒有時用現有環境變數）組出連線字串，請在 `backend/` 目錄執行：

```sh
cd backend
./scripts/migrate.sh up                     # 套用全部未執行的 migration
./scripts/migrate.sh down                   # 回復最近一個 migration
./scripts/migrate.sh create add_something sql   # 新增一個 SQL migration 檔
./scripts/migrate.sh status                 # 其他 goose 指令也可以照用
```

也可以在容器內執行：`docker compose exec backend ./scripts/migrate.sh status`。

## 測試

```sh
# 後端：pytest（需要資料庫與 goose）。測試會先刪除再重建 TEST_DATABASE_URL 指定的資料庫並套用 migration
docker compose up -d db
cd backend
TEST_DATABASE_URL=postgresql://erpcrm:erpcrm@localhost:5436/erpcrm_test uv run pytest -q
uv run ruff check . && uv run ruff format --check .

# 前端：Vitest 單元測試（只收 tests/**/*.spec.ts）
cd frontend
npx vitest run

# 端對端：Playwright，對 docker compose 起來的完整系統執行
docker compose up -d --build
cd frontend
npx playwright install chromium   # 第一次執行前
npx playwright test               # 預設 http://localhost:8080
E2E_BASE_URL=http://localhost:18080 npx playwright test   # 前端改用其他埠時

# 全庫文字檢查：參考專案名稱與簡體字
uv run --with opencc-python-reimplemented python scripts/check_repo_text.py
```

`TEST_DATABASE_URL` 未設定時，預設為 `postgresql://erpcrm:erpcrm@localhost:5436/erpcrm_test`。請勿指向正式資料庫。

Playwright 測試位於 `frontend/e2e/`。每個測試都使用全新的瀏覽器 context，會各自建立新的工作區，涵蓋以下流程：

- 建置精靈
- 銷售教學 8 步
- 行政合成示範與 CSV 匯出
- 備份匯出後再還原
- 主題試看時停用快速新增
- 手機寬度下教學操作列貼齊視窗底部

## 備份與還原

### 單一工作區：SIM JSON

- **匯出**：在「設定與資料」頁按「匯出 SIM JSON」，或呼叫 `GET /api/v1/backup/export`，會下載 `erpcrm-sim-backup.json`。格式為 `{"format": "erpcrm-sim-backup", "format_version": 1, ...}`，包含所有業務集合與操作歷史。
- **還原**：按「匯入 SIM JSON」選擇檔案。瀏覽器先檢查格式並顯示摘要，確認後上傳（檔案上限 8 MiB，精簡後內容上限 3 MiB），再由伺服器完整驗證。
  - 驗證通過後，會以備份內容建立新的資料世代，取代目前的工作區。教學進度與釘選不會帶過去。
  - 備份若被竄改（例如錢包總和不為 0，或帳本金額不符），會回 422，現有資料完全保留。

### 整個資料庫

compose 的資料庫存放在 `./data/postgres`。

```sh
# 備份
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > erpcrm.dump
# 還原（會覆蓋同名物件）
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < erpcrm.dump
```

## 已知限制

- 只做 SIM 模擬：沒有真實金流、稅務、發票、會計、物流或薪資，也不提供任何串接。
- 沒有使用者帳號、角色與權限。工作區綁在瀏覽器 cookie 上，換瀏覽器或清除 cookie 就無法回到原工作區，請用 SIM JSON 備份搬移資料。
- 公開試用模式下，資料 72 小時沒有存取會自動刪除，無法復原。
- 每個集合最多 500 筆、每個工作區每分鐘最多 120 個請求、備份最大 3 MiB，不適合當作大量資料或正式營運使用。
- 時間以 Asia/Taipei 顯示與計算週次（週一為一週的第一天），不支援其他時區設定。
- 介面與錯誤訊息只有繁體中文。

## 授權

授權：MIT，見 LICENSE
