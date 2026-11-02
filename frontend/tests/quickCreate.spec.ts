import { afterEach, describe, expect, it } from "vitest";
import QuickCreate from "../src/modules/overview/QuickCreate.vue";
import { useUiStore } from "../src/stores/ui";
import { fieldByLabel, flush, submitDialog, workspace } from "./pageHarness";
import { mountOverview } from "./overviewHarness";

afterEach(() => {
  document.body.innerHTML = "";
});

const PRODUCT = { id: "p1", name: "星砂杯", sku: "CUP-1", active: true, on_hand: 5, reserved: 1, price_minor: 1200 };
const BUYER = { id: "w-buy", kind: "buyer", name: "測試買家甲", balance_minor: 0 };

async function openQuick(ws = workspace()) {
  const h = await mountOverview(QuickCreate, ws);
  useUiStore().openQuickCreate();
  await flush();
  return h;
}

function kindButton(wrapper: Awaited<ReturnType<typeof openQuick>>["wrapper"], kind: string) {
  return wrapper.get(`[data-testid=quick-create-${kind}]`);
}

describe("quick create", () => {
  it("order disabled without buyer wallet shows 先建立買家錢包", async () => {
    const { wrapper } = await openQuick(workspace({ products: [PRODUCT] }));
    const btn = kindButton(wrapper, "order");
    expect(btn.attributes("disabled")).toBeDefined();
    expect(btn.text()).toContain("先建立買家錢包");
  });

  it("lists eight kinds with the documented blocker reasons", async () => {
    const { wrapper } = await openQuick(
      workspace({ modules: ["inventory", "sales", "wallets", "services", "crm"], wallets: [BUYER] }),
    );
    const kinds = wrapper.findAll("button[data-testid^=quick-create-]").map((b) => b.attributes("data-testid"));
    expect(kinds).toEqual([
      "quick-create-customer",
      "quick-create-product",
      "quick-create-order",
      "quick-create-wallet",
      "quick-create-service",
      "quick-create-workOrder",
      "quick-create-task",
      "quick-create-milestone",
    ]);
    expect(kindButton(wrapper, "order").text()).toContain("先準備可用商品庫存");
    expect(kindButton(wrapper, "service").text()).toContain("先建立客戶案件");
    expect(kindButton(wrapper, "workOrder").text()).toContain("尚未啟用此模組");
    expect(kindButton(wrapper, "task").text()).toContain("尚未啟用此模組");
    expect(kindButton(wrapper, "customer").attributes("disabled")).toBeUndefined();
  });

  it("work order needs a BOM", async () => {
    const { wrapper } = await openQuick(workspace({ modules: ["inventory", "wallets", "manufacturing"], boms: [] }));
    expect(kindButton(wrapper, "workOrder").text()).toContain("先建立 BOM");
    expect(kindButton(wrapper, "workOrder").attributes("disabled")).toBeDefined();
  });

  it("selecting a kind closes the picker and submits the create form", async () => {
    const { wrapper, run } = await openQuick(workspace({ products: [PRODUCT], wallets: [BUYER] }));
    await kindButton(wrapper, "order").trigger("click");
    await flush();
    expect(wrapper.find("[data-testid=quick-create-dialog]").exists()).toBe(false);
    expect(wrapper.get("[role=dialog]").text()).toContain("建立模擬訂單");
    await fieldByLabel(wrapper, "買家錢包").setValue("w-buy");
    await fieldByLabel(wrapper, "星砂杯").setValue("2");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/sales/orders", {
      buyer_wallet_id: "w-buy",
      lines: [{ product_id: "p1", quantity: 2 }],
    });
    expect(wrapper.find("[role=dialog]").exists()).toBe(false);
  });

  it("task form posts with todo status and optional fields", async () => {
    const { wrapper, run } = await openQuick(workspace({ modules: ["projects"] }));
    await kindButton(wrapper, "task").trigger("click");
    await flush();
    await fieldByLabel(wrapper, "標題").setValue("整理倉庫");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/projects/tasks", {
      title: "整理倉庫",
      status: "todo",
      due_at: null,
      notes: "",
    });
  });

  it("milestone defaults to planned", async () => {
    const { wrapper, run } = await openQuick(workspace({ modules: ["projects"] }));
    await kindButton(wrapper, "milestone").trigger("click");
    await flush();
    await fieldByLabel(wrapper, "標題").setValue("上線");
    await submitDialog(wrapper);
    expect(run).toHaveBeenCalledWith("POST", "/api/v1/projects/milestones", expect.objectContaining({ status: "planned" }));
  });

  it("does not open while an operation is pending confirmation", async () => {
    const { wrapper, store } = await mountOverview(QuickCreate, workspace());
    store.busy = true;
    useUiStore().openQuickCreate();
    await flush();
    expect(wrapper.find("[data-testid=quick-create-dialog]").exists()).toBe(false);
  });
});
