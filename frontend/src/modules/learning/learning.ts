import type {
  LearningDetail,
  LearningFact,
  LearningPathId,
  LearningScope,
  TargetRef,
  WorkspaceSnapshot,
} from "../../api/types";
import { findRow, isRecordKind, moduleOfKind, str } from "../../lib/records";

/** 流程教學端點（Task 17）。 */
export const LEARNING_API = {
  listing: "/api/v1/learning",
  detail: (path: string) => `/api/v1/learning/${encodeURIComponent(path)}`,
  start: (path: string) => `/api/v1/learning/${encodeURIComponent(path)}/start`,
  restart: (path: string) => `/api/v1/learning/${encodeURIComponent(path)}/restart`,
  view: (path: string) => `/api/v1/learning/${encodeURIComponent(path)}/view`,
  execute: (path: string) => `/api/v1/learning/${encodeURIComponent(path)}/execute`,
} as const;

export const NOTICES = {
  switched: "已切換教學路線，尚未執行任何操作。",
  restarted: "已另開一輪練習。現有工作區資料保留，新的實作仍需要逐步按下執行。",
  reading: "已開啟章節閱讀，工作區資料沒有改變。",
  paused: "已暫停教學與示意動畫，可以繼續閱讀。",
  resumed: "已繼續教學。操作仍需要你逐步確認。",
  running: "正在執行這一步，等待工作區確認結果…",
  confirmed: "操作已確認。下方顯示實際紀錄與前後變化，閱讀內容不會新增完成證據。",
  unconfirmed: "這一步尚未確認完成。請處理工作區提示，再核對原操作結果。",
} as const;

/** 路線卡的裝飾識別碼與圖示（HUD 用，不影響邏輯）。 */
export const ROUTE_GLYPHS: Record<LearningPathId, { code: string; glyph: string }> = {
  sales: { code: "RT-01 · TRADE", glyph: "↗" },
  manufacturing: { code: "RT-02 · FORGE", glyph: "◇" },
  service: { code: "RT-03 · RELAY", glyph: "✓" },
};

/**
 * 流程示意圖節點的顯示名稱、符號與沒有讀值時的說明（以後端 `path.nodes` 的 id 為鍵）。
 * 未列出的 id 直接顯示 id。
 */
const NODE_COPY: Record<string, { label: string; glyph: string; idle?: string }> = {
  wallet: { label: "測試幣", glyph: "S" },
  inventory: { label: "商品與材料", glyph: "▤" },
  order: { label: "訂單", glyph: "≡" },
  shipment: { label: "出貨與成本", glyph: "⇥" },
  bom: { label: "物料清單", glyph: "⌘", idle: "沿用範本 BOM，版本由工單凍結" },
  production: { label: "製造工單", glyph: "◇" },
  finished: { label: "成品入庫", glyph: "▣" },
  case: { label: "客戶案件", glyph: "↗" },
  quote: { label: "報價版本", glyph: "≋" },
  service: { label: "服務確認", glyph: "◎" },
  delivery: { label: "交付與驗收", glyph: "✓" },
};

export function nodeLabel(node: string): string {
  return NODE_COPY[node]?.label ?? node;
}

export function nodeGlyph(node: string): string {
  return NODE_COPY[node]?.glyph ?? "•";
}

/** 節點下方顯示的讀值：取後端標為這個節點的第一列（找不到時給說明文字）。 */
export function nodeFact(node: string, facts: readonly LearningFact[]): string {
  const fact = facts.find((f) => f.node === node);
  if (fact) return `${fact.label} ${fact.value}`;
  return NODE_COPY[node]?.idle ?? "本輪尚無對應紀錄";
}

/** 目前步驟對應的節點索引（後端保證節點 id 不重複）；步驟不在示意圖上時回傳 -1。 */
export function currentNodeIndex(detail: LearningDetail, stepIndex: number): number {
  const step = detail.path.steps[stepIndex];
  return step ? detail.path.nodes.indexOf(step.node) : -1;
}

/** 閱讀位置：有選取的章節就用它，否則停在下一個實作步驟。 */
export function currentIndexOf(detail: LearningDetail): number {
  const steps = detail.evaluation.steps;
  const selected = detail.session?.selected_step ?? null;
  const at = selected ? steps.findIndex((s) => s.id === selected) : -1;
  if (at >= 0) return at;
  return Math.max(0, Math.min(detail.evaluation.next_index, steps.length - 1));
}

export function confirmedCount(detail: LearningDetail): number {
  return detail.evaluation.steps.filter((s) => s.complete).length;
}

export interface ExecuteGate {
  busy: boolean;
  pending: boolean;
}

/** 「執行這一步」能否按下（F§3 Action dock）。 */
export function canExecute(detail: LearningDetail, index: number, gate: ExecuteGate): boolean {
  const session = detail.session;
  const step = detail.evaluation.steps[index];
  if (!session || !step || session.paused) return false;
  if (gate.busy || gate.pending) return false;
  if (detail.evaluation.complete || step.complete) return false;
  if (index !== detail.evaluation.next_index) return false;
  return detail.preview.text !== null && !detail.preview.blocked_reason;
}

export function scopeLabel(scope: LearningScope): string {
  return scope === "lesson" ? "本輪練習" : "整個工作區";
}

/**
 * 「到工作台核對」的定位：依這一步的檢查點找出實際紀錄。
 * - wallet.fund 的結果是流水，定位到入帳的錢包
 * - inventory.receive 的結果是採購，定位到採購的商品
 * - 其餘以命令前綴為紀錄種類、結果為 id
 * 找不到或模組未啟用時回傳 null（改為只開啟模組頁）。
 */
export function recordTarget(detail: LearningDetail, index: number, ws: WorkspaceSnapshot | null | undefined): TargetRef | null {
  const checkpoint = detail.evaluation.steps[index]?.checkpoint;
  if (!checkpoint || !ws) return null;
  let kind = checkpoint.action.split(".")[0];
  let id = checkpoint.result;
  if (checkpoint.action === "wallet.fund") {
    kind = "wallet";
    id = str(checkpoint.payload, "wallet_id");
  } else if (checkpoint.action === "inventory.receive") {
    kind = "product";
    id = str(findRow(ws, "purchases", checkpoint.result), "product_id") || str(checkpoint.payload, "product_id");
  }
  if (!id || !isRecordKind(kind)) return null;
  const module = moduleOfKind(kind, ws.modules);
  if (!module || !ws.modules.includes(module)) return null;
  return { module, kind, id };
}
