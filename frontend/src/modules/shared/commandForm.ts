import { ref, shallowRef } from "vue";
import type { MutateMethod } from "../../api/pending";
import { formatSim, parseSim } from "../../lib/format";
import { useWorkspaceStore } from "../../stores/workspace";
import type { FormField } from "../../ui/FormDialog.vue";

export type FormValues = Record<string, string | number>;

export interface CommandRequest {
  method: MutateMethod;
  path: string;
  body: Record<string, unknown>;
}

/** 一張命令表單：欄位、預設值，以及把欄位值轉成 API 請求（或回傳本地驗證錯誤字串）。 */
export interface CommandFormSpec {
  title: string;
  fields: FormField[];
  initial?: Record<string, string | number | null>;
  submitLabel?: string;
  build: (values: FormValues) => CommandRequest | string;
}

export const API_V1 = "/api/v1";
export const LINES_REQUIRED = "請至少選擇一個品項與數量。";

/** 必填檢查：空字串或缺值時回傳錯誤訊息。 */
export function missingRequired(fields: FormField[], values: FormValues): string | null {
  const missing = fields.find((f) => f.required && (values[f.name] === undefined || values[f.name] === ""));
  return missing ? `請填寫「${missing.label}」。` : null;
}

/** 讀取 SIM 金額欄位並換算 minor；不合法時回傳錯誤訊息字串（以 `{error}` 包起來）。 */
export function readMoney(values: FormValues, name: string, label: string, min = 1): number | { error: string } {
  const minor = parseSim(String(values[name] ?? ""));
  if (minor === null) return { error: `「${label}」請以 SIM 輸入，最多兩位小數。` };
  if (minor < min) return { error: `「${label}」至少 ${formatSim(min)}。` };
  return minor;
}

/** 讀取整數數量欄位；`min` 預設 1。 */
export function readQty(values: FormValues, name: string, label: string, min = 1): number | { error: string } {
  const raw = values[name];
  const n = typeof raw === "number" ? raw : raw === undefined || raw === "" ? 0 : Number(raw);
  if (!Number.isSafeInteger(n) || n < min) return { error: `「${label}」請輸入至少 ${min} 的整數。` };
  return n;
}

export function isError(v: unknown): v is { error: string } {
  return typeof v === "object" && v !== null && "error" in v;
}

/** 選填文字：空字串時不放進 body（建立時使用）。 */
export function optionalText(body: Record<string, unknown>, values: FormValues, ...names: string[]): Record<string, unknown> {
  for (const name of names) {
    const v = values[name];
    if (typeof v === "string" && v !== "") body[name] = v;
  }
  return body;
}

/**
 * 頁面共用的命令表單狀態：開啟、關閉（處理中不可關閉）、送出。
 * 送出成功（store.run 回傳非 null）即關閉；失敗時保留表單並顯示錯誤。
 */
export function useCommandForm() {
  const store = useWorkspaceStore();
  const spec = shallowRef<CommandFormSpec | null>(null);
  const error = ref("");

  function open(next: CommandFormSpec): void {
    error.value = "";
    spec.value = next;
  }

  function close(): void {
    if (store.busy) return;
    spec.value = null;
    error.value = "";
  }

  async function submit(values: FormValues): Promise<void> {
    const current = spec.value;
    if (!current || store.busy) return;
    const missing = missingRequired(current.fields, values);
    if (missing) {
      error.value = missing;
      return;
    }
    const request = current.build(values);
    if (typeof request === "string") {
      error.value = request;
      return;
    }
    error.value = "";
    const result = await store.run(request.method, request.path, request.body);
    if (result === null) {
      error.value = store.error || "操作尚未完成，請稍後再試。";
      return;
    }
    if (spec.value === current) spec.value = null;
  }

  /** 不需要表單的命令（例如發出報價、模擬驗收），錯誤顯示在全域通知。 */
  async function direct(method: MutateMethod, path: string, body: Record<string, unknown> = {}): Promise<void> {
    await store.run(method, path, body);
  }

  return { spec, error, open, close, submit, direct };
}
