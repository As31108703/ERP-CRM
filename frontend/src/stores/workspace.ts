import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ApiError, get, mutate, retryPending, setSession, upload as uploadRequest, type UploadHandlers } from "../api/client";
import { readPending, type MutateMethod, type PendingOperation } from "../api/pending";
import type { MutationResult, TemplatesResponse, Workbench, WorkspaceView } from "../api/types";

export const API = {
  view: "/api/v1/workspace/view",
  templates: "/api/templates",
  workbench: "/api/v1/workbench",
} as const;

export const DESIGN_PREVIEW_BLOCKED = "請先套用或取消外觀試看，再進行資料操作。";
export const PENDING_BLOCKED = "上次操作的結果尚未確認，請先按「確認原操作結果」。";
export const BUSY_BLOCKED = "上一個操作仍在處理中，請稍候。";
export const NO_VIEW_BLOCKED = "尚未取得工作區狀態，請按「重新讀取」。";
export const SAVED_MESSAGE = "已儲存模擬操作。";
export const RECOVERED_MESSAGE = "已確認並恢復原操作。";

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "發生未預期的錯誤，請重新讀取。";
}

/** 讀取尚未上線（404）的端點時視為「暫不可用」，回傳 null，不讓整頁失敗。 */
async function optional<T>(path: string): Promise<T | null> {
  try {
    return await get<T>(path);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export const useWorkspaceStore = defineStore("workspace", () => {
  const view = ref<WorkspaceView | null>(null);
  const templates = ref<TemplatesResponse | null>(null);
  const workbench = ref<Workbench | null>(null);
  const busy = ref(false);
  const pending = ref<PendingOperation | null>(readPending());
  const error = ref("");
  const message = ref("");
  const loaded = ref(false);
  const designPreview = ref(false);

  const hasWorkspace = computed(() => Boolean(view.value?.workspace));

  let firstLoad: Promise<void> | null = null;

  /**
   * view 是寫入所需的 csrf／版本號來源，必須獨立套用：templates 或 workbench 失敗時
   * 只記錄錯誤，不得丟棄 view。沒有工作區時不讀 workbench。
   */
  async function refresh(): Promise<void> {
    const failures: unknown[] = [];
    try {
      const [v, t] = await Promise.allSettled([
        optional<WorkspaceView>(API.view),
        optional<TemplatesResponse>(API.templates),
      ]);
      if (v.status === "fulfilled") {
        view.value = v.value;
        if (v.value) setSession({ csrf: v.value.csrf, version: v.value.version });
      } else {
        failures.push(v.reason);
      }
      if (t.status === "fulfilled") templates.value = t.value;
      else failures.push(t.reason);

      if (view.value?.workspace) {
        try {
          workbench.value = await optional<Workbench>(API.workbench);
        } catch (err) {
          workbench.value = null;
          failures.push(err);
        }
      } else {
        workbench.value = null;
      }
      error.value = failures.length ? messageOf(failures[0]) : "";
    } finally {
      pending.value = readPending();
      loaded.value = true;
    }
  }

  /** 第一次讀取完成前，路由守衛等待這個 promise，避免在狀態未知時誤導向。 */
  function ready(): Promise<void> {
    if (loaded.value) return Promise.resolve();
    firstLoad ??= refresh();
    return firstLoad;
  }

  /** 由外觀設定（Task 20 的 preferences store）在試看開始／結束時呼叫。 */
  function setDesignPreview(active: boolean): void {
    designPreview.value = active;
  }

  function blockedReason(): string | null {
    if (designPreview.value) return DESIGN_PREVIEW_BLOCKED;
    if (busy.value) return BUSY_BLOCKED;
    if (pending.value) return PENDING_BLOCKED;
    if (!view.value) return NO_VIEW_BLOCKED;
    return null;
  }

  /**
   * 寫入的共用流程：標記處理中、成功後顯示訊息並重新讀取；失敗時顯示錯誤、
   * 重讀 pending，遇到 409／412 也重新讀取以取得最新版本號。
   */
  async function execute<T>(call: () => Promise<T>, success: string): Promise<T | null> {
    busy.value = true;
    error.value = "";
    message.value = "";
    try {
      const result = await call();
      pending.value = readPending();
      message.value = success;
      await refresh();
      return result;
    } catch (err) {
      error.value = messageOf(err);
      pending.value = readPending();
      if (err instanceof ApiError && (err.status === 409 || err.status === 412)) {
        await refresh();
        error.value = messageOf(err);
      }
      return null;
    } finally {
      busy.value = false;
    }
  }

  async function run<T = MutationResult>(method: MutateMethod, path: string, body: unknown): Promise<T | null> {
    const blocked = blockedReason();
    if (blocked) {
      error.value = blocked;
      return null;
    }
    return execute(() => mutate<T>(method, path, body), SAVED_MESSAGE);
  }

  /** 大型寫入（備份匯入）：與 run 相同的鎖定與重新讀取規則，另外回報上傳進度。 */
  async function upload<T = MutationResult>(
    path: string,
    body: unknown,
    handlers: UploadHandlers = {},
    success = SAVED_MESSAGE,
  ): Promise<T | null> {
    const blocked = blockedReason();
    if (blocked) {
      error.value = blocked;
      return null;
    }
    return execute(() => uploadRequest<T>("POST", path, body, handlers), success);
  }

  /** 以同一把 key 重送上次未確認的操作。 */
  async function retry<T = MutationResult>(): Promise<T | null> {
    if (busy.value) return null;
    return execute(() => retryPending<T>(), RECOVERED_MESSAGE);
  }

  function dismissMessage(): void {
    message.value = "";
  }

  return {
    view,
    templates,
    workbench,
    busy,
    pending,
    error,
    message,
    loaded,
    designPreview,
    hasWorkspace,
    refresh,
    ready,
    run,
    upload,
    retry,
    blockedReason,
    setDesignPreview,
    dismissMessage,
  };
});
