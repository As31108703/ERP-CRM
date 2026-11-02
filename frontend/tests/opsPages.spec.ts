import { afterEach, describe, expect, it, vi } from "vitest";
import ManufacturingPage from "../src/modules/manufacturing/ManufacturingPage.vue";
import ProjectsPage from "../src/modules/projects/ProjectsPage.vue";
import ReportsPage from "../src/modules/reports/ReportsPage.vue";
import { buttonIn, card, fieldByLabel, mountPage, submitDialog, workspace } from "./pageHarness";

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

const MFG_MODULES = ["inventory", "wallets", "manufacturing"];
const A = { id: "pa", name: "金屬支架", sku: "FG-1", active: true, on_hand: 0, reserved: 0 };
const B = { id: "pb", name: "鋼料片", sku: "RM-1", active: true, on_hand: 10, reserved: 4 };
const BOM = { id: "b1", product_id: "pa", revision: 1, components: [{ product_id: "pb", quantity: 2 }] };

function wo(id: string, status: string) {
  return { id, bom_id: "b1", bom_snapshot: BOM, quantity: 3, status, created_at: "2026-11-01T00:00:00Z" };
}

describe("manufacturing page", () => {
  it("BOM creation needs two products and rejects self component", async () => {
    const one = await mountPage(ManufacturingPage, workspace({ modules: MFG_MODULES, products: [A] }), { module: "manufacturing" });
    expect(one.wrapper.get("[data-testid=create-bom]").attributes("disabled")).toBeDefined();
    expect(one.wrapper.get("[data-testid=create-work-order]").attributes("disabled")).toBeDefined();
    one.wrapper.unmount();

    const { wrapper, run } = await mountPage(ManufacturingPage, workspace({ modules: MFG_MODULES, products: [A, B] }), {
      module: "manufacturing",
    });
    await wrapper.get("[data-testid=create-bom]").trigger("click");
    await fieldByLabel(wrapper, "成品").setValue("pa");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid=form-error]").text()).toContain("至少");

    await fieldByLabel(wrapper, "金屬支架 每件用量").setValue("1");
    await submitDialog(wrapper);
    expect(run).not.toHaveBeenCalled();
    expect(wrapper.get("[data-testid=form-error]").text()).toContain("自己");

    await fieldByLabel(wrapper, "金屬支架 每件用量").setValue("0");
    await fieldByLabel(wrapper, "鋼料片 每件用量").setValue("2");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/manufacturing/boms", {
      product_id: "pa",
      components: [{ product_id: "pb", quantity: 2 }],
    });
  });

  it("work order actions follow status", async () => {
    const ws = workspace({
      modules: MFG_MODULES,
      products: [A, B],
      boms: [BOM],
      work_orders: [wo("w1", "planned"), wo("w2", "started"), wo("w3", "completed")],
    });
    const { wrapper, run } = await mountPage(ManufacturingPage, ws, { module: "manufacturing" });
    const enabled = (id: string) =>
      card(wrapper, id)
        .findAll("button")
        .filter((b) => ["備料", "開工", "完工入庫", "取消工單"].includes(b.text().trim()) && b.attributes("disabled") === undefined)
        .map((b) => b.text().trim());
    expect(enabled("w1")).toEqual(["備料", "取消工單"]);
    expect(enabled("w2")).toEqual(["完工入庫", "取消工單"]);
    expect(enabled("w3")).toEqual([]);
    expect(card(wrapper, "w1").text()).toContain("金屬支架 · 工單 1");
    expect(card(wrapper, "w1").text()).toContain("製作 3 件");
    expect(card(wrapper, "b1").text()).toContain("鋼料片");

    await buttonIn(card(wrapper, "w1"), "備料").trigger("click");
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/manufacturing/work-orders/w1/reserve", {});

    await wrapper.get("[data-testid=create-work-order]").trigger("click");
    await fieldByLabel(wrapper, "BOM").setValue("b1");
    await fieldByLabel(wrapper, "製作數量").setValue("4");
    await submitDialog(wrapper);
    expect(run).toHaveBeenLastCalledWith("POST", "/api/v1/manufacturing/work-orders", { bom_id: "b1", quantity: 4 });
  });
});

describe("projects page", () => {
  const PROJ = ["services", "wallets", "crm", "projects"];

  it("marks overdue tasks and updates progress with ISO due time", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-02T00:00:00Z"));
    const ws = workspace({
      modules: PROJ,
      cases: [{ id: "c1", title: "內部系統原型建置", status: "open" }],
      tasks: [
        { id: "t1", title: "確認需求", status: "todo", due_at: "2026-11-01T00:00:00Z", case_id: "c1", notes: "" },
        { id: "t2", title: "收尾", status: "done", due_at: "2026-11-01T00:00:00Z" },
      ],
      milestones: [{ id: "m1", title: "原型驗收", status: "planned", due_at: null }],
    });
    const { wrapper, run } = await mountPage(ProjectsPage, ws, { module: "projects" });
    expect(card(wrapper, "t1").find(".overdue").exists()).toBe(true);
    expect(card(wrapper, "t1").text()).toContain("內部系統原型建置");
    expect(card(wrapper, "t2").find(".overdue").exists()).toBe(false);
    expect(card(wrapper, "m1").text()).toContain("未設定到期時間");

    await buttonIn(card(wrapper, "m1"), "更新進度").trigger("click");
    const status = fieldByLabel(wrapper, "狀態");
    expect(status.findAll("option").map((o) => o.attributes("value"))).toEqual(["", "todo", "in_progress", "done", "planned"]);
    await status.setValue("in_progress");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("PATCH", "/api/v1/projects/milestones/m1", {
      title: "原型驗收",
      status: "in_progress",
      due_at: null,
      notes: "",
    });

    await wrapper.get("[data-testid=create-task]").trigger("click");
    await fieldByLabel(wrapper, "標題").setValue("新任務");
    await fieldByLabel(wrapper, "到期時間").setValue("2026-11-05T09:30");
    await submitDialog(wrapper);
    const [, path, body] = run.mock.lastCall as unknown as [string, string, Record<string, unknown>];
    expect(path).toBe("/api/v1/projects/tasks");
    expect(body.status).toBe("todo");
    expect(body.due_at).toBe(new Date("2026-11-05T09:30").toISOString());
    expect(body).not.toHaveProperty("case_id");
  });
});

describe("reports page", () => {
  it("labels every metric and shows the three gauges", async () => {
    const ws = workspace({
      products: [{ id: "p", on_hand: 10, reserved: 2 }],
      orders: [
        { id: "o1", status: "paid", total_minor: 1000, paid_minor: 1000 },
        { id: "o2", status: "pending", total_minor: 1000, paid_minor: 0 },
        { id: "o3", status: "cancelled", total_minor: 5000, paid_minor: 0 },
      ],
      services: [{ id: "s1", status: "accepted", amount_minor: 400, paid_minor: 100 }],
    });
    const { wrapper, store } = await mountPage(ReportsPage, ws, { module: "reports" });
    store.view = {
      ...store.view!,
      report: {
        sales_minor: 12345,
        refunds_minor: 0,
        cost_of_goods_sold_minor: 400,
        gross_profit_minor: 11945,
        estimated_gross_profit_minor: 11900,
        inventory_value_minor: 3000,
        service_payments_minor: 100,
      },
    };
    await wrapper.vm.$nextTick();
    const text = wrapper.text();
    expect(text).toContain("模擬出貨金額");
    expect(text).toContain("123.45 SIM");
    expect(text).toContain("FIFO 模擬毛利");
    expect(text).toContain("服務測試幣收款");
    expect(text).toContain("核對依據");
    const gauges = wrapper.findAll("[data-gauge]").map((g) => [g.attributes("data-gauge"), g.text()]);
    expect(gauges.map((g) => g[0])).toEqual(["stock", "orders", "services"]);
    expect(gauges[0][1]).toContain("80");
    expect(gauges[1][1]).toContain("50");
    expect(gauges[2][1]).toContain("25");
  });
});
