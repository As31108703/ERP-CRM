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

/** 由狀態碼、回應文字與 Retry-After 標頭組出 ApiError（fetch 與 XHR 共用）。 */
function errorFrom(status: number, text: string, retryAfter: string | null): ApiError {
  let code = `http_${status}`;
  let message = `請求失敗（HTTP ${status}）`;
  let retryAfterMs: number | null = null;
  try {
    const data = JSON.parse(text) as Partial<ErrorBody> & { message?: string; code?: string };
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
    const seconds = retryAfter === null ? NaN : Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) retryAfterMs = seconds * 1000;
  }
  return new ApiError(status, code, message, retryAfterMs);
}

/** 把非 2xx 的 fetch 回應解成 ApiError（下載等非 JSON 請求也共用）。 */
export async function decodeError(res: Response): Promise<ApiError> {
  let text = "";
  try {
    text = await res.text();
  } catch {
    // 讀不到內容時沿用預設訊息
  }
  return errorFrom(res.status, text, res.headers.get("Retry-After"));
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

/** 寫入請求的共用標頭（csrf、冪等鍵、版本號）。fetch 與 XHR 上傳都由此產生。 */
function writeHeaders(op: PendingOperation): Record<string, string> {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    "x-csrf-token": session.csrf,
    "Idempotency-Key": op.key,
    "If-Match-Version": String(op.version),
  };
}

/** 寫入結果確定後依 F§9 規則清除或保留 pending；成功時清除。 */
async function settle<T>(call: Promise<T>): Promise<T> {
  try {
    const data = await call;
    clearPending();
    return data;
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 0;
    const code = err instanceof ApiError ? err.code : "network_error";
    if (shouldClearPending(status, code)) clearPending();
    throw err;
  }
}

function send<T>(op: PendingOperation): Promise<T> {
  return settle(
    request<T>(op.path, { method: op.method, headers: writeHeaders(op), body: JSON.stringify(op.body ?? {}) }),
  );
}

/** 寫入請求：送出前先把操作存成 pending，結果確定後依 F§9 規則清除或保留。 */
export function mutate<T>(method: MutateMethod, path: string, body: unknown): Promise<T> {
  return send<T>(prepare(method, path, body));
}

function prepare(method: MutateMethod, path: string, body: unknown): PendingOperation {
  const op: PendingOperation = { key: newKey(), method, path, body, version: session.version };
  // 超過 pending 上限（32 KiB，例如備份匯入）時不保存，結果仍依同一套規則處理
  savePending(op);
  return op;
}

export interface UploadHandlers {
  /** 上傳進度（位元組）；瀏覽器無法計算總量時 total 為 0。 */
  onProgress?: (loaded: number, total: number) => void;
  /** 內容已全部送出，接下來等待伺服器驗證。 */
  onUploaded?: () => void;
}

/**
 * 大型寫入（備份匯入）：以 XHR 送出以取得上傳進度。標頭、pending 與錯誤解碼
 * 與 `mutate` 相同；回應 2xx 才算成功。
 */
export function upload<T>(method: MutateMethod, path: string, body: unknown, handlers: UploadHandlers = {}): Promise<T> {
  const op = prepare(method, path, body);
  const payload = JSON.stringify(op.body ?? {});
  inflight.value++;
  const call = new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(op.method, op.path);
    xhr.withCredentials = true;
    for (const [name, value] of Object.entries(writeHeaders(op))) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (e: ProgressEvent) => {
      handlers.onProgress?.(e.loaded, e.lengthComputable ? e.total : 0);
    };
    xhr.upload.onload = () => handlers.onUploaded?.();
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(errorFrom(xhr.status, xhr.responseText, xhr.getResponseHeader("Retry-After")));
        return;
      }
      if (xhr.status === 204 || xhr.responseText === "") {
        resolve(undefined as T);
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch {
        reject(new ApiError(xhr.status, "invalid_response", "伺服器回應格式不正確。"));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "無法連線到伺服器，請確認網路後再試。"));
    xhr.onabort = xhr.onerror;
    xhr.send(payload);
  });
  return settle(call).finally(() => {
    inflight.value--;
  });
}

/** 以同一把 Idempotency-Key、同一份內容與版本號重送上次未確認的操作；沒有時回傳 null。 */
export async function retryPending<T>(): Promise<T | null> {
  const op = readPending();
  if (!op) return null;
  return send<T>(op);
}
