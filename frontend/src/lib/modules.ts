import { MODULE_LABELS } from "../ui/icons";

/** 後端模組登錄的順序（`src/platform/registry.py` 的 MODULES）；勾選結果依此排序。 */
export const MODULE_ORDER = [
  "inventory",
  "sales",
  "wallets",
  "services",
  "crm",
  "projects",
  "manufacturing",
  "administration",
] as const;

/**
 * 模組相依的後備值，與後端 MODULE_DEPENDENCIES 相同。
 * 有範本目錄（`GET /api/templates` 的 `module_dependencies`）時以目錄為準。
 */
export const MODULE_DEPENDENCIES: Readonly<Record<string, readonly string[]>> = {
  sales: ["inventory", "wallets"],
  services: ["crm", "wallets"],
  manufacturing: ["inventory", "wallets"],
};

/** 建置精靈與自訂建置顯示的一行用途說明。 */
export const MODULE_USES: Record<string, string> = {
  inventory: "商品目錄、採購入庫與 FIFO 成本批次，看得到可用、預留與現有數量。",
  sales: "多品項訂單，分次付款、分批出貨、部分退貨與取消。",
  wallets: "商家、供應商與買家的測試幣錢包，每筆移轉都留紀錄。",
  services: "服務確認、提交交付版本、驗收或補件，驗收後分次收款。",
  crm: "客戶、聯絡人、商機跟進、案件與報價版本。",
  projects: "任務與里程碑的狀態與到期時間，逾期會標示出來。",
  manufacturing: "BOM 配方、製造工單的備料、開工與完工入庫。",
  administration: "組織、假員工、週班表、出勤、申請、設備借用與公告。",
};

export const COMPANY_MAX = 100;

export function moduleLabel(id: string): string {
  if (id === "administration") return "行政工作台";
  return MODULE_LABELS[id] ?? id;
}

function orderModules(set: Set<string>): string[] {
  const known = MODULE_ORDER.filter((m) => set.has(m));
  const unknown = [...set].filter((m) => !(MODULE_ORDER as readonly string[]).includes(m));
  return [...known, ...unknown];
}

/**
 * 勾選或取消一個模組。開啟時遞迴補上相依模組；關閉時反覆移除相依已不齊全的模組。
 * `notice` 列出除了 `toggled` 之外被連帶改變的模組。
 */
export function changeModules(
  current: string[],
  toggled: string,
  on: boolean,
  dependencies: Readonly<Record<string, readonly string[]>> = MODULE_DEPENDENCIES,
): { modules: string[]; notice: string | null } {
  const next = new Set(current);
  if (on) {
    const add = (key: string): void => {
      if (next.has(key)) return;
      next.add(key);
      for (const dep of dependencies[key] ?? []) add(dep);
    };
    add(toggled);
  } else {
    next.delete(toggled);
    let changed = true;
    while (changed) {
      changed = false;
      for (const key of next) {
        if ((dependencies[key] ?? []).some((dep) => !next.has(dep))) {
          next.delete(key);
          changed = true;
        }
      }
    }
  }
  const modules = orderModules(next);
  const affected = orderModules(new Set([...current, ...modules])).filter(
    (m) => m !== toggled && current.includes(m) !== modules.includes(m),
  );
  const notice = affected.length
    ? `${on ? "一併啟用" : "一併關閉"}：${affected.map(moduleLabel).join("、")}。`
    : null;
  return { modules, notice };
}

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/;

/** 公司名稱：去頭尾空白後必填、最多 100 字、不可含控制字元。回傳錯誤訊息或 null。 */
export function validateCompany(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "請輸入店名或公司名稱。";
  if (name.length > COMPANY_MAX) return `名稱最多 ${COMPANY_MAX} 個字。`;
  if (CONTROL_CHARS.test(name)) return "名稱不可包含控制字元。";
  return null;
}

export interface BuildConfig {
  industry: string;
  company: string;
  modules: string[];
}

/** 送出建立或下載啟動包前的完整檢查（產業、名稱、模組、相依）。 */
export function buildConfigError(
  config: BuildConfig,
  industryIds: readonly string[],
  dependencies: Readonly<Record<string, readonly string[]>> = MODULE_DEPENDENCIES,
): string | null {
  if (!industryIds.includes(config.industry)) return "請選擇產業範本。";
  const companyError = validateCompany(config.company);
  if (companyError) return companyError;
  if (config.modules.length === 0) return "請至少啟用一個功能模組。";
  if (new Set(config.modules).size !== config.modules.length) return "功能模組重複。";
  if (!config.modules.every((m) => (MODULE_ORDER as readonly string[]).includes(m))) return "包含未知的功能模組。";
  for (const m of config.modules) {
    const missing = (dependencies[m] ?? []).filter((dep) => !config.modules.includes(dep));
    if (missing.length) return `${moduleLabel(m)}需要先啟用：${missing.map(moduleLabel).join("、")}。`;
  }
  return null;
}

/** 本機啟動包下載網址（後端 `GET /api/v1/backup/launch-kit`，回傳 erpcrm-launch-kit.zip）。 */
export function launchKitUrl(config: BuildConfig): string {
  const query = [
    `industry=${encodeURIComponent(config.industry)}`,
    `company_name=${encodeURIComponent(config.company.trim())}`,
    `modules=${config.modules.map(encodeURIComponent).join(",")}`,
  ].join("&");
  return `/api/v1/backup/launch-kit?${query}`;
}

export const LAUNCH_KIT_FILENAME = "erpcrm-launch-kit.zip";
