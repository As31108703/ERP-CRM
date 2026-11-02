import type { TargetRef, WorkspaceSnapshot } from "../api/types";

/** 紀錄種類 → 所屬模組與快照集合（F§2）。報價在啟用服務模組時歸到服務頁。 */
export const RECORD_KINDS = {
  customer: { module: "crm", collection: "customers", label: "客戶" },
  contact: { module: "crm", collection: "contacts", label: "聯絡人" },
  deal: { module: "crm", collection: "deals", label: "商機" },
  case: { module: "crm", collection: "cases", label: "案件" },
  quote: { module: "crm", collection: "quotes", label: "報價" },
  product: { module: "inventory", collection: "products", label: "商品" },
  wallet: { module: "wallets", collection: "wallets", label: "錢包" },
  order: { module: "sales", collection: "orders", label: "訂單" },
  service: { module: "services", collection: "services", label: "服務" },
  bom: { module: "manufacturing", collection: "boms", label: "BOM" },
  workOrder: { module: "manufacturing", collection: "work_orders", label: "工單" },
  task: { module: "projects", collection: "tasks", label: "任務" },
  milestone: { module: "projects", collection: "milestones", label: "里程碑" },
} as const;

export type RecordKind = keyof typeof RECORD_KINDS;

export type Rec = Record<string, unknown>;
export type Row = Rec & { id: string };

export function isRecordKind(kind: string): kind is RecordKind {
  return Object.prototype.hasOwnProperty.call(RECORD_KINDS, kind);
}

export function moduleOfKind(kind: string, modules: readonly string[]): string {
  if (kind === "quote" && modules.includes("services")) return "services";
  return isRecordKind(kind) ? RECORD_KINDS[kind].module : "";
}

/** 取快照中的集合（缺少或型別不對時回傳空陣列）。 */
export function rowsOf(ws: WorkspaceSnapshot | null | undefined, collection: string): Row[] {
  const value = ws?.[collection];
  return Array.isArray(value) ? (value.filter((r) => r && typeof r === "object" && typeof r.id === "string") as Row[]) : [];
}

export function findRow(ws: WorkspaceSnapshot | null | undefined, collection: string, id: unknown): Row | undefined {
  return typeof id === "string" ? rowsOf(ws, collection).find((r) => r.id === id) : undefined;
}

/** 卡片與選單共用的顯示名稱：name → title → sku → 「種類 id 前 8 碼」。 */
export function recordName(row: Row | undefined, fallback = "紀錄"): string {
  if (!row) return "（已刪除）";
  for (const key of ["name", "title", "sku"]) {
    const v = row[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  return `${fallback} ${row.id.slice(0, 8)}`;
}

/** 以 `/m/<module>` 呈現的業務模組頁；其他模組（例如行政工作台）是獨立頁面 `/<module>`。 */
export const MODULE_ROUTES = ["crm", "inventory", "sales", "wallets", "services", "manufacturing", "projects"] as const;

/** 模組頁路徑：業務模組走 `/m/<module>`，其餘走 `/<module>`。 */
export function modulePath(module: string): string {
  return (MODULE_ROUTES as readonly string[]).includes(module) ? `/m/${module}` : `/${module}`;
}

/**
 * 前往某筆紀錄：切到所屬模組頁，以 `?target=<kind>:<id>` 交給頁面定位
 * （業務模組由 DataSection、行政工作台由 AdminDesk 處理）。
 */
export function targetLocation(target: TargetRef): { path: string; query: { target: string } } {
  return { path: modulePath(target.module), query: { target: `${target.kind}:${target.id}` } };
}

/** 解析路由上的定位參數，只有種類相符時回傳 id。 */
export function targetIdFor(query: unknown, kind: string): string | null {
  if (typeof query !== "string") return null;
  const at = query.indexOf(":");
  return at > 0 && query.slice(0, at) === kind ? query.slice(at + 1) || null : null;
}

/** 狀態顯示文字（F§ 狀態語意，以星軌語氣重寫）。未列出的狀態原樣顯示。 */
export const STATUS_LABELS: Record<string, string> = {
  pending: "待付款",
  partially_paid: "部分付款",
  paid: "已付清",
  partially_shipped: "部分出貨",
  shipped: "已出貨",
  partially_returned: "部分退貨",
  returned: "已退貨",
  cancelled: "已取消",
  draft: "草稿",
  issued: "已發出",
  superseded: "已被新版取代",
  simulated_confirmed: "已模擬確認",
  confirmed: "已確認",
  submitted: "待驗收",
  changes_requested: "需補件",
  accepted: "已驗收",
  new: "待聯繫",
  open: "進行中",
  won: "成交",
  lost: "未成交",
  planned: "計畫中",
  todo: "待辦",
  in_progress: "進行中",
  done: "完成",
  reserved: "已備料",
  started: "製作中",
  completed: "已完工",
  active: "啟用中",
  inactive: "停用中",
  business: "商家",
  supplier: "供應商",
  faucet: "測試幣來源",
  buyer: "買家",
  not_set: "未設定",
};

export function statusLabel(status: unknown): string {
  if (typeof status !== "string" || !status) return STATUS_LABELS.not_set;
  return STATUS_LABELS[status] ?? status;
}

/** DataSection 狀態篩選依據：商品用啟用／停用，錢包用種類，其他用 status。 */
export function statusKey(kind: string, row: Row): string {
  if (kind === "product") return row.active === false ? "inactive" : "active";
  if (kind === "wallet") return typeof row.kind === "string" ? row.kind : "not_set";
  return typeof row.status === "string" && row.status ? row.status : "not_set";
}

export function num(row: Rec | undefined, key: string): number {
  const v = row?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

export function str(row: Rec | undefined, key: string): string {
  const v = row?.[key];
  return typeof v === "string" ? v : "";
}

export function list<T extends Rec = Row>(row: Rec | undefined, key: string): T[] {
  const v = row?.[key];
  return Array.isArray(v) ? (v.filter((x) => x && typeof x === "object") as T[]) : [];
}
