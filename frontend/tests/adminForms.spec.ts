import { describe, expect, it } from "vitest";
import {
  correctionForm,
  requestCreateForm,
  shiftCreateForm,
  type AdminCommand,
  type DeskData,
} from "../src/modules/administration/adminForms";

const STAMP = { created_at: "2026-11-01T00:00:00+00:00", updated_at: "2026-11-01T00:00:00+00:00" };

function desk(): DeskData {
  return {
    units: [{ id: "u1", name: "星港門市", kind: "branch", parent_id: null, active: true, ...STAMP }],
    staff: [{ id: "s1", code: "S-1", alias: "星員甲", unit_id: "u1", role_label: "", status: "active", ...STAMP }],
    shifts: [
      {
        id: "sh1",
        staff_id: "s1",
        unit_id: "u1",
        start_at: "2026-11-02T01:00:00+00:00",
        end_at: "2026-11-02T09:00:00+00:00",
        break_minutes: 60,
        note: "早班",
        status: "scheduled",
        ...STAMP,
      },
    ],
    attendance: [],
    requests: [],
    equipment: [],
    reservations: [],
    notices: [],
    changes: [],
  };
}

function isCommand(out: AdminCommand | string): out is AdminCommand {
  return typeof out !== "string";
}

describe("adminForms", () => {
  it("shift interval over 48h rejected client-side", () => {
    const spec = shiftCreateForm(desk(), "shifts", "2026-11-02");
    const base = { ...spec.initial, staff_id: "s1", start_at: "2026-11-02T09:00", break_minutes: "0", note: "" };

    const tooLong = spec.build({ ...base, end_at: "2026-11-04T09:01" });
    expect(typeof tooLong).toBe("string");
    expect(tooLong).toContain("48");

    const exactly48 = spec.build({ ...base, end_at: "2026-11-04T09:00" });
    expect(isCommand(exactly48)).toBe(true);
    if (!isCommand(exactly48)) return;
    expect(exactly48.method).toBe("POST");
    expect(exactly48.path).toBe("/api/v1/administration/shifts");
    // 台北時間輸入，送出帶 +08:00 的分鐘對齊時間；unit_id 由假員工推得。
    expect(exactly48.body).toEqual({
      staff_id: "s1",
      unit_id: "u1",
      start_at: "2026-11-02T09:00:00+08:00",
      end_at: "2026-11-04T09:00:00+08:00",
      break_minutes: 0,
      note: "",
    });

    expect(spec.build({ ...base, end_at: "2026-11-02T09:00" })).toContain("結束時間");
    expect(spec.build({ ...base, end_at: "2026-11-02T10:00", break_minutes: "60" })).toContain("休息");
  });

  it("correction with no change rejected", () => {
    const row = desk().shifts[0];
    const spec = correctionForm("shift", row);
    // 預設值就是原紀錄（台北時間）。
    expect(spec.initial.start_at).toBe("2026-11-02T09:00");
    expect(spec.initial.end_at).toBe("2026-11-02T17:00");

    const unchanged = spec.build({ ...spec.initial, reason: "核對後確認" });
    expect(unchanged).toBe("沒有任何欄位變更，請修改後再送出更正。");

    expect(spec.build({ ...spec.initial, note: "晚到", reason: "  " })).toContain("更正原因");

    const changed = spec.build({ ...spec.initial, note: "早班（調整）", reason: "備註補充" });
    expect(isCommand(changed)).toBe(true);
    if (!isCommand(changed)) return;
    expect(changed.method).toBe("PATCH");
    expect(changed.path).toBe("/api/v1/administration/shifts/sh1");
    // 只送出有變更的欄位與原因。
    expect(changed.body).toEqual({ reason: "備註補充", note: "早班（調整）" });
  });

  it("leave forces amount 0", () => {
    const spec = requestCreateForm(desk());
    const values = {
      ...spec.initial,
      type: "leave",
      unit_id: "u1",
      staff_id: "s1",
      title: "家庭照顧假",
      description: "",
      start_at: "2026-11-03T09:00",
      end_at: "2026-11-05T18:00",
      amount_sim: "120.50",
    };
    // 請假不顯示金額欄位。
    expect(spec.fields.find((f) => f.name === "amount_sim")?.show?.(values)).toBe(false);

    const out = spec.build(values);
    expect(isCommand(out)).toBe(true);
    if (!isCommand(out)) return;
    expect(out.body.amount_minor).toBe(0);
    expect(out.body.type).toBe("leave");
    expect(out.body.start_at).toBe("2026-11-03T09:00:00+08:00");

    // 請假必須指定假員工與起訖時間。
    expect(spec.build({ ...values, staff_id: "" })).toContain("假員工");
    expect(spec.build({ ...values, end_at: "" })).toContain("結束");

    // 切換類型會重設金額與日期；切換組織會清除假員工。
    const next = { ...values };
    spec.onChange?.("type", next);
    expect(next.amount_sim).toBe("");
    expect(next.start_at).toBe("");
    expect(next.end_at).toBe("");
    spec.onChange?.("unit_id", next);
    expect(next.staff_id).toBe("");

    // 請購金額必須大於 0。
    const purchase = spec.build({ ...values, type: "purchase", amount_sim: "0", start_at: "", end_at: "" });
    expect(purchase).toContain("金額");
  });
});
