import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import PinnedRecords from "../src/modules/overview/PinnedRecords.vue";
import RecordCard from "../src/ui/RecordCard.vue";
import { flush } from "./pageHarness";
import { mountOverview } from "./overviewHarness";
import { workspace } from "./pageHarness";
import { useUiStore } from "../src/stores/ui";
import { useWorkspaceStore } from "../src/stores/workspace";

const KEY = "erpcrm.pins.v1.gen-1";

function order(id: string) {
  return { id, buyer_wallet_id: "w-buy", status: "pending", total_minor: 1000, paid_minor: 0, lines: [] };
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => {
  document.body.innerHTML = "";
  window.sessionStorage.clear();
});

describe("pins", () => {
  it("limit 24 shows message", async () => {
    const orders = Array.from({ length: 25 }, (_, i) => order(`o${i}`));
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify(orders.slice(0, 24).map((o) => ({ module: "sales", kind: "order", id: o.id }))),
    );
    const { wrapper, router } = await mountOverview(PinnedRecords, workspace({ orders }));
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("24／24");
    expect(wrapper.findAll("[data-testid=pinned-record]")).toHaveLength(24);

    // 第 25 筆從紀錄卡釘選：拒絕並顯示上限訊息，總覽仍是 24 筆。
    const cardWrapper = mount(RecordCard, {
      props: { kind: "order", row: orders[24], readiness: null },
      global: { plugins: [router] },
      slots: { title: "訂單 25" },
    });
    await cardWrapper.get("[data-testid=pin-toggle]").trigger("click");
    expect(cardWrapper.get("[role=alert]").text()).toBe("最多釘選 24 筆紀錄，請先取消一筆釘選。");
    expect(cardWrapper.get("[data-testid=pin-toggle]").attributes("aria-pressed")).toBe("false");
    await flush();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("24／24");

    // 取消一筆後就能再釘選。
    await wrapper.findAll("[data-testid=pinned-remove]")[0].trigger("click");
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("23／24");
    await cardWrapper.get("[data-testid=pin-toggle]").trigger("click");
    expect(cardWrapper.find("[role=alert]").exists()).toBe(false);
    await flush();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("24／24");
  });

  it("drops pins of deleted records", async () => {
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify([
        { module: "sales", kind: "order", id: "o1" },
        { module: "sales", kind: "order", id: "gone" },
        { module: "projects", kind: "task", id: "t1" },
        { module: "crm", kind: "customer", id: "c1" },
        { module: "inventory", kind: "unknown", id: "x" },
        "garbage",
      ]),
    );
    const ws = workspace({
      orders: [order("o1")],
      customers: [{ id: "c1", name: "北辰貿易" }],
      tasks: [{ id: "t1", title: "盤點", status: "todo" }],
    });
    const { wrapper, router } = await mountOverview(PinnedRecords, ws);
    const ids = wrapper.findAll("[data-testid=pinned-record]").map((r) => r.attributes("data-record-id"));
    // 已刪除的訂單、未啟用的專案模組、未知種類與壞資料都被剔除。
    expect(ids).toEqual(["o1", "c1"]);
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("2／24");
    const customer = wrapper.findAll("[data-testid=pinned-record]")[1];
    expect(customer.text()).toContain("北辰貿易");
    expect(customer.text()).toContain("客戶");

    await customer.get("[data-testid=pinned-open]").trigger("click");
    await flush();
    expect(router.currentRoute.value.path).toBe("/m/crm");
    expect(router.currentRoute.value.query.target).toBe("customer:c1");
  });

  it("shows the empty state without pins", async () => {
    const { wrapper } = await mountOverview(PinnedRecords, workspace());
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("0／24");
    expect(wrapper.text()).toContain("釘選");
    expect(wrapper.findAll("[data-testid=pinned-record]")).toHaveLength(0);
  });
  it("toggling one pin keeps pins hidden by a disabled module or missing record", async () => {
    const stored = [
      { module: "projects", kind: "task", id: "t1" },
      { module: "sales", kind: "order", id: "o1" },
      { module: "sales", kind: "order", id: "restored-later" },
    ];
    window.sessionStorage.setItem(KEY, JSON.stringify(stored));
    const ws = workspace({ orders: [order("o1"), order("o2")], tasks: [{ id: "t1", title: "盤點", status: "todo" }] });
    await mountOverview(PinnedRecords, ws);
    const ui = useUiStore();
    expect(ui.pins.map((p) => p.id)).toEqual(["o1"]);

    // 新增一筆：其他已存的釘選（含目前看不到的）全部保留。
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o2" })).toBeNull();
    expect(JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]")).toEqual([
      ...stored,
      { module: "sales", kind: "order", id: "o2" },
    ]);
    // 取消一筆：只移除那一筆。
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o1" })).toBeNull();
    expect(JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]")).toEqual([
      stored[0],
      stored[2],
      { module: "sales", kind: "order", id: "o2" },
    ]);

    // 重新啟用專案模組後，隱藏的釘選再度出現。
    const store = useWorkspaceStore();
    store.view = { ...store.view!, workspace: { ...ws, modules: [...ws.modules, "projects"] } };
    expect(ui.pins.map((p) => p.id)).toEqual(["t1", "o2"]);
  });

  it("the limit counts visible pins; a full store makes room by dropping hidden pins only", async () => {
    const orders = Array.from({ length: 24 }, (_, i) => order(`o${i}`));
    const hidden = [
      { module: "projects", kind: "task", id: "t1" },
      { module: "sales", kind: "order", id: "gone" },
    ];
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify([...hidden, ...orders.slice(0, 22).map((o) => ({ module: "sales", kind: "order", id: o.id }))]),
    );
    const { wrapper } = await mountOverview(PinnedRecords, workspace({ orders }));
    const ui = useUiStore();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("22／24");

    // 畫面顯示還有空位就能釘選；儲存已滿時優先捨棄已刪除紀錄，再捨棄最舊的隱藏釘選。
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o22" })).toBeNull();
    let saved = JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]") as { id: string }[];
    expect(saved).toHaveLength(24);
    expect(saved.map((p) => p.id)).toContain("t1");
    expect(saved.map((p) => p.id)).not.toContain("gone");

    expect(ui.togglePin({ module: "sales", kind: "order", id: "o23" })).toBeNull();
    saved = JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]") as { id: string }[];
    expect(saved).toHaveLength(24);
    expect(saved.map((p) => p.id)).toEqual(orders.map((o) => o.id));
    await flush();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("24／24");
  });
});
