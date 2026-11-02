import { describe, expect, it } from "vitest";
import { lifecycle } from "../src/lib/lifecycle";

function states(result: ReturnType<typeof lifecycle>) {
  return Object.fromEntries(result.stages.map((s) => [s.label, s.state]));
}

describe("lifecycle", () => {
  it("order paid not shipped → 付款 done, 出貨 current", () => {
    const r = lifecycle("order", { status: "paid", paid_minor: 1000, total_minor: 1000, refunded_minor: 0 });
    expect(r.stages.map((s) => s.label)).toEqual(["建立", "付款", "出貨", "退貨"]);
    expect(states(r)).toEqual({ 建立: "done", 付款: "done", 出貨: "current", 退貨: "todo" });
  });

  it("cancelled order marks failed", () => {
    // 未付款就取消 → 付款 failed
    const unpaid = lifecycle("order", { status: "cancelled", paid_minor: 0, total_minor: 1000, refunded_minor: 0 });
    expect(states(unpaid)).toEqual({ 建立: "done", 付款: "failed", 出貨: "todo", 退貨: "todo" });
    expect(unpaid.terminal).toBe("cancelled");
    expect(unpaid.stages.some((s) => s.state === "current")).toBe(false);
  });

  it("cancelled after full payment marks 出貨 failed; partial payment marks 付款 failed", () => {
    const paid = lifecycle("order", { status: "cancelled", paid_minor: 1000, total_minor: 1000, refunded_minor: 1000 });
    expect(states(paid)).toEqual({ 建立: "done", 付款: "done", 出貨: "failed", 退貨: "todo" });
    const partial = lifecycle("order", { status: "cancelled", paid_minor: 500, total_minor: 1000, refunded_minor: 500 });
    expect(states(partial)).toEqual({ 建立: "done", 付款: "failed", 出貨: "todo", 退貨: "todo" });
  });

  it("uses the spec §6 stage labels for every kind", () => {
    expect(lifecycle("service", { status: "draft" }).stages.map((s) => s.label)).toEqual([
      "草稿", "確認", "交付", "驗收", "收款",
    ]);
    expect(lifecycle("workOrder", { status: "planned" }).stages.map((s) => s.label)).toEqual([
      "規劃", "備料", "開工", "完工",
    ]);
    expect(lifecycle("quote", { status: "draft" }).stages.map((s) => s.label)).toEqual(["草稿", "發出", "確認"]);
    expect(lifecycle("request", { status: "draft" }).stages.map((s) => s.label)).toEqual([
      "草稿", "送出", "整理完成",
    ]);
  });

  it("service accepted and unpaid → 收款 current; fully paid → all done", () => {
    expect(states(lifecycle("service", { status: "accepted", amount_minor: 100, paid_minor: 0 }))).toEqual({
      草稿: "done", 確認: "done", 交付: "done", 驗收: "done", 收款: "current",
    });
    const paid = lifecycle("service", { status: "accepted", amount_minor: 100, paid_minor: 100 });
    expect(paid.stages.every((s) => s.state === "done")).toBe(true);
  });

  it("work order started → 開工 done, 完工 current; cancelled marks first unreached failed", () => {
    expect(states(lifecycle("workOrder", { status: "started" }))).toEqual({
      規劃: "done", 備料: "done", 開工: "done", 完工: "current",
    });
    expect(states(lifecycle("workOrder", { status: "cancelled" }))).toEqual({
      規劃: "done", 備料: "failed", 開工: "todo", 完工: "todo",
    });
  });

  it("withdrawn request keeps reached stages from transitions and marks first unreached failed", () => {
    const r = lifecycle("request", {
      status: "withdrawn",
      transitions: [{ status: "draft" }, { status: "submitted" }, { status: "withdrawn" }],
    });
    expect(states(r)).toEqual({ 草稿: "done", 送出: "done", 整理完成: "failed" });
    expect(r.terminal).toBe("withdrawn");
    const early = lifecycle("request", { status: "withdrawn", transitions: [{ status: "draft" }, { status: "withdrawn" }] });
    expect(states(early)).toEqual({ 草稿: "done", 送出: "failed", 整理完成: "todo" });
  });

  it("order partially returned → 退貨 current; quote issued → 確認 current", () => {
    expect(states(lifecycle("order", { status: "partially_returned" }))["退貨"]).toBe("current");
    expect(states(lifecycle("quote", { status: "issued" }))).toEqual({ 草稿: "done", 發出: "done", 確認: "current" });
  });
});
