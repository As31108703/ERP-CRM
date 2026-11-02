import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import PinnedRecords from "../src/modules/overview/PinnedRecords.vue";
import RecordCard from "../src/ui/RecordCard.vue";
import { flush } from "./pageHarness";
import { mountOverview } from "./overviewHarness";
import { workspace } from "./pageHarness";

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
});
