/**
 * 單據生命週期軌道（spec §6）。只依紀錄本身的欄位推算，不呼叫 API。
 *
 * 狀態語意：
 * - done：這一段已經完成。
 * - current：下一步要做的段落。
 * - todo：尚未輪到。
 * - failed：單據已取消／撤回／被取代，第一個未到達的段落標為 failed。
 */
export type LifecycleKind = "order" | "service" | "workOrder" | "quote" | "request";
export type StageState = "done" | "current" | "todo" | "failed";

export interface LifecycleStage {
  key: string;
  label: string;
  state: StageState;
}

export interface Lifecycle {
  stages: LifecycleStage[];
  /** 單據以非正常方式結束時的原因；正常進行或完成時不設定。 */
  terminal?: "cancelled" | "withdrawn" | "superseded";
}

type Row = Record<string, unknown>;

const STAGES: Record<LifecycleKind, [key: string, label: string][]> = {
  order: [
    ["create", "建立"],
    ["pay", "付款"],
    ["ship", "出貨"],
    ["return", "退貨"],
  ],
  service: [
    ["draft", "草稿"],
    ["confirm", "確認"],
    ["deliver", "交付"],
    ["accept", "驗收"],
    ["collect", "收款"],
  ],
  workOrder: [
    ["plan", "規劃"],
    ["reserve", "備料"],
    ["start", "開工"],
    ["complete", "完工"],
  ],
  quote: [
    ["draft", "草稿"],
    ["issue", "發出"],
    ["confirm", "確認"],
  ],
  request: [
    ["draft", "草稿"],
    ["submit", "送出"],
    ["prepare", "整理完成"],
  ],
};

function num(row: Row, key: string): number {
  const v = row[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function str(row: Row, key: string): string {
  const v = row[key];
  return typeof v === "string" ? v : "";
}

/** 依「已完成幾段」組出軌道：前 done 段為 done，下一段為 current（若還有）。 */
function progress(kind: LifecycleKind, done: number): LifecycleStage[] {
  return STAGES[kind].map(([key, label], i) => ({
    key,
    label,
    state: i < done ? "done" : i === done ? "current" : "todo",
  }));
}

/** 已終止的單據：已到達的段落保留 done，第一個未到達的段落為 failed，之後為 todo。 */
function terminated(kind: LifecycleKind, reached: number): LifecycleStage[] {
  const defs = STAGES[kind];
  const stop = Math.min(reached, defs.length - 1);
  return defs.map(([key, label], i) => ({
    key,
    label,
    state: i < stop ? "done" : i === stop ? "failed" : "todo",
  }));
}

function orderDone(status: string, row: Row): number {
  switch (status) {
    case "pending":
    case "partially_paid":
      return 1;
    case "paid":
    case "partially_shipped":
      return 2;
    case "shipped":
    case "partially_returned":
      return 3;
    case "returned":
      return 4;
    default:
      // 未知狀態：以金額推算，至少已建立。
      return num(row, "paid_minor") > 0 ? 2 : 1;
  }
}

function lifecycleOf(kind: LifecycleKind, row: Row): Lifecycle {
  const status = str(row, "status");
  switch (kind) {
    case "order": {
      if (status === "cancelled") {
        // 取消會把已付金額全數退回（refunded = 取消前的 paid）。付清後才取消 → 卡在出貨；
        // 未付或只付部分就取消 → 卡在付款。
        const total = num(row, "total_minor");
        const paidBefore = Math.max(num(row, "refunded_minor"), num(row, "paid_minor"));
        const fullyPaid = total > 0 && paidBefore >= total;
        return { stages: terminated(kind, fullyPaid ? 2 : 1), terminal: "cancelled" };
      }
      const done = orderDone(status, row);
      // 已全部出貨：退貨是選擇性步驟，不標為 current。
      if (status === "shipped") {
        return { stages: progress(kind, 3).map((s) => (s.state === "current" ? { ...s, state: "todo" } : s)) };
      }
      return { stages: progress(kind, done) };
    }
    case "service": {
      const done =
        status === "draft"
          ? 1
          : status === "confirmed" || status === "changes_requested"
            ? 2
            : status === "submitted"
              ? 3
              : status === "accepted"
                ? num(row, "paid_minor") >= num(row, "amount_minor") && num(row, "amount_minor") > 0
                  ? 5
                  : 4
                : 1;
      return { stages: progress(kind, done) };
    }
    case "workOrder": {
      if (status === "cancelled") return { stages: terminated(kind, 1), terminal: "cancelled" };
      const done = { planned: 1, reserved: 2, started: 3, completed: 4 }[status] ?? 1;
      return { stages: progress(kind, done) };
    }
    case "quote": {
      if (status === "superseded") return { stages: terminated(kind, 2), terminal: "superseded" };
      const done = { draft: 1, issued: 2, simulated_confirmed: 3 }[status] ?? 1;
      return { stages: progress(kind, done) };
    }
    case "request": {
      if (status === "withdrawn") {
        const transitions = Array.isArray(row.transitions) ? (row.transitions as Row[]) : [];
        const submitted = transitions.some((t) => t && str(t, "status") === "submitted");
        return { stages: terminated(kind, submitted ? 2 : 1), terminal: "withdrawn" };
      }
      // returned（退回補件）需回到草稿修改後重新送出，所以「送出」是下一步。
      const done = { draft: 1, returned: 1, submitted: 2, prepared_unreviewed: 3 }[status] ?? 1;
      return { stages: progress(kind, done) };
    }
  }
}

export function lifecycle(kind: LifecycleKind, row: Row | null | undefined): Lifecycle {
  return lifecycleOf(kind, row ?? {});
}

export const LIFECYCLE_KINDS: Record<LifecycleKind, string> = {
  order: "模擬訂單",
  service: "服務",
  workOrder: "工單",
  quote: "報價",
  request: "行政申請",
};

export const TERMINAL_LABELS: Record<NonNullable<Lifecycle["terminal"]>, string> = {
  cancelled: "已取消",
  withdrawn: "已撤回",
  superseded: "已被取代",
};
