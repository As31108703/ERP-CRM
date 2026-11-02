import type { WorkspaceSnapshot } from "../../api/types";
import { formatSim, simInput } from "../../lib/format";
import { num, recordName, rowsOf, type Row } from "../../lib/records";
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
 * 頁面上的「新增」表單（F§2 快速新增的五種業務紀錄）。Task 21 的快速新增對話框可直接沿用。
 * 金額欄位以 SIM 輸入，送出前換算 minor。
 */
export type CreateKind = "customer" | "product" | "wallet" | "order" | "service";

export const CREATE_MODULE: Record<CreateKind, string> = {
  customer: "crm",
  product: "inventory",
  wallet: "wallets",
  order: "sales",
  service: "services",
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

export function createSpec(kind: CreateKind, ws: WorkspaceSnapshot | null | undefined): CommandFormSpec {
  switch (kind) {
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
