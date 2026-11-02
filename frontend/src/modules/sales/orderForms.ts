import { list, num, recordName, str, type Row } from "../../lib/records";
import type { FormField } from "../../ui/FormDialog.vue";
import { LINES_REQUIRED, type FormValues } from "../shared/commandForm";

export type LineMode = "ship" | "return";

export interface LineChoice {
  line: Row;
  /** 這次最多可出貨（數量−已出）或可退貨（已出−已退）的件數。 */
  max: number;
}

/** 出貨／退貨表單只列出還有剩餘量的品項。 */
export function lineChoices(order: Row, mode: LineMode): LineChoice[] {
  return list(order, "lines")
    .map((line) => ({
      line,
      max:
        mode === "ship"
          ? num(line, "quantity") - num(line, "shipped_quantity")
          : num(line, "shipped_quantity") - num(line, "returned_quantity"),
    }))
    .filter((c) => c.max > 0);
}

export function lineKey(line: Row): string {
  return `line:${line.id}`;
}

export function lineFields(choices: LineChoice[], mode: LineMode): FormField[] {
  return choices.map(({ line, max }) => ({
    name: lineKey(line),
    label: `${recordName(line, "品項")} · 可${mode === "ship" ? "出貨" : "退貨"} ${max}`,
    type: "number",
    min: 0,
    max,
  }));
}

/** 欄位值 → `{lines:[{line_id, quantity}]}`；數量為 0 的品項剔除，全部為 0 時回傳錯誤訊息。 */
export function linePayload(
  choices: LineChoice[],
  values: FormValues,
): { lines: { line_id: string; quantity: number }[] } | string {
  const lines: { line_id: string; quantity: number }[] = [];
  for (const { line, max } of choices) {
    const raw = values[lineKey(line)];
    const qty = raw === undefined || raw === "" ? 0 : Number(raw);
    const name = recordName(line, "品項");
    if (!Number.isSafeInteger(qty) || qty < 0) return `「${name}」請輸入 0 以上的整數。`;
    if (qty > max) return `「${name}」最多可操作 ${max} 件。`;
    if (qty > 0) lines.push({ line_id: line.id, quantity: qty });
  }
  return lines.length ? { lines } : LINES_REQUIRED;
}

/** 訂單操作是否可用（F§1 sales）。 */
export function orderActions(order: Row): { pay: boolean; ship: boolean; return: boolean; cancel: boolean } {
  const cancelled = str(order, "status") === "cancelled";
  const lines = list(order, "lines");
  const total = num(order, "total_minor");
  const paid = num(order, "paid_minor");
  const anyShipped = lines.some((l) => num(l, "shipped_quantity") > 0);
  return {
    pay: !cancelled && paid < total && !anyShipped,
    ship: !cancelled && paid === total && lines.some((l) => num(l, "shipped_quantity") < num(l, "quantity")),
    return: !cancelled && lines.some((l) => num(l, "shipped_quantity") > num(l, "returned_quantity")),
    cancel: !cancelled && !anyShipped,
  };
}
