import type { WorkspaceSnapshot } from "../../api/types";
import { localInputToIso, simInput, toLocalInput } from "../../lib/format";
import { findRow, list, recordName, rowsOf, str, type Row } from "../../lib/records";
import { API_V1, isError, readMoney, type CommandFormSpec } from "../shared/commandForm";
import { caseField, moneyField } from "../shared/createForms";

const WEEK_MS = 7 * 86_400_000;

/** 建立報價：金額預設 100 SIM，有效期限預設 7 天後；`caseId` 有值時不顯示案件選單。 */
export function quoteSpec(ws: WorkspaceSnapshot | null | undefined, caseId?: string): CommandFormSpec {
  return {
    title: "建立報價版本",
    fields: [
      ...(caseId ? [] : [caseField(ws)]),
      moneyField("amount_minor", "報價金額（SIM）"),
      { name: "expires_at", label: "有效期限", type: "datetime-local", required: true, hint: "發出後內容凍結，過期需重新起草" },
    ],
    initial: { amount_minor: simInput(10000), expires_at: toLocalInput(Date.now() + WEEK_MS) },
    submitLabel: "建立報價",
    build: (v) => {
      const amount = readMoney(v, "amount_minor", "報價金額");
      if (isError(amount)) return amount.error;
      const expires = localInputToIso(String(v.expires_at ?? ""));
      if (!expires) return "請輸入有效的到期時間。";
      return {
        method: "POST",
        path: `${API_V1}/crm/quotes`,
        body: { case_id: caseId ?? v.case_id, amount_minor: amount, expires_at: expires },
      };
    },
  };
}

/** 報價版次：有 `revision` 欄位時用它，否則以同案件內的建立順序推算。 */
export function quoteRevision(ws: WorkspaceSnapshot | null | undefined, quote: Row): number {
  if (typeof quote.revision === "number") return quote.revision;
  const sameCase = rowsOf(ws, "quotes").filter((q) => q.case_id === quote.case_id);
  return sameCase.findIndex((q) => q.id === quote.id) + 1;
}

export function quoteTitle(ws: WorkspaceSnapshot | null | undefined, quote: Row): string {
  return `${recordName(findRow(ws, "cases", quote.case_id), "案件")} · 報價 ${quoteRevision(ws, quote)}`;
}

export function quoteExpired(quote: Row, now: number): boolean {
  const at = Date.parse(str(quote, "expires_at"));
  return Number.isNaN(at) || at <= now;
}

/** 服務名稱：自身 title → 來源快照的案件標題 → 目前案件名稱。 */
export function serviceTitle(ws: WorkspaceSnapshot | null | undefined, service: Row): string {
  const own = str(service, "title");
  if (own) return own;
  const snap = service.source_snapshot as { case?: { title?: unknown } } | undefined;
  if (typeof snap?.case?.title === "string" && snap.case.title) return snap.case.title;
  return recordName(findRow(ws, "cases", service.case_id), "服務");
}

export function latestDelivery(service: Row): Row | undefined {
  return list(service, "deliveries").find((d) => d.id === service.latest_delivery_id);
}
