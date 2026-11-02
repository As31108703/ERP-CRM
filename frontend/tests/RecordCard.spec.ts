import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { useUiStore } from "../src/stores/ui";
import { useWorkspaceStore } from "../src/stores/workspace";
import RecordCard, { type Readiness } from "../src/ui/RecordCard.vue";
import type { Row } from "../src/lib/records";
import { workspace } from "./pageHarness";

const ORDER = {
  id: "o1",
  buyer_wallet_id: "w-buy",
  status: "pending",
  total_minor: 3000,
  paid_minor: 0,
  refunded_minor: 0,
  lines: [],
};

async function make(props: { kind: string; row: Row; readiness: Readiness | null }) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:rest(.*)*", component: { render: () => null } }],
  });
  await router.push("/m/sales");
  const store = useWorkspaceStore();
  store.view = { workspace: workspace({ orders: [ORDER], wallets: [{ id: "w-buy", kind: "buyer", name: "甲", balance_minor: 0 }] }), csrf: "c", version: 1 };
  const wrapper = mount(RecordCard, {
    props,
    slots: { title: "訂單 1", default: "<p class='body'>內容</p>" },
    global: { plugins: [router] },
  });
  return { wrapper, router };
}

describe("RecordCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    window.sessionStorage.clear();
  });
  afterEach(() => window.sessionStorage.clear());

  it("shows lifecycle, readiness with a go-to link and the JSON record", async () => {
    const { wrapper, router } = await make({
      kind: "order",
      row: ORDER,
      readiness: {
        summary: "請先準備買家測試幣",
        blockers: [{ message: "買家沒有可用測試幣，尚欠 30.00 SIM", target: { module: "wallets", kind: "wallet", id: "w-buy" } }],
      },
    });
    expect(wrapper.find(".ltrack").exists()).toBe(true);
    expect(wrapper.text()).toContain("請先準備買家測試幣");
    expect(wrapper.text()).toContain("待付款");
    const link = wrapper.get("[data-testid=readiness-go]");
    expect(link.text()).toContain("前往處理");
    await link.trigger("click");
    await new Promise((r) => setTimeout(r, 0));
    expect(router.currentRoute.value.path).toBe("/m/wallets");
    expect(router.currentRoute.value.query.target).toBe("wallet:w-buy");

    const details = wrapper.get("details");
    expect(details.get("summary").text()).toBe("紀錄與來源");
    expect(details.get("pre").text()).toContain('"total_minor": 3000');
  });

  it("renders without readiness and without lifecycle for plain records", async () => {
    const { wrapper } = await make({ kind: "customer", row: { id: "c1", name: "甲" }, readiness: null });
    expect(wrapper.find(".ltrack").exists()).toBe(false);
    expect(wrapper.find("[data-testid=readiness]").exists()).toBe(false);
    expect(wrapper.find(".body").exists()).toBe(true);
  });

  it("toggles the pin and stores it per generation", async () => {
    const { wrapper } = await make({ kind: "order", row: ORDER, readiness: null });
    const pin = wrapper.get("[data-testid=pin-toggle]");
    expect(pin.text()).toBe("釘選");
    expect(pin.attributes("aria-pressed")).toBe("false");
    await pin.trigger("click");
    expect(pin.text()).toBe("已釘選");
    expect(pin.attributes("aria-pressed")).toBe("true");
    expect(JSON.parse(window.sessionStorage.getItem("erpcrm.pins.v1.gen-1") ?? "[]")).toEqual([
      { module: "sales", kind: "order", id: "o1" },
    ]);
    await pin.trigger("click");
    expect(useUiStore().pins).toEqual([]);
  });

  it("refuses the 25th pin with the limit message", async () => {
    const ui = useUiStore();
    const store = useWorkspaceStore();
    const orders = Array.from({ length: 25 }, (_, i) => ({ ...ORDER, id: `o${i}` }));
    store.view = { workspace: workspace({ orders }), csrf: "c", version: 1 };
    for (let i = 0; i < 24; i += 1) expect(ui.togglePin({ module: "sales", kind: "order", id: `o${i}` })).toBeNull();
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o24" })).toBe(
      "最多釘選 24 筆紀錄，請先取消一筆釘選。",
    );
    expect(ui.pins).toHaveLength(24);
  });
});
