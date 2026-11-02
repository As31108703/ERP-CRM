import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { h, type Component } from "vue";
import DataSectionSfc from "../src/ui/DataSection.vue";

// 泛型 SFC 在測試中以一般元件掛載，props 型別由各案自行保證。
const DataSection = DataSectionSfc as unknown as Component;

interface Row {
  id: string;
  name: string;
  status: string;
}

const rows: Row[] = Array.from({ length: 30 }, (_, i) => ({
  id: `r${i}`,
  name: `紀錄 ${String(i).padStart(2, "0")}`,
  status: i % 3 === 0 ? "paid" : "pending",
}));

function make(props: Record<string, unknown> = {}) {
  return mount(DataSection, {
    props: {
      title: "訂單",
      items: rows,
      searchText: (r: Row) => r.name,
      statusOf: (r: Row) => r.status,
      targetId: null,
      ...props,
    },
    slots: {
      item: ({ item }: { item: Row }) => h("span", { class: "row-id" }, item.id),
    },
    attachTo: document.body,
  });
}

const ids = (w: ReturnType<typeof make>) => w.findAll(".row-id").map((n) => n.text());

describe("DataSection", () => {
  it("paginates at 12 and jumps to target page", async () => {
    const w = make();
    expect(ids(w)).toHaveLength(12);
    expect(ids(w)[0]).toBe("r0");
    expect(w.text()).toContain("顯示 30／30 筆");
    expect(w.text()).toContain("第 1／3 頁 · 每頁 12 筆");

    await w.get("[data-testid=page-next]").trigger("click");
    expect(ids(w)[0]).toBe("r12");

    // 「1」命中 01、10–19、21：剛好 12 筆，不顯示分頁
    await w.get("input[type=search]").setValue("紀錄 1");
    expect(w.text()).toContain("顯示 12／30 筆");
    expect(w.find("[data-testid=page-next]").exists()).toBe(false);

    await w.setProps({ targetId: "r27" });
    expect((w.get("input[type=search]").element as HTMLInputElement).value).toBe("");
    expect(w.text()).toContain("第 3／3 頁");
    expect(ids(w)).toContain("r27");
    const card = w.get("[data-record-id=r27]");
    expect(card.classes()).toContain("is-target");
    expect(card.text()).toContain("目前定位");
    w.unmount();
  });

  it("status filter, max length and clear filters", async () => {
    const w = make();
    const input = w.get("input[type=search]");
    expect(input.attributes("maxlength")).toBe("120");
    await w.get("select").setValue("paid");
    expect(w.text()).toContain("顯示 10／30 筆");
    await w.get("[data-testid=clear-filters]").trigger("click");
    expect(w.text()).toContain("顯示 30／30 筆");
    await input.setValue("不存在的字");
    expect(w.text()).toContain("沒有符合");
    w.unmount();
  });

  it("changing search emits clear-target, and search is NFKC/case/space insensitive", async () => {
    const w = mount(DataSection, {
      props: {
        title: "商品",
        items: [{ id: "p1", name: "DEMO-001", status: "active" }],
        searchText: (r: Row) => r.name,
        statusOf: (r: Row) => r.status,
        targetId: null,
      },
      slots: { item: ({ item }: { item: Row }) => h("span", { class: "row-id" }, item.id) },
    });
    await w.get("input[type=search]").setValue("ＤＥＭＯ　－００１");
    expect(w.findAll(".row-id")).toHaveLength(1);
    expect(w.emitted("clear-target")).toBeTruthy();
  });
});
