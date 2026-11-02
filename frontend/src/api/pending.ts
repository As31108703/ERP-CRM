import { safeSession } from "../lib/storage";

/** 尚未確認結果的寫入操作，存在 sessionStorage，供「確認原操作結果」以同一把 key 重送。 */
export const PENDING_KEY = "erpcrm.pending.v1";
export const PENDING_BODY_LIMIT = 32_768;

export type MutateMethod = "POST" | "PATCH";

export interface PendingOperation {
  key: string;
  method: MutateMethod;
  path: string;
  body: unknown;
  version: number;
}

const KEY_PATTERN = /^[A-Za-z0-9_-]{8,100}$/;
// 只允許同源的 API 路徑，避免被竄改的暫存資料把請求送到別處
const PATH_PATTERN = /^\/api\/(v1\/)?[A-Za-z0-9_\-/.]+$/;

function byteLength(text: string): number {
  return new TextEncoder().encode(text).length;
}

export function isValidPending(value: unknown): value is PendingOperation {
  if (!value || typeof value !== "object") return false;
  const p = value as Record<string, unknown>;
  return (
    typeof p.key === "string" &&
    KEY_PATTERN.test(p.key) &&
    (p.method === "POST" || p.method === "PATCH") &&
    typeof p.path === "string" &&
    PATH_PATTERN.test(p.path) &&
    !p.path.includes("..") &&
    Number.isSafeInteger(p.version) &&
    (p.version as number) >= 0 &&
    "body" in p &&
    byteLength(JSON.stringify(p.body ?? null)) <= PENDING_BODY_LIMIT
  );
}

/** 寫入暫存；內容不合規格（例如超過 32 KiB）時不保存，回傳 false。 */
export function savePending(op: PendingOperation): boolean {
  if (!isValidPending(op)) return false;
  return safeSession.set(PENDING_KEY, JSON.stringify(op));
}

/** 讀取暫存；格式錯誤的資料會被丟棄。 */
export function readPending(): PendingOperation | null {
  const raw = safeSession.get(PENDING_KEY);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (isValidPending(parsed)) return parsed;
  } catch {
    // 落到下方清除
  }
  safeSession.remove(PENDING_KEY);
  return null;
}

export function clearPending(): void {
  safeSession.remove(PENDING_KEY);
}

/**
 * F§9 的保留規則：成功、或 4xx（429 除外）時清除；429 `receipt_limit` 也清除；
 * 其餘（5xx、429 速率限制、網路錯誤）保留，讓使用者以同一把 key 確認結果。
 */
export function shouldClearPending(status: number, code: string): boolean {
  if (status >= 200 && status < 300) return true;
  if (status === 429) return code === "receipt_limit";
  return status >= 400 && status < 500;
}

export function pendingStorageVolatile(): boolean {
  return safeSession.volatile;
}
