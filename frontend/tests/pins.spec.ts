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
  it("toggling one pin keeps pins hidden by a disabled module and drops deleted records", async () => {
    const stored = [
      { module: "projects", kind: "task", id: "t1" },
      { module: "sales", kind: "order", id: "o1" },
      { module: "sales", kind: "order", id: "gone" },
    ];
    window.sessionStorage.setItem(KEY, JSON.stringify(stored));
    const ws = workspace({ orders: [order("o1"), order("o2")], tasks: [{ id: "t1", title: "盤點", status: "todo" }] });
    await mountOverview(PinnedRecords, ws);
    const ui = useUiStore();
    expect(ui.pins.map((p) => p.id)).toEqual(["o1"]);

    // 新增一筆：隱藏（模組停用）的釘選保留，已刪除紀錄的釘選剔除。
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o2" })).toBeNull();
    expect(JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]")).toEqual([
      stored[0],
      stored[1],
      { module: "sales", kind: "order", id: "o2" },
    ]);
    // 取消一筆：只移除那一筆。
    expect(ui.togglePin({ module: "sales", kind: "order", id: "o1" })).toBeNull();
    expect(JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]")).toEqual([
      stored[0],
      { module: "sales", kind: "order", id: "o2" },
    ]);

    // 重新啟用專案模組後，隱藏的釘選再度出現。
    const store = useWorkspaceStore();
    store.view = { ...store.view!, workspace: { ...ws, modules: [...ws.modules, "projects"] } };
    expect(ui.pins.map((p) => p.id)).toEqual(["t1", "o2"]);
  });

  it("the limit counts all valid stored pins, hidden ones included, and never evicts", async () => {
    const orders = Array.from({ length: 24 }, (_, i) => order(`o${i}`));
    const pin = (id: string) => ({ module: "sales", kind: "order", id });
    // 1 筆隱藏（專案模組停用）＋ 22 筆可見 ＋ 1 筆已刪除：有效 23 筆。
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify([
        { module: "projects", kind: "task", id: "t1" },
        ...orders.slice(0, 22).map((o) => pin(o.id)),
        pin("gone"),
      ]),
    );
    const ws = workspace({ orders, tasks: [{ id: "t1", title: "盤點", status: "todo" }] });
    const { wrapper } = await mountOverview(PinnedRecords, ws);
    const ui = useUiStore();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("22／24");

    // 已刪除的不佔名額：第 24 筆有效釘選可以加入。
    expect(ui.togglePin(pin("o22"))).toBeNull();
    const full = window.sessionStorage.getItem(KEY);
    const fullIds = (JSON.parse(full ?? "[]") as { id: string }[]).map((p) => p.id);
    expect(fullIds).toHaveLength(24);
    expect(fullIds).toContain("t1");
    expect(fullIds).not.toContain("gone");

    // 有效 24 筆（含 1 筆隱藏）：拒絕新增，儲存不變。
    expect(ui.togglePin(pin("o23"))).toBe("最多釘選 24 筆紀錄，請先取消一筆釘選。");
    expect(window.sessionStorage.getItem(KEY)).toBe(full);
    await flush();
    expect(wrapper.get("[data-testid=pinned-count]").text()).toBe("23／24");

    // 取消一筆後就能再加入，隱藏的釘選始終保留。
    expect(ui.togglePin(pin("o0"))).toBeNull();
    expect(ui.togglePin(pin("o23"))).toBeNull();
    const saved = (JSON.parse(window.sessionStorage.getItem(KEY) ?? "[]") as { id: string }[]).map((p) => p.id);
    expect(saved).toHaveLength(24);
    expect(saved).toContain("t1");
    expect(saved).not.toContain("o0");
  });
});
