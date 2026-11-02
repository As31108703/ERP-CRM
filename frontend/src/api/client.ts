import { ref } from "vue";
import type { ErrorBody } from "./types";
import {
  clearPending,
  readPending,
  savePending,
  shouldClearPending,
  type MutateMethod,
  type PendingOperation,
} from "./pending";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterMs: number | null;

  constructor(status: number, code: string, message: string, retryAfterMs: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

/** 進行中的 API 請求數，頂部全域讀取進度條依此顯示。 */
export const inflight = ref(0);

interface Session {
  csrf: string;
  version: number;
}

let session: Session = { csrf: "", version: 0 };

/** 由 workspace store 在每次讀取 view 後更新，寫入請求依此帶上 csrf 與版本號。 */
export function setSession(next: Session): void {
  session = { ...next };
}

export function getSession(): Readonly<Session> {
  return session;
}

function newKey(): string {
  return crypto.randomUUID();
}

async function decodeError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = `請求失敗（HTTP ${res.status}）`;
  let retryAfterMs: number | null = null;
  try {
    const data = (await res.json()) as Partial<ErrorBody> & { message?: string; code?: string };
    if (data?.error) {
      code = data.error.code || code;
      message = data.error.message || message;
      if (typeof data.error.retry_after_ms === "number") retryAfterMs = data.error.retry_after_ms;
    } else {
      code = data?.code || code;
      message = data?.message || message;
    }
  } catch {
    // 非 JSON 回應（例如 nginx 的 502 頁面），使用預設訊息
  }
  if (retryAfterMs === null) {
    const header = res.headers.get("Retry-After");
    const seconds = header === null ? NaN : Number(header);
    if (Number.isFinite(seconds) && seconds >= 0) retryAfterMs = seconds * 1000;
  }
  return new ApiError(res.status, code, message, retryAfterMs);
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  inflight.value++;
  try {
    let res: Response;
    try {
      res = await fetch(path, { credentials: "same-origin", ...init });
    } catch {
      throw new ApiError(0, "network_error", "無法連線到伺服器，請確認網路後再試。");
    }
    if (!res.ok) throw await decodeError(res);
    if (res.status === 204) return undefined as T;
    try {
      return (await res.json()) as T;
    } catch {
      throw new ApiError(res.status, "invalid_response", "伺服器回應格式不正確。");
    }
  } finally {
    inflight.value--;
  }
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET", headers: { Accept: "application/json" } });
}

async function send<T>(op: PendingOperation): Promise<T> {
  try {
    const data = await request<T>(op.path, {
      method: op.method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "x-csrf-token": session.csrf,
        "Idempotency-Key": op.key,
        "If-Match-Version": String(op.version),
      },
      body: JSON.stringify(op.body ?? {}),
    });
    clearPending();
    return data;
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    const code = err instanceof ApiError ? err.code : "network_error";
    if (shouldClearPending(status, code)) clearPending();
    throw err;
  }
}

/** 寫入請求：送出前先把操作存成 pending，結果確定後依 F§9 規則清除或保留。 */
export function mutate<T>(method: MutateMethod, path: string, body: unknown): Promise<T> {
  const op: PendingOperation = { key: newKey(), method, path, body, version: session.version };
  savePending(op);
  return send<T>(op);
}

/** 以同一把 Idempotency-Key、同一份內容與版本號重送上次未確認的操作；沒有時回傳 null。 */
export async function retryPending<T>(): Promise<T | null> {
  const op = readPending();
  if (!op) return null;
  return send<T>(op);
}
