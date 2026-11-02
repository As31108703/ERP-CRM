import type { WorkspaceSnapshot } from "../../api/types";
import { formatSim, localInputToIso, simInput } from "../../lib/format";
import { findRow, num, recordName, rowsOf, statusLabel, type Rec, type Row } from "../../lib/records";
import type { FormField } from "../../ui/FormDialog.vue";
import {
  API_V1,
  isError,
  LINES_REQUIRED,
  optionalText,
  readMoney,
  readQty,
  type CommandFormSpec,
  type FormValues,
} from "./commandForm";

/**
 * 「新增」表單（F§2 快速新增的八種紀錄），模組頁與工作總覽的快速新增共用。
 * 金額欄位以 SIM 輸入，送出前換算 minor。
 */
export type CreateKind = "customer" | "product" | "order" | "wallet" | "service" | "workOrder" | "task" | "milestone";

/** 快速新增的順序與所屬模組。 */
export const CREATE_MODULE: Record<CreateKind, string> = {
  customer: "crm",
  product: "inventory",
  order: "sales",
  wallet: "wallets",
  service: "services",
  workOrder: "manufacturing",
  task: "projects",
  milestone: "projects",
};

export const CREATE_KINDS = Object.keys(CREATE_MODULE) as CreateKind[];

export const CREATE_NAMES: Record<CreateKind, string> = {
  customer: "新增客戶",
  product: "新增商品",
  order: "建立訂單",
  wallet: "新增買家錢包",
  service: "建立服務",
  workOrder: "新增製造工單",
  task: "新增任務",
  milestone: "新增里程碑",
};

export function buyerWallets(ws: WorkspaceSnapshot | null | undefined): Row[] {
  return rowsOf(ws, "wallets").filter((w) => w.kind === "buyer");
}

export function availableOf(product: Row): number {
  return num(product, "on_hand") - num(product, "reserved");
}

/** 條件不足時回傳原因（按鈕停用並顯示），可建立時回傳 null。 */
export function createBlocker(kind: CreateKind, ws: WorkspaceSnapshot | null | undefined): string | null {
  if (!ws || !ws.modules.includes(CREATE_MODULE[kind])) return "尚未啟用此模組";
  if (kind === "order") {
    if (buyerWallets(ws).length === 0) return "先建立買家錢包";
    if (!rowsOf(ws, "products").some((p) => p.active !== false && availableOf(p) > 0)) return "先準備可用商品庫存";
  }
  if (kind === "service" && rowsOf(ws, "cases").length === 0) return "先建立客戶案件";
  if (kind === "workOrder" && rowsOf(ws, "boms").length === 0) return "先建立 BOM";
  return null;
}

export function options(rows: Row[], fallback = "紀錄"): { value: string; label: string }[] {
  return rows.map((r) => ({ value: r.id, label: recordName(r, fallback) }));
}

export function caseField(ws: WorkspaceSnapshot | null | undefined): FormField {
  return { name: "case_id", label: "案件", type: "select", required: true, options: options(rowsOf(ws, "cases"), "案件") };
}

export function buyerField(ws: WorkspaceSnapshot | null | undefined): FormField {
  return { name: "buyer_wallet_id", label: "買家錢包", type: "select", required: true, options: options(buyerWallets(ws), "錢包") };
}

export function moneyField(name: string, label: string, hint = "以 SIM 為單位，最多兩位小數"): FormField {
  return { name, label, type: "money", required: true, hint };
}

/** 新訂單的品項欄位：每個啟用中的商品一格數量，標示可用量與售價。 */
export function orderProducts(ws: WorkspaceSnapshot | null | undefined): Row[] {
  return rowsOf(ws, "products").filter((p) => p.active !== false);
}

function orderBuild(products: Row[]) {
  return (values: FormValues) => {
    const lines: { product_id: string; quantity: number }[] = [];
    for (const p of products) {
      const qty = readQty(values, `qty:${p.id}`, recordName(p, "商品"), 0);
      if (isError(qty)) return qty.error;
      if (qty > 0) lines.push({ product_id: p.id, quantity: qty });
    }
    if (lines.length === 0) return LINES_REQUIRED;
    return { method: "POST" as const, path: `${API_V1}/sales/orders`, body: { buyer_wallet_id: values.buyer_wallet_id, lines } };
  };
}

// ── 製造 ─────────────────────────────────────────────

/** BOM 選單文字：成品名稱與版次。 */
export function bomLabel(ws: WorkspaceSnapshot | null | undefined, bom: Rec): string {
  return `${recordName(findRow(ws, "products", bom.product_id), "商品")} · 第 ${num(bom, "revision") || 1} 版`;
}

export function workOrderSpec(ws: WorkspaceSnapshot | null | undefined): CommandFormSpec {
  return {
    title: "新增製造工單",
    fields: [
      {
        name: "bom_id",
        label: "BOM 配方",
        type: "select",
        required: true,
        options: rowsOf(ws, "boms").map((b) => ({ value: b.id, label: bomLabel(ws, b) })),
      },
      { name: "quantity", label: "製作數量", type: "number", required: true, min: 1 },
    ],
    initial: { quantity: 1 },
    submitLabel: "建立工單",
    build: (v) => {
      const qty = readQty(v, "quantity", "製作數量");
      if (isError(qty)) return qty.error;
      return { method: "POST", path: `${API_V1}/manufacturing/work-orders`, body: { bom_id: v.bom_id, quantity: qty } };
    },
  };
}

// ── 專案（任務與里程碑） ───────────────────────────────

export type ProjectKind = "task" | "milestone";

export const PROJECT_COLLECTION: Record<ProjectKind, string> = { task: "tasks", milestone: "milestones" };
export const PROJECT_LABEL: Record<ProjectKind, string> = { task: "任務", milestone: "里程碑" };

export function projectStatusOptions(kind: ProjectKind, current = ""): { value: string; label: string }[] {
  const values = ["todo", "in_progress", "done", ...(kind === "milestone" ? ["planned"] : [])];
  if (current && !values.includes(current)) values.push(current);
  return values.map((v) => ({ value: v, label: statusLabel(v) }));
}

/** 共用欄位轉換：空白到期時間送 null，其餘以本地時間換算 ISO。 */
export function readProjectCommon(
  v: FormValues,
): { title: string; status: string; due_at: string | null; notes: string } | string {
  const raw = String(v.due_at ?? "");
  const due = raw === "" ? null : localInputToIso(raw);
  if (raw !== "" && due === null) return "到期時間格式不正確。";
  return { title: String(v.title), status: String(v.status), due_at: due, notes: String(v.notes ?? "") };
}

export function projectFields(kind: ProjectKind, current = ""): FormField[] {
  return [
    { name: "title", label: "標題", required: true, maxlength: 200 },
    { name: "status", label: "狀態", type: "select", required: true, options: projectStatusOptions(kind, current) },
    { name: "due_at", label: "到期時間", type: "datetime-local", hint: "留白表示未設定" },
    { name: "notes", label: "備註", type: "textarea" },
  ];
}

export function projectCreateSpec(kind: ProjectKind, ws: WorkspaceSnapshot | null | undefined): CommandFormSpec {
  const cases = rowsOf(ws, "cases");
  const fields = projectFields(kind);
  if (cases.length) fields.push({ name: "case_id", label: "關聯案件（選填）", type: "select", options: options(cases, "案件") });
  return {
    title: `新增${PROJECT_LABEL[kind]}`,
    fields,
    initial: { status: kind === "task" ? "todo" : "planned" },
    submitLabel: `建立${PROJECT_LABEL[kind]}`,
    build: (v) => {
      const common = readProjectCommon(v);
      if (typeof common === "string") return common;
      const body: Record<string, unknown> = { ...common };
      if (typeof v.case_id === "string" && v.case_id !== "") body.case_id = v.case_id;
      return { method: "POST", path: `${API_V1}/projects/${PROJECT_COLLECTION[kind]}`, body };
    },
  };
}

export function createSpec(kind: CreateKind, ws: WorkspaceSnapshot | null | undefined): CommandFormSpec {
  switch (kind) {
    case "workOrder":
      return workOrderSpec(ws);
    case "task":
    case "milestone":
      return projectCreateSpec(kind, ws);
    case "customer":
      return {
        title: "新增客戶",
        fields: [
          { name: "name", label: "客戶名稱", required: true },
          { name: "notes", label: "備註", type: "textarea" },
        ],
        build: (v) => ({ method: "POST", path: `${API_V1}/crm/customers`, body: optionalText({ name: v.name }, v, "notes") }),
      };
    case "product":
      return {
        title: "新增商品",
        fields: [
          { name: "name", label: "商品名稱", required: true, maxlength: 100 },
          { name: "sku", label: "SKU", required: true },
          moneyField("price_minor", "售價（SIM）"),
          moneyField("cost_minor", "採購成本（SIM）"),
        ],
        initial: { price_minor: simInput(10000), cost_minor: simInput(5000) },
        build: (v) => {
          const price = readMoney(v, "price_minor", "售價", 1);
          if (isError(price)) return price.error;
          const cost = readMoney(v, "cost_minor", "採購成本", 0);
          if (isError(cost)) return cost.error;
          return {
            method: "POST",
            path: `${API_V1}/inventory/products`,
            body: { name: v.name, sku: v.sku, price_minor: price, cost_minor: cost },
          };
        },
      };
    case "wallet":
      return {
        title: "新增買家錢包",
        fields: [{ name: "name", label: "買家錢包名稱", required: true }],
        build: (v) => ({ method: "POST", path: `${API_V1}/wallets`, body: { kind: "buyer", name: v.name } }),
      };
    case "service":
      return {
        title: "建立服務",
        fields: [caseField(ws), moneyField("amount_minor", "服務金額（SIM）")],
        initial: { amount_minor: simInput(10000) },
        build: (v) => {
          const amount = readMoney(v, "amount_minor", "服務金額", 1);
          if (isError(amount)) return amount.error;
          return { method: "POST", path: `${API_V1}/services`, body: { case_id: v.case_id, amount_minor: amount } };
        },
      };
    case "order": {
      const products = orderProducts(ws);
      return {
        title: "建立模擬訂單",
        fields: [
          buyerField(ws),
          ...products.map(
            (p): FormField => ({
              name: `qty:${p.id}`,
              label: `${recordName(p, "商品")} · 可用 ${availableOf(p)} · ${formatSim(num(p, "price_minor"))}`,
              type: "number",
              min: 0,
            }),
          ),
        ],
        initial: Object.fromEntries(products.map((p) => [`qty:${p.id}`, 0])),
        submitLabel: "建立訂單",
        build: orderBuild(products),
      };
    }
  }
}
